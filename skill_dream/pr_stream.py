from __future__ import annotations

import hashlib
import math
import re
import subprocess
from collections import Counter
from pathlib import PurePosixPath


SUFFIXES = ('.py', '.rst', '.md', '.yml', '.yaml', '.toml', '.json', '.ini', '.cfg')
COMMON = frozenset('test tests unit integration src lib ansible openlibrary qutebrowser '
                   'python file files code module modules plugin plugins app web'.split())
STOP = frozenset('the a an and or to for from with in on by of is are it this that '
                 'add fix update change support handle use using after before code file files '
                 'error errors test tests new issue feature behavior ansible openlibrary '
                 'qutebrowser python'.split())


def _git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                          text=True, errors='replace', check=True, timeout=360).stdout


def _words(value):
    value = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', str(value))
    raw = re.findall(r'[A-Za-z][A-Za-z0-9]*', value.lower())
    result = set(raw)
    if 'utility' in result or 'utilities' in result:
        result.add('utils')
    for word in raw:
        if word.endswith('utils') and len(word) > 5:
            result.update((word[:-5], 'utils'))
        if word.endswith('parser') and len(word) > 6:
            result.update((word[:-6], 'parser'))
        if word.endswith('iterator') and len(word) > 8:
            result.update((word[:-8], 'iterator'))
        if word.endswith('s') and len(word) > 5:
            result.add(word[:-1])
    return result


def _title(statement):
    lines = [line.strip(' #*" ') for line in statement.replace('\\n', '\n').splitlines()]
    lines = [line for line in lines if line]
    if lines and lines[0].lower().rstrip(':') == 'title':
        return lines[1] if len(lines) > 1 else ''
    if lines and lines[0].lower().startswith('title:'):
        return lines[0].split(':', 1)[1].strip() or (lines[1] if len(lines) > 1 else '')
    return lines[0] if lines else ''


def _pr_number(subject):
    match = re.match(r'^Merge pull request #(\d+)\b', subject)
    if not match:
        match = re.search(r'\(#(\d+)\)\s*$', subject)
    return int(match.group(1)) if match else None


def _task_file_candidates(statement, repository_files, limit=8):
    title = statement.replace('\\n', '\n')[:500].lower()
    documentation_task = any(term in title for term in
                             ('documentation', 'readme', 'changelog', 'docs'))
    test_task = 'test' in title and not any(term in title for term in
                                            ('feature', 'behavior', 'bug', 'fix'))
    files = [path for path in repository_files if path.endswith(SUFFIXES)
             and (test_task or not path.startswith(('test/', 'tests/')))
             and (documentation_task or not path.startswith((
                 'docs/', '.github/', 'hacking/', 'changelogs/', 'misc/requirements/')))
             and (test_task or '/tests/' not in path and '/test_data/' not in path)]
    if not files:
        return []
    statement = statement.replace('\\n', '\n')
    issue_terms = _words(statement[:2500])
    title_terms = _words(statement[:500])
    document_terms = {path: _words(path) - COMMON for path in files}
    frequency = Counter(term for terms in document_terms.values() for term in terms)
    explicit = {part.strip('`.,:;()[]') for part in
                re.findall(r'[A-Za-z0-9_./-]+\.(?:py|rst|md|yml|yaml|toml|json)', statement)}
    ranks = []
    for path in files:
        stem = PurePosixPath(path).stem
        terms = document_terms[path]
        overlap = terms & issue_terms
        score = sum(math.log(1 + len(files) / (1 + frequency[term])) for term in overlap)
        score += sum(2 * math.log(1 + len(files) / (1 + frequency[term]))
                     for term in terms & title_terms)
        if path in explicit:
            score += 100
        elif PurePosixPath(path).name in explicit or ('`' + stem.lower() + '`') in statement.lower():
            score += 25
        if score > 0:
            ranks.append((score, path))
    ranks.sort(key=lambda item: (-item[0], item[1]))
    return [{'path': path, 'score': round(score, 3)} for score, path in ranks[:limit]]


def select_prebase_pr_sources(repo, base_commit, statement, max_candidates=6):
    if max_candidates < 0:
        raise ValueError('max_candidates must be nonnegative')
    history = []
    for line in _git(repo, 'log', '--first-parent', '--format=%H%x1f%ct%x1f%s',
                     base_commit).splitlines():
        parts = line.split('\x1f', 2)
        if len(parts) != 3:
            continue
        number = _pr_number(parts[2])
        if number is not None:
            history.append({'sha': parts[0], 'committer_unix': int(parts[1]),
                            'subject': parts[2], 'pr_number': number})
    tree = _git(repo, 'ls-tree', '-r', '--name-only', base_commit).splitlines()
    target_paths = _task_file_candidates(statement, tree)
    paths = {item['path'] for item in target_paths}
    target_dirs = {str(PurePosixPath(path).parent) for path in paths}
    title_terms = _words(_title(statement)) - STOP
    body_terms = _words(statement[:2600]) - STOP
    frequency = Counter(term for row in history for term in _words(row['subject']) - STOP)
    ranked = []
    for row in history:
        words = _words(row['subject']) - STOP
        title_hits = words & title_terms
        body_hits = words & body_terms
        if not title_hits and len(body_hits) < 2:
            continue
        lexical = sum(3 * math.log(1 + len(history) / (1 + frequency[word]))
                      for word in title_hits)
        lexical += sum(math.log(1 + len(history) / (1 + frequency[word]))
                       for word in body_hits)
        ranked.append((lexical, len(title_hits), row))
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2]['committer_unix'],
                                  item[2]['sha']))
    candidates = []
    for lexical, title_hits, row in ranked[:60]:
        changed = _git(repo, 'diff', '--name-only', row['sha'] + '^1', row['sha']).splitlines()
        if not changed or len(changed) > 45:
            continue
        exact = sorted(paths & set(changed))
        same_dir = sorted(path for path in changed
                          if str(PurePosixPath(path).parent) in target_dirs and path not in paths)
        if not exact and not same_dir and title_hits < 2:
            continue
        score = lexical + 24 * len(exact) + 4 * min(len(same_dir), 3)
        candidates.append({**row, 'changed_files': changed,
                           'score': round(score, 3), 'exact_target_files': exact,
                           'same_directory_files': same_dir[:6],
                           'distinctive_title_hits': title_hits})
    candidates.sort(key=lambda item: (-item['score'], -item['committer_unix'], item['sha']))
    return {'target_paths': target_paths, 'selected': candidates[:max_candidates],
            'eligible_historical_prs': len(history), 'lexical_candidates': len(ranked)}


def align_approved_skills(instance_id, repo, active_ids, catalog, generated,
                          approvals, capacity=200):
    if len(active_ids) != capacity or len(set(active_ids)) != capacity:
        raise ValueError('input snapshot must have exactly capacity distinct skills')
    chosen = list(active_ids)
    updated_catalog = dict(catalog)
    operations = []
    approved = []
    for skill in generated:
        source = skill['version_scope']['source_id']
        if skill['version_scope']['repo'] != repo:
            raise ValueError('cross-repository skill')
        sid = hashlib.sha256((instance_id + '\0' + source + '\0' + skill['name']).encode()).hexdigest()
        decision = approvals.get(sid)
        if decision is None or decision.get('applicable') is None or decision.get('grounded') is None:
            raise ValueError('every generated skill needs a completed assessment')
        if not (decision['applicable'] and decision['grounded']):
            continue
        if sid in updated_catalog:
            raise ValueError('duplicate generated skill identity')
        approved.append((sid, skill))
    approved_ids = {sid for sid, _ in approved}
    for sid, skill in approved:
        same_name = [old for old in chosen if updated_catalog[old]['name'] == skill['name']]
        if same_name:
            chosen.remove(same_name[0])
            operation = 'UPDATE'
        else:
            operation = 'ADD'
        updated_catalog[sid] = skill
        chosen.append(sid)
        if len(chosen) > capacity:
            prior = [candidate for candidate in chosen if candidate not in approved_ids]
            prior.sort(key=lambda candidate: (
                updated_catalog[candidate]['version_scope'].get('committer_unix', 0),
                float(updated_catalog[candidate].get('confidence') or 0),
                updated_catalog[candidate]['name']))
            chosen.remove(prior[0])
        operations.append({'operation': operation, 'skill_id': sid, 'source_commit':
                           skill['version_scope']['source_id']})
    if len(chosen) != capacity or len({updated_catalog[sid]['name'] for sid in chosen}) != capacity:
        raise ValueError('aligned snapshot violates capacity or name uniqueness')
    return sorted(chosen), updated_catalog, operations


def selected_validation_steps(skills):
    return '\n'.join('- ' + step for skill in skills for step in skill.get('validation', [])
                     if isinstance(step, str))[:800]
