import os, sys, json, argparse, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from skill_dream.config import BENCHMARK_ROOT, AGENT_CONFIG
SWE = str(BENCHMARK_ROOT)
sys.path.insert(0, os.path.join(SWE, 'adapter'))
from skill_dream.llm import LLMClient
from skill_dream.skill_store import SkillStore
POOL_ROOT = os.path.join(SWE, 'verified_pool_sonnet')
MODEL = os.environ.get('SD_MODEL', 'claude-sonnet-4-6')
DISTILL_TAG = 'verified_sonnet'

def repo_key(repo):
    return repo.replace('/', '__')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repos', default='')
    ap.add_argument('--cap_per_repo', type=int, default=0)
    a = ap.parse_args()
    import methods as M
    all_rows = [json.loads(l) for l in open(os.path.join(SWE, 'data', 'swebench_verified.jsonl'))]
    main_ids = set(json.load(open(os.path.join(SWE, 'verified_main100.json'))))
    ev_by_repo = collections.defaultdict(list)
    for r in all_rows:
        if r['instance_id'] in main_ids:
            continue
        ev_by_repo[r['repo']].append(r)
    for repo in ev_by_repo:
        ev_by_repo[repo].sort(key=lambda r: r.get('created_at', ''))
    want = set(a.repos.split(',')) if a.repos else None
    llm = LLMClient()
    for (repo, evs) in sorted(ev_by_repo.items(), key=lambda kv: -len(kv[1])):
        rk = repo_key(repo)
        if want and rk not in want:
            continue
        cand = evs[:a.cap_per_repo] if a.cap_per_repo else evs
        proot = os.path.join(POOL_ROOT, rk)
        os.makedirs(os.path.join(proot, 'current'), exist_ok=True)
        os.makedirs(os.path.join(proot, 'history'), exist_ok=True)
        store = SkillStore(proot)
        print('[opus-pool] %s: distilling from %d evidence PRs' % (rk, len(cand)), flush=True)
        for (i, src) in enumerate(cand):
            try:
                skills = M.distill_source_pr(llm, DISTILL_TAG, src, model=MODEL)
            except Exception as e:
                print('  distill err', src['instance_id'][:40], str(e)[:80], flush=True)
                skills = []
            for sk in skills:
                store.apply_op('ADD', sk, note='verified opus evidence %s' % src['instance_id'])
            if (i + 1) % 10 == 0:
                store.save()
                print('  [%s] %d/%d -> %d skills' % (rk, i + 1, len(cand), len(store.skills)), flush=True)
        store.save()
        print('[opus-pool] %s DONE: %d skills from %d PRs' % (rk, len(store.skills), len(cand)), flush=True)
    print('[opus-pool] ALL DONE', flush=True)
if __name__ == '__main__':
    main()
