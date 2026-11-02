import os

def changed_files_from_patch(patch):
    files = []
    for ln in (patch or '').splitlines():
        if ln.startswith('+++ b/') or ln.startswith('--- a/'):
            p = ln[6:].strip()
            if p and p != '/dev/null' and (p not in files):
                files.append(p)
    return files

def surfaces_from_files(files):
    surf = set()
    for f in files:
        fl = f.lower()
        if fl.endswith(('.py',)) and ('/test' in fl or os.path.basename(fl).startswith('test')):
            surf.add('tests')
        elif fl.endswith(('.rst', '.md', '.txt')):
            surf.add('docs')
        elif 'changelog' in fl or 'changes' in fl or '/news' in fl:
            surf.add('changelog')
        elif fl.endswith(('.cfg', '.toml', '.ini', '.yml', '.yaml')):
            surf.add('config')
        else:
            surf.add('code')
    return sorted(surf)
