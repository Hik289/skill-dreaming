import json, sys
files = sys.argv[1:]

def tok(r):
    return (r.get('tokens') if r.get('tokens') is not None else r.get('tok')) or 0

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False

def db(r):
    for k in ('diff_bytes', 'diff_size'):
        if k in r and r[k] is not None:
            return r[k]
    return None
for f in files:
    rows = [json.loads(l) for l in open(f) if l.strip()]
    print('\n=== %s (n=%d res=%d) ===' % (f, len(rows), sum((res(r) for r in rows))))
    print('  unresolved records, sorted by tokens:')
    un = [r for r in rows if not res(r)]
    for r in sorted(un, key=tok):
        print('    tok=%-8s diff=%-6s ncand=%-4s empty=%-5s %s' % (tok(r), db(r), r.get('n_candidates'), r.get('empty_patch'), r.get('instance_id')))
