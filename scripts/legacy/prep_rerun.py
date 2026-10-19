import json, os, glob, time, shutil

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False
report = json.load(open('_false429_strict.json'))
report = {f: v for (f, v) in report.items() if not os.path.basename(f).startswith('records_dn_')}
summary = {}
for (f, false_ids) in report.items():
    rows = [json.loads(l) for l in open(f) if l.strip()]
    all_ids = [r['instance_id'] for r in rows]
    fset = set(false_ids)
    keep = [r for r in rows if not (r['instance_id'] in fset and (not res(r)))]
    dropped = len(rows) - len(keep)
    if dropped:
        shutil.copy(f, f + '.bak429rerun_%d' % int(time.time()))
        with open(f, 'w') as w:
            for r in keep:
                w.write(json.dumps(r) + '\n')
    seen = set()
    ids = []
    for i in all_ids:
        if i not in seen:
            seen.add(i)
            ids.append(i)
    idf = '_rerunids_%s.json' % os.path.basename(f).replace('records_', '').replace('.jsonl', '')
    json.dump(ids, open(idf, 'w'))
    summary[f] = {'total': len(rows), 'dropped_false429': dropped, 'kept': len(keep), 'idfile': idf, 'n_ids': len(ids)}
    print('%-46s drop=%d kept=%d ids=%d -> %s' % (f, dropped, len(keep), len(ids), idf))
json.dump(summary, open('_rerun_summary.json', 'w'), indent=1)
print('\nTOTAL dropped:', sum((v['dropped_false429'] for v in summary.values())))
