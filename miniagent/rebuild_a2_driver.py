import os, sys, json, glob, re, time, subprocess, argparse, hashlib, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skill_dream.config import BENCHMARK_ROOT, AGENT_CONFIG
SWE = str(BENCHMARK_ROOT)
MINI = os.path.join(SWE, 'miniagent')
sys.path.insert(0, os.path.join(SWE, 'adapter'))
POOL = os.environ.get('SD_PRO_SKILL_POOL') or os.path.join(MINI, 'pro_related_nogold')
EMB_CACHE = os.path.join(MINI, 'skill_emb_cache')
REPOS = {'ansible': 'ansible__ansible', 'openlibrary': 'internetarchive__openlibrary', 'qutebrowser': 'qutebrowser__qutebrowser'}
BARE = {'ansible': os.path.join(SWE, 'repos_cache', 'ansible__ansible.git'), 'openlibrary': os.path.join(SWE, 'repos_cache', 'internetarchive__openlibrary.git'), 'qutebrowser': os.path.join(SWE, 'repos_cache', 'qutebrowser__qutebrowser.git')}
from skill_dream.embedding import embed_one, cosine

def repo_of(i):
    return 'ansible' if 'ansible' in i else 'openlibrary' if 'openlibrary' in i else 'qutebrowser'
_shacache = {}

def sha_date(repo, sha):
    if not sha:
        return None
    k = (repo, sha)
    if k in _shacache:
        return _shacache[k]
    try:
        r = subprocess.run(['git', '-C', BARE[repo], 'show', '-s', '--format=%cI', sha], capture_output=True, text=True, timeout=30)
        dt = r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        dt = None
    _shacache[k] = dt
    return dt
_pool = {}

def load_pool(repo):
    if repo in _pool:
        return _pool[repo]
    sk = [json.load(open(f)) for f in glob.glob(POOL + '/' + REPOS[repo] + '/current/*.json')]
    _pool[repo] = sk
    return sk

def skill_embed_text(sk):
    tr = sk.get('trigger', {}) or {}
    parts = [sk.get('name', '').replace('-', ' ')]
    parts += [str(k) for k in tr.get('keywords', [])]
    parts += [str(s) for s in tr.get('repository_surfaces', [])]
    parts += [str(p) for p in sk.get('procedure', [])]
    return '  '.join(parts)[:8000]

def cache_key(t):
    identity = os.environ.get('SD_EMBEDDING_ENDPOINT', '') + os.environ.get('SD_EMBEDDING_MODEL', '')
    return hashlib.sha256((identity + '\n' + t).encode('utf-8', 'replace')).hexdigest()

def embed_cached_one(t):
    cp = os.path.join(EMB_CACHE, cache_key(t) + '.json')
    if os.path.exists(cp):
        try:
            return json.load(open(cp))
        except Exception:
            pass
    v = embed_one(t)
    try:
        json.dump(v, open(cp, 'w'))
    except Exception:
        pass
    return v

def retrieve_top8(problem, skills, top_k=8, min_cos=0.2):
    if not skills:
        return []
    q = embed_one(problem[:8000])
    scored = []
    for sk in skills:
        v = embed_cached_one(skill_embed_text(sk))
        c = cosine(q, v)
        scored.append((c, sk))
    scored.sort(key=lambda x: x[0], reverse=True)
    from skill_dream.skill_context import compatible_subset
    return [sk.to_dict() for sk in compatible_subset([sk for c, sk in scored if c >= min_cos], top_k)]
SKILL_PREAMBLE = "The following engineering patterns were distilled from this repository's own merged history of fixing similar issues. They encode where relevant code tends to live and how fixes in this codebase are structured. Treat them as strong priors from a senior maintainer of THIS repo:\n- Early in your exploration, open and read the files/modules these patterns point to.\n- Prefer the conventions they describe unless the code clearly contradicts them.\n- Heed every listed pitfall; they mark mistakes previously made on this repo.\n"

def render_skills(skills):
    if not skills:
        return ''
    lines = ['<repository_skills>', SKILL_PREAMBLE]
    for (i, sk) in enumerate(skills, 1):
        tr = sk.get('trigger', {}) or {}
        nm = sk.get('name', '')
        applies_parts = [tr.get('task_type', '')] + list(tr.get('keywords', []) or [])
        applies = ', '.join((str(x) for x in applies_parts if x))
        proc = sk.get('procedure', [])
        pit = sk.get('negative_constraints', []) or []
        lines.append('Skill %d: %s' % (i, nm))
        lines.append('  Applies when: %s' % applies)
        lines.append('  Approach: %s' % (proc,))
        if pit:
            lines.append('  Pitfall to avoid: %s' % (pit,))
        lines.append('')
    lines.append('</repository_skills>')
    return '\n'.join(lines)

def build_task(inst, method):
    ps = inst.get('problem_statement', '')
    if method == 'none':
        return (ps, 0)
    repo = repo_of(inst['instance_id'])
    tdate = str(DATES.get(inst['instance_id'], ''))
    skills = load_pool(repo)
    safe = []
    from skill_dream.skill_context import eligible, pack_skills
    from skill_dream.skill_store import _timestamp
    for sk in skills:
        sources = sk.get('positive_evidence') or []
        dates = [_timestamp(sha_date(repo, source)) for source in sources if isinstance(source, str)]
        cutoff = _timestamp(tdate)
        if not dates or len(dates) != len(sources) or cutoff is None or any(d is None or d >= cutoff for d in dates):
            continue
        candidate = dict(sk)
        candidate['version_scope'] = dict(sk.get('version_scope') or {})
        candidate['version_scope']['available_at'] = max(dates).isoformat()
        candidate['version_scope'].setdefault('date', max(dates).isoformat())
        if eligible(candidate, tdate, [inst['instance_id'], inst.get('base_commit')], BARE[repo], inst.get('base_commit')):
            safe.append(candidate)
    top = retrieve_top8(ps, safe, top_k=8, min_cos=0.2)
    block, included, _ = pack_skills(top, int(os.environ.get('SD_SKILL_CONTEXT_CHARS', '12000')))
    return (ps + ('\n\n' + block if block else ''), len(included))

def run_one(iid, method, tag):
    from minisweagent.environments.docker import DockerEnvironment
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.models.litellm_model import LitellmModel
    inst = ROWS[iid]
    inst['created_at'] = DATES.get(iid, '')
    (task, nsk) = build_task(inst, method)
    envcfg = dict(CFG['environment'])
    envcfg['image'] = 'jefzda/sweap-images:' + inst['dockerhub_tag']
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
    return {'instance_id': iid, 'method': method, 'n_skills': nsk, 'model_patch': patch, 'exit_status': exit_status}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--method', required=True)
    ap.add_argument('--ids_file', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    global DATES, ROWS, CFG
    DATES = json.load(open(os.path.join(SWE, 'data', 'pro_created_at.json')))
    ROWS = {r['instance_id']: r for r in (json.loads(l) for l in open(os.path.join(SWE, 'data', 'swebench_pro.jsonl')))}
    CFG = json.load(open(AGENT_CONFIG))
    ids = json.load(open(a.ids_file)) if a.ids_file.endswith('.json') else [l.strip() for l in open(a.ids_file)]
    ids = [i for i in ids if i in ROWS]
    if a.limit:
        ids = ids[:a.limit]
    outp = os.path.join(MINI, 'rebuild_preds_%s_%s.jsonl' % (a.method, a.tag))
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
        futs = {ex.submit(run_one, i, a.method, a.tag): i for i in todo}
        n = 0
        for f in as_completed(futs):
            iid = futs[f]
            try:
                rec = f.result()
            except Exception as e:
                rec = {'instance_id': iid, 'method': a.method, 'model_patch': '', 'exit_status': 'ERROR:' + str(e)[:120]}
            with open(outp, 'a') as w:
                w.write(json.dumps(rec) + '\n')
            n += 1
            print('  [%s] %d/%d %s sk=%s bytes=%d exit=%s' % (a.method, n, len(todo), iid[:48], rec.get('n_skills'), len(rec['model_patch']), rec.get('exit_status')), flush=True)
    print('[%s:%s] DONE' % (a.method, a.tag), flush=True)
if __name__ == '__main__':
    main()
