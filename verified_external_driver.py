import os, sys, json, glob, time, argparse, hashlib, collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_dream.config import BENCHMARK_ROOT, AGENT_CONFIG
SWE = str(BENCHMARK_ROOT)
MINI = os.path.join(SWE, 'miniagent')
sys.path.insert(0, os.path.join(SWE, 'adapter'))
POOL = os.environ.get('SD_SKILL_POOL') or os.path.join(SWE, 'verified_pool')
EMB_CACHE = os.path.join(MINI, 'skill_emb_cache')
os.makedirs(EMB_CACHE, exist_ok=True)
from skill_dream.embedding import embed_one, cosine

def repo_key(repo):
    return repo.replace('/', '__')

def dockerhub_image(iid):
    (repo, num) = iid.rsplit('-', 1)
    (owner, name) = repo.split('__')
    return 'swebench/sweb.eval.x86_64.%s_1776_%s-%s:latest' % (owner, name, num)

def kw(text, n=60):
    import re
    toks = re.findall('[A-Za-z_][A-Za-z0-9_]{2,}', (text or '').lower())
    seen = []
    for t in toks:
        if t not in seen:
            seen.append(t)
        if len(seen) >= n:
            break
    return seen
_pool = {}

def load_pool(repo):
    rk = repo_key(repo)
    if rk in _pool:
        return _pool[rk]
    sk = [json.load(open(f)) for f in glob.glob(os.path.join(POOL, rk, 'current', '*.json'))]
    _pool[rk] = sk
    return sk

def leak_safe_pool(repo, tdate):
    from skill_dream.skill_context import eligible
    out = []
    for sk in load_pool(repo):
        if tdate and eligible(sk, tdate, globals().get('MAIN', ())):
            out.append(sk)
    return out
_ev = {}

def evidence_for_repo(repo):
    if repo in _ev:
        return _ev[repo]
    rows = [r for r in ROWS.values() if r['repo'] == repo and r['instance_id'] not in MAIN]
    rows.sort(key=lambda r: r.get('created_at', ''))
    _ev[repo] = rows
    return rows

def sk_text(sk):
    tr = sk.get('trigger', {}) or {}
    parts = [sk.get('name', '').replace('-', ' ')] + [str(k) for k in tr.get('keywords', [])]
    parts += [str(s) for s in tr.get('repository_surfaces', [])] + [str(p) for p in sk.get('procedure', [])]
    return '  '.join(parts)[:8000]

def rel_kw(sk, kws):
    hay = sk_text(sk).lower()
    tr = sk.get('trigger', {}) or {}
    return sum((1 for w in kws if len(w) >= 3 and w in hay))

def retr_skilllens(repo, tdate, kws, tt, top_k=8):
    pool = leak_safe_pool(repo, tdate)
    GRAN = ['policy', 'strategy', 'procedure', 'primitive']
    graph = {g: [] for g in GRAN}
    for sk in pool:
        nsurf = len((sk.get('trigger', {}) or {}).get('repository_surfaces', []) or [])
        nproc = len(sk.get('procedure', []) or [])
        g = 'policy' if nsurf >= 3 else 'strategy' if nsurf == 2 else 'procedure' if nproc >= 3 else 'primitive'
        graph[g].append(sk)
    picked = []
    per = max(1, top_k // len(GRAN))
    for g in GRAN:
        cand = sorted(graph[g], key=lambda s: rel_kw(s, kws), reverse=True)
        for s in cand[:per]:
            if rel_kw(s, kws) > 0:
                picked.append(s)
    if len(picked) < top_k:
        allc = sorted(pool, key=lambda s: rel_kw(s, kws), reverse=True)
        for s in allc:
            if s not in picked and rel_kw(s, kws) > 0:
                picked.append(s)
            if len(picked) >= top_k:
                break
    return picked[:top_k]

def retr_codeskill(repo, tdate, kws, tt, top_k=8):
    pool = leak_safe_pool(repo, tdate)
    scored = []
    for sk in pool:
        conf = sk.get('confidence', 0.5) or 0.5
        rel = rel_kw(sk, kws)
        score = conf + rel
        if rel > 0 or conf > 0.5:
            scored.append((score, sk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for (_, s) in scored[:top_k]]

def retr_l2c(repo, tdate, kws, tt, top_k=8):
    mem = []
    for r in evidence_for_repo(repo):
        if r.get('created_at', '') >= tdate:
            continue
        subj = r.get('problem_statement', '')[:200]
        hay = subj.lower()
        rel = sum((1 for w in kws if len(w) >= 3 and w in hay))
        mem.append((rel, r.get('created_at', ''), r))
    mem.sort(key=lambda x: (x[0], x[1]), reverse=True)
    out = []
    for (rel, d, r) in mem[:top_k]:
        out.append({'name': 'l2c-mem-%s' % r['instance_id'], 'trigger': {'task_type': tt, 'keywords': []}, 'procedure': ['Historical commit memory %s: %s' % (r['instance_id'], r.get('problem_statement', '')[:160]), '(L2C: chronological repo memory, not a distilled skill)'], 'negative_constraints': []})
    return out

def retr_socratic(repo, tdate, kws, tt, top_k=8):
    return [{'name': 'socratic-iter-guide', 'trigger': {'task_type': tt, 'keywords': []}, 'procedure': ['(Socratic-SWE training-free approx: self-questioning iteration, not the trained version)', 'Which files and functions does this change touch? (localization)', 'Do tests/docs/changelog need synchronized updates? (maintenance surface)', 'Are boundary conditions and error paths covered? (robustness)', "Is it consistent with the repo's existing interface style? (alignment)"], 'negative_constraints': []}]
METHODS = {'skilllens': retr_skilllens, 'codeskill': retr_codeskill, 'l2c': retr_l2c, 'socratic': retr_socratic}
PREAMBLE = "The following engineering patterns were distilled from this repository's own merged history of fixing similar issues. Treat them as strong priors from a senior maintainer of THIS repo:\n- Early in your exploration, open and read the files/modules these patterns point to.\n- Prefer the conventions they describe unless the code clearly contradicts them.\n- Heed every listed pitfall; they mark mistakes previously made on this repo.\n"

def render(skills):
    if not skills:
        return ''
    lines = ['<repository_skills>', PREAMBLE]
    for (i, sk) in enumerate(skills, 1):
        tr = sk.get('trigger', {}) or {}
        applies = ', '.join((str(x) for x in [tr.get('task_type', '')] + list(tr.get('keywords', []) or []) if x))
        lines.append('Skill %d: %s' % (i, sk.get('name', '')))
        lines.append('  Applies when: %s' % applies)
        lines.append('  Approach: %s' % (sk.get('procedure', []),))
        pit = sk.get('negative_constraints', []) or []
        if pit:
            lines.append('  Pitfall to avoid: %s' % (pit,))
        lines.append('')
    lines.append('</repository_skills>')
    return '\n'.join(lines)

def build_task(inst, method):
    ps = inst.get('problem_statement', '')
    repo = inst['repo']
    tdate = str(inst.get('created_at', ''))
    kws = kw(ps, 60)
    import re
    tt = 'bugfix'
    top = METHODS[method](repo, tdate, kws, tt, top_k=8)
    from skill_dream.skill_context import pack_skills
    block, included, _ = pack_skills(top, int(os.environ.get('SD_SKILL_CONTEXT_CHARS', '12000')))
    return (ps + ('\n\n' + block if block else ''), len(included))

def run_one(iid, method):
    from minisweagent.environments.docker import DockerEnvironment
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.models.litellm_model import LitellmModel
    inst = ROWS[iid]
    (task, nsk) = build_task(inst, method)
    envcfg = dict(CFG['environment'])
    envcfg['image'] = dockerhub_image(iid)
    envcfg['cwd'] = '/testbed'
    envcfg['pull_timeout'] = 1800
    envcfg['timeout'] = 180
    mk = dict(CFG['model'].get('model_kwargs', {}))
    model = LitellmModel(model_name=CFG['model']['model_name'], **mk)
    env_kwargs = {k: v for (k, v) in envcfg.items() if k in ('image', 'cwd', 'env', 'forward_env', 'timeout', 'run_args', 'container_timeout', 'pull_timeout')}
    env = DockerEnvironment(**env_kwargs)
    agent_kwargs = {k: CFG['agent'][k] for k in ('system_template', 'instance_template', 'step_limit', 'cost_limit', 'wall_time_limit_seconds', 'max_consecutive_format_errors') if k in CFG['agent']}
    agent = DefaultAgent(model, env, **agent_kwargs)
    patch = ''
    exit_status = None
    try:
        res = agent.run(task=task)
        if isinstance(res, dict):
            exit_status = res.get('exit_status')
            patch = res.get('submission', '') or ''
    finally:
        try:
            env.cleanup()
        except Exception:
            pass
    return {'instance_id': iid, 'method': method, 'n_skills': nsk, 'model_patch': patch, 'model_name_or_path': 'skilldream_verified', 'exit_status': exit_status}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--method', required=True, choices=list(METHODS.keys()))
    ap.add_argument('--ids_file', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    global ROWS, MAIN, CFG
    ROWS = {r['instance_id']: r for r in (json.loads(l) for l in open(os.path.join(SWE, 'data', 'swebench_verified.jsonl')))}
    MAIN = set(json.load(open(os.path.join(SWE, 'verified_main100.json'))))
    CFG = json.load(open(AGENT_CONFIG))
    ids = json.load(open(a.ids_file))
    ids = [i for i in ids if i in ROWS]
    if a.limit:
        ids = ids[:a.limit]
    outp = os.path.join(SWE, 'verified_preds_%s_%s.jsonl' % (a.method, a.tag))
    done = set()
    if os.path.exists(outp):
        for l in open(outp):
            try:
                done.add(json.loads(l)['instance_id'])
            except Exception:
                pass
    todo = [i for i in ids if i not in done]
    print('[%s:%s] total=%d done=%d todo=%d' % (a.method, a.tag, len(ids), len(done), len(todo)), flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, i, a.method): i for i in todo}
        n = 0
        for f in as_completed(futs):
            iid = futs[f]
            try:
                rec = f.result()
            except Exception as e:
                rec = {'instance_id': iid, 'method': a.method, 'model_patch': '', 'model_name_or_path': 'skilldream_verified', 'exit_status': 'ERROR:' + str(e)[:160]}
            with open(outp, 'a') as w:
                w.write(json.dumps(rec) + '\n')
            n += 1
            print('  [%s] %d/%d %s sk=%s bytes=%d exit=%s' % (a.method, n, len(todo), iid[:46], rec.get('n_skills'), len(rec['model_patch']), rec.get('exit_status')), flush=True)
    print('[%s:%s] GEN DONE -> %s' % (a.method, a.tag, outp), flush=True)
if __name__ == '__main__':
    main()
