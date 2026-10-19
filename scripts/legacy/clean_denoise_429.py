import json, sys, os, time, shutil
tags = sys.argv[1:] or ['dn_current', 'dn_top1', 'dn_top2', 'dn_filt02', 'dn_filt04', 'dn_filt06']
for tag in tags:
    fp = f'records_{tag}.jsonl'
    if not os.path.exists(fp):
        continue
    rows = [json.loads(l) for l in open(fp) if l.strip()]
    keep = []
    drop = 0
    for r in rows:
        cand = r.get('n_candidates')
        db = r.get('diff_bytes', 0)
        tok = r.get('tokens') or 0
        contaminated = cand == 0 or (db == 0 and tok < 60000)
        if contaminated and (not r.get('task_success_strict')):
            drop += 1
        else:
            keep.append(r)
    if drop:
        shutil.copy(fp, fp + f'.bak429_{int(time.time())}')
        with open(fp, 'w') as f:
            for r in keep:
                f.write(json.dumps(r) + '\n')
    print(f'{tag}: total={len(rows)} kept={len(keep)} dropped_429={drop}')
