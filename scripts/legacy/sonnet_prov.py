import json, glob, os
os.chdir(os.environ.get('SD_BENCH_ROOT', '.'))
pool = glob.glob('verified_pool_sonnet/*/current/*.json')
sonnet_tag = opus_tag = both = neither = 0
contaminated = []
for f in pool:
    d = json.load(open(f))
    src = (d.get('version_scope') or {}).get('source_id')
    name = d.get('name')
    if not src:
        neither += 1
        continue
    slug = src.replace('/', '__')
    scf = 'skill_cache/verified_sonnet__' + slug + '.json'
    ocf = 'skill_cache/verified__' + slug + '.json'
    in_s = os.path.exists(scf) and any((x.get('name') == name for x in json.load(open(scf))))
    in_o = False
    if os.path.exists(ocf):
        om = next((x for x in json.load(open(ocf)) if x.get('name') == name), None)
        if om and om.get('procedure') == d.get('procedure'):
            in_o = True
    if in_s and (not in_o):
        sonnet_tag += 1
    elif in_o and (not in_s):
        opus_tag += 1
        contaminated.append((name, src))
    elif in_s and in_o:
        both += 1
    else:
        neither += 1
print('total:', len(pool), 'repos:', len(glob.glob('verified_pool_sonnet/*/current')))
print('sonnet-cache:', sonnet_tag, 'opus-cache-content(CONTAM):', opus_tag, 'both:', both, 'neither:', neither)
print('CLEAN' if opus_tag == 0 else 'CONTAMINATED: ' + str(contaminated[:8]))
