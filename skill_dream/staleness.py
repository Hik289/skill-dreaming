from __future__ import annotations
import subprocess, re, os
from typing import Optional

def _path_exists_at(repo: str, ref: str, path: str) -> bool:
    r = subprocess.run(['git', '-C', repo, 'cat-file', '-e', f'{ref}:{path}'], capture_output=True)
    return r.returncode == 0

def _symbol_exists_at(repo: str, ref: str, symbol: str, hint_paths: list) -> bool:
    pat = re.compile(rf'\b{re.escape(symbol)}\b')
    for p in hint_paths:
        out = subprocess.run(['git', '-C', repo, 'show', f'{ref}:{p}'], capture_output=True, text=True)
        if out.returncode == 0 and pat.search(out.stdout):
            return True
    return False

def extract_skill_refs(skill) -> dict:
    vs = skill.version_scope or {}
    paths = list(vs.get('referenced_paths', []))
    symbols = list(vs.get('referenced_symbols', []))
    if not paths:
        for s in skill.trigger.get('repository_surfaces', []):
            if isinstance(s, str) and ('/' in s and s.endswith(('.py', '.rst', '.toml', '.cfg'))):
                paths.append(s)
    return {'paths': paths, 'symbols': symbols}

def assess_staleness(repo: str, base_ref: str, skill) -> dict:
    refs = extract_skill_refs(skill)
    paths = refs['paths']
    symbols = refs['symbols']
    path_hit = sum((1 for p in paths if _path_exists_at(repo, base_ref, p)))
    path_total = len(paths)
    sym_hit = sum((1 for s in symbols if _symbol_exists_at(repo, base_ref, s, paths)))
    sym_total = len(symbols)
    stale = False
    reason = 'fresh'
    if path_total > 0 and path_hit == 0:
        stale = True
        reason = 'all referenced paths absent at base (files renamed/removed)'
    elif path_total >= 2 and path_hit / path_total < 0.5:
        stale = True
        reason = f'majority referenced paths absent ({path_hit}/{path_total})'
    elif sym_total > 0 and sym_hit == 0 and path_hit > 0:
        stale = True
        reason = 'all referenced symbols absent (API renamed)'
    return {'stale': stale, 'path_hit': path_hit, 'path_total': path_total, 'symbol_hit': sym_hit, 'symbol_total': sym_total, 'reason': reason}

def record_version_scope(skill, evidence_pr: dict, referenced_paths: list, referenced_symbols: list):
    skill.version_scope.update({'valid_from_sha': evidence_pr.get('sha', ''), 'date': evidence_pr.get('date', ''), 'valid_from_date': evidence_pr.get('date', ''), 'referenced_paths': referenced_paths[:12], 'referenced_symbols': referenced_symbols[:12], 'last_validated': evidence_pr.get('date', '')})
    return skill

def detect_supersede(skills: list) -> list:
    pairs = []
    by_tt = {}
    for sk in skills:
        tt = sk.trigger.get('task_type', '?')
        by_tt.setdefault(tt, []).append(sk)
    for (tt, group) in by_tt.items():
        for i in range(len(group)):
            for j in range(len(group)):
                if i == j:
                    continue
                (a, b) = (group[i], group[j])
                ka = set(a.trigger.get('keywords', []))
                kb = set(b.trigger.get('keywords', []))
                if not ka or not kb:
                    continue
                overlap = len(ka & kb) / min(len(ka), len(kb))
                da = (a.version_scope or {}).get('valid_from_date', '')
                db = (b.version_scope or {}).get('valid_from_date', '')
                if overlap >= 0.6 and db and da and (db > da):
                    pairs.append((a.name, b.name))
    seen = set()
    out = []
    for p in pairs:
        if p[0] not in seen:
            out.append(p)
            seen.add(p[0])
    return out
