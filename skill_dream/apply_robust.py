from __future__ import annotations
import re

def _normalize_ws(s: str) -> str:
    lines = [ln.rstrip() for ln in s.split('\n')]
    (out, prev_blank) = ([], False)
    for ln in lines:
        blank = ln.strip() == ''
        if blank and prev_blank:
            continue
        out.append(ln)
        prev_blank = blank
    return '\n'.join(out)

def _find_exact(content, search):
    idx = content.find(search)
    if idx < 0:
        return None
    if content.count(search) > 1:
        return 'ambiguous'
    return (idx, idx + len(search))

def _find_ws(content, search):
    c_lines = content.split('\n')
    s_norm = [ln.rstrip() for ln in search.split('\n') if ln.strip() != '']
    if not s_norm:
        return None
    c_norm = [ln.rstrip() for ln in c_lines]
    matches = []
    for i in range(len(c_norm)):
        (j, k) = (i, 0)
        while j < len(c_norm) and k < len(s_norm):
            if c_norm[j].strip() == '':
                j += 1
                continue
            if c_norm[j] == s_norm[k]:
                j += 1
                k += 1
            else:
                break
        if k == len(s_norm):
            matches.append((i, j))
    if len(matches) == 1:
        return ('lines', matches[0])
    if len(matches) > 1:
        return 'ambiguous'
    return None

def _find_strip(content, search):
    c_lines = content.split('\n')
    s_lines = [ln.strip() for ln in search.split('\n') if ln.strip() != '']
    if not s_lines:
        return None
    c_strip = [ln.strip() for ln in c_lines]
    matches = []
    for i in range(len(c_strip)):
        (j, k) = (i, 0)
        while j < len(c_strip) and k < len(s_lines):
            if c_strip[j] == '':
                j += 1
                continue
            if c_strip[j] == s_lines[k]:
                j += 1
                k += 1
            else:
                break
        if k == len(s_lines):
            matches.append((i, j))
    if len(matches) == 1:
        return ('lines', matches[0])
    if len(matches) > 1:
        return 'ambiguous'
    return None

def _find_anchor(content, search):
    s_lines = [ln for ln in search.split('\n') if ln.strip() != '']
    if len(s_lines) < 2:
        return None
    (first, last) = (s_lines[0].strip(), s_lines[-1].strip())
    c_lines = content.split('\n')
    c_strip = [ln.strip() for ln in c_lines]
    starts = [i for (i, ln) in enumerate(c_strip) if ln == first]
    if len(starts) != 1:
        return None
    i = starts[0]
    ends = [j for j in range(i + 1, len(c_strip)) if c_strip[j] == last]
    if not ends:
        return None
    j = ends[0]
    if j - i + 1 > max(len(s_lines) * 3, len(s_lines) + 10):
        return None
    return ('lines', (i, j + 1))

def apply_edits_robust(sandbox, edits: list, new_files: dict) -> dict:
    (applied, failed) = ([], [])
    tiers = {'exact': 0, 'ws_normalized': 0, 'strip_lines': 0, 'anchor': 0}
    for e in edits:
        (path, search, replace) = (e['path'], e['search'], e.get('replace', ''))
        content = sandbox.read_file(path)
        if content is None:
            failed.append({'path': path, 'reason': 'file not found', 'tier': None})
            continue
        r = _find_exact(content, search)
        if r == 'ambiguous':
            failed.append({'path': path, 'reason': 'ambiguous (exact >1 match)', 'tier': 'exact'})
            continue
        if r is not None:
            (a, b) = r
            sandbox.write_file(path, content[:a] + replace + content[b:])
            applied.append({'path': path, 'tier': 'exact'})
            tiers['exact'] += 1
            continue
        matched = None
        used_tier = None
        for (tier, fn) in [('ws_normalized', _find_ws), ('strip_lines', _find_strip), ('anchor', _find_anchor)]:
            rr = fn(content, search)
            if rr == 'ambiguous':
                matched = 'ambiguous'
                used_tier = tier
                break
            if rr is not None and rr[0] == 'lines':
                matched = rr[1]
                used_tier = tier
                break
        if matched == 'ambiguous':
            failed.append({'path': path, 'reason': f'ambiguous ({used_tier})', 'tier': used_tier})
            continue
        if matched is None:
            failed.append({'path': path, 'reason': 'not located by any tier (possible hallucinated base content)', 'tier': None})
            continue
        (i, j) = matched
        c_lines = content.split('\n')
        new_content = '\n'.join(c_lines[:i] + [replace.rstrip('\n')] + c_lines[j:])
        sandbox.write_file(path, new_content)
        applied.append({'path': path, 'tier': used_tier})
        tiers[used_tier] += 1
    for (path, content) in new_files.items():
        sandbox.write_file(path, content)
        applied.append({'path': path, 'tier': 'new_file'})
    return {'applied': applied, 'failed': failed, 'tiers': tiers, 'clean': bool(applied) and (not failed)}
