import json, os, time, shutil

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False
M = json.load(open('_main4_false429.json'))
plan = {}
for (f, ids) in M.items():
    idset = set(ids)
    rows = [json.loads(l) for l in open(f) if l.strip()]
    keep = [r for r in rows if not (r['instance_id'] in idset and (not res(r)) and (r.get('n_candidates') == 0))]
    dropped = len(rows) - len(keep)
    assert dropped == len(idset), '%s: dropped %d != flagged %d' % (f, dropped, len(idset))
    shutil.copy(f, f + '.bak_main4_%d' % int(time.time()))
    with open(f, 'w') as w:
        for r in keep:
            w.write(json.dumps(r) + '\n')
    idf = '_rr_' + os.path.basename(f).replace('records_', '').replace('.jsonl', '') + '.json'
    json.dump(ids, open(idf, 'w'))
    plan[f] = {'ids': ids, 'idfile': idf, 'dropped': dropped, 'kept': len(keep)}
    print('%-42s dropped=%d kept=%d -> %s (%d ids)' % (f, dropped, len(keep), idf, len(ids)))
json.dump(plan, open('_main4_rerun_plan.json', 'w'), indent=1)
print('TOTAL to rerun:', sum((len(v['ids']) for v in plan.values())))
