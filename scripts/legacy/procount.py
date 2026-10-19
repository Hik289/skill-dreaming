import json, os, glob
for f in sorted(glob.glob('records_*_pro100.jsonl')):
    ids = set()
    for l in open(f):
        l = l.strip()
        if l:
            ids.add(json.loads(l)['instance_id'])
    print(f, len(ids))
