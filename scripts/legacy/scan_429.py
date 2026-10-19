import json, os, glob, sys

def toknum(r):
    t = r.get('tokens')
    if t is None:
        t = r.get('tok')
    return t or 0

def is_resolved(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False

def diffbytes(r):
    for k in ('diff_bytes', 'diff_size'):
        if k in r and r[k] is not None:
            return r[k]
    return None

def ncand(r):
    return r.get('n_candidates')
files = sorted(glob.glob('records_*.jsonl'))
total_false = 0
print('%-46s %5s %5s %6s %7s %7s' % ('file', 'n', 'res', 'false', 'genEmp', 'other0'))
report = {}
for f in files:
    rows = []
    for l in open(f):
        l = l.strip()
        if l:
            try:
                rows.append(json.loads(l))
            except:
                pass
    n = len(rows)
    res = sum((1 for r in rows if is_resolved(r)))
    false_empty = []
    genuine_empty = 0
    for r in rows:
        if is_resolved(r):
            continue
        db = diffbytes(r)
        nc = ncand(r)
        tok = toknum(r)
        cond_nc0 = nc == 0
        cond_empty_lowtok = db == 0 and tok < 60000
        if cond_nc0 or cond_empty_lowtok:
            false_empty.append(r.get('instance_id'))
        elif db == 0:
            genuine_empty += 1
    nf = len(false_empty)
    total_false += nf
    report[f] = false_empty
    other0 = sum((1 for r in rows if not is_resolved(r) and diffbytes(r) == 0)) - genuine_empty - nf
    if nf or genuine_empty:
        print('%-46s %5d %5d %6d %7d %7d' % (f, n, res, nf, genuine_empty, max(0, other0)))
print('\nTOTAL suspected false-empty (429/API) across all files:', total_false)
json.dump(report, open('_false429_report.json', 'w'), indent=0)
print('wrote _false429_report.json')
