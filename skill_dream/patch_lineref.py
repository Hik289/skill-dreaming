from __future__ import annotations
from .pr_loader import get_file_at

def _file_priority(f: str) -> int:
    p = f.lower()
    if p.startswith('src/') and p.endswith('.py'):
        return 0
    if p.endswith('.py') and ('test' in p or p.startswith('tests/')):
        return 1
    if p.endswith('.py'):
        return 0
    if p.endswith(('.cfg', '.ini', '.toml')):
        return 2
    return 3

def build_base_context_numbered(repo: str, base: str, hint_files: list, max_files: int=6, max_lines: int=400) -> tuple:
    parts = []
    file_lines = {}
    ordered = sorted(hint_files, key=_file_priority)
    for f in ordered[:max_files]:
        content = get_file_at(repo, base, f)
        if content is None:
            continue
        lines = content.split('\n')
        file_lines[f] = lines
        shown = lines[:max_lines]
        numbered = '\n'.join((f'{i + 1:5d}| {ln}' for (i, ln) in enumerate(shown)))
        trunc = '' if len(lines) <= max_lines else f'\n... (file has {len(lines)} lines, showing first {max_lines})'
        parts.append(f'=== FILE: {f} ({len(lines)} lines) ===\n{numbered}{trunc}')
    if not parts:
        import subprocess
        tree = subprocess.run(['git', '-C', repo, 'ls-tree', '-r', '--name-only', base], capture_output=True, text=True).stdout
        parts.append('=== REPO FILE TREE (base) ===\n' + '\n'.join(tree.splitlines()[:200]))
    return ('\n\n'.join(parts), file_lines)

def apply_lineref_edits(sandbox, edits: list, new_files: dict, file_lines_map: dict) -> dict:
    (applied, failed) = ([], [])
    by_path = {}
    for e in edits:
        by_path.setdefault(e.get('path'), []).append(e)
    for (path, es) in by_path.items():
        base_lines = file_lines_map.get(path)
        content = sandbox.read_file(path)
        if content is None or base_lines is None:
            for e in es:
                failed.append({'path': path, 'reason': 'file not in base context', 'edit': _brief(e)})
            continue
        cur_lines = content.split('\n')
        n = len(cur_lines)
        norm = []
        ok = True
        for e in es:
            try:
                s = int(e['start_line'])
                t = int(e.get('end_line', e['start_line']))
            except Exception:
                failed.append({'path': path, 'reason': 'start/end_line not int', 'edit': _brief(e)})
                ok = False
                continue
            if s < 1 or t < s or t > n:
                failed.append({'path': path, 'reason': f'line range out of bounds (1..{n}, got {s}..{t})', 'edit': _brief(e)})
                ok = False
                continue
            norm.append((s, t, e.get('replacement', '')))
        if not ok:
            continue
        norm.sort()
        overlap = False
        for i in range(1, len(norm)):
            if norm[i][0] <= norm[i - 1][1]:
                overlap = True
                break
        if overlap:
            for e in es:
                failed.append({'path': path, 'reason': 'edit line ranges overlap', 'edit': _brief(e)})
            continue
        new_lines = list(cur_lines)
        for (s, t, repl) in sorted(norm, reverse=True):
            repl_lines = repl.split('\n') if repl != '' else []
            new_lines[s - 1:t] = repl_lines
        sandbox.write_file(path, '\n'.join(new_lines))
        applied.append({'path': path, 'n_edits': len(es)})
    for (path, content) in new_files.items():
        sandbox.write_file(path, content)
        applied.append({'path': path, 'n_edits': 'new_file'})
    n_halluc = sum((1 for f in failed if 'out of bounds' in f['reason']))
    return {'applied': applied, 'failed': failed, 'clean': bool(applied) and (not failed), 'n_out_of_range': n_halluc}

def _brief(e):
    return {k: e.get(k) for k in ('path', 'start_line', 'end_line')}
