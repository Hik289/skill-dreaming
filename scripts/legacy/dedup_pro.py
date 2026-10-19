import json, shutil, time, sys

def tokz(r):
    return int(float(r.get('tokens', 0) or 0)) == 0

def tb(x):
    return str(x).lower() in ('true', '1')
for m in ['base_v2', 'repo_context_v2']:
    f = f'records_{m}_pro100.jsonl'
    rows = [json.loads(l) for l in open(f)]
    byid = {}
    for r in rows:
        byid.setdefault(r['instance_id'], []).append(r)
    keep = []
    for (iid, rs) in byid.items():
        good = [r for r in rs if not tokz(r)]
        keep.append((good or rs)[-1])
    shutil.copy(f, f'_pro_corrupt_bak/{f}.{int(time.time())}.dedup.bak')
    with open(f, 'w') as out:
        for r in keep:
            out.write(json.dumps(r) + '\n')
    res = sum((1 for r in keep if tb(r.get('task_success_strict'))))
    print(f'{m}: rows={len(keep)} resolved={res}')
