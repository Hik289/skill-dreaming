import json, glob

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False
files = sorted(glob.glob('records_*.jsonl'))
report = {}
total = 0
print('%-48s %5s %5s %8s' % ('file', 'n', 'res', 'false429'))
for f in files:
    rows = [json.loads(l) for l in open(f) if l.strip()]
    fe = []
    for r in rows:
        if res(r):
            continue
        nc = r.get('n_candidates')
        if nc == 0:
            fe.append(r.get('instance_id'))
    if fe:
        print('%-48s %5d %5d %8d' % (f, len(rows), sum((res(r) for r in rows)), len(fe)))
        report[f] = fe
        total += len(fe)
json.dump(report, open('_false429_strict.json', 'w'), indent=0)
print('\nTOTAL strict false-429 (ncand==0):', total)
print('files affected:', len(report))
