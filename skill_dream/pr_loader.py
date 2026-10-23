from __future__ import annotations
import subprocess, re, os, json
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

def _git(repo: str, *args) -> str:
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True).stdout

def classify_surface(path: str) -> str:
    p = path.lower()
    base = os.path.basename(p)
    if re.search('(^|/)tests?/', p) or re.search('(^|/)test_|_test\\.py$|conftest\\.py$', p):
        return 'tests'
    if re.search('(^|/)docs?/', p) or base in ('readme.md', 'readme.rst', 'readme.txt') or (p.endswith(('.rst', '.md')) and 'doc' in p):
        return 'docs'
    if base.startswith('readme'):
        return 'docs'
    if re.search('change(s|log)|release|news|history', base):
        return 'changelog'
    if base in ('pyproject.toml', 'setup.py', 'setup.cfg', 'tox.ini', 'pytest.ini', 'requirements.txt', 'makefile', '.pre-commit-config.yaml') or p.endswith(('.cfg', '.ini', '.toml')) or re.search('(^|/)\\.github/', p):
        return 'config'
    if re.search('(^|/)\\.github/workflows/', p):
        return 'ci'
    if re.search('migrat', p):
        return 'migration'
    if re.search('(^|/)examples?/', p):
        return 'examples'
    if p.endswith('.pyi') or 'generated' in p:
        return 'generated'
    if p.endswith('.py'):
        return 'code'
    return 'other'
_SYM = re.compile('^[+-]\\s*(async\\s+def|def|class)\\s+([A-Za-z_][A-Za-z0-9_]*)')

@dataclass
class PRRecord:
    pr: int
    sha: str
    base: str
    date: str
    author: str
    subject: str
    kind: str
    n_files: int
    added: int
    deleted: int
    surfaces: dict
    n_symbols: int
    intent: str
    files: list
    symbols: list = field(default_factory=list)

    def gold_surfaces(self) -> set:
        return set(self.surfaces.keys())

    def task_description(self) -> str:
        return self.subject

def parse_pr_from_repo(repo: str, sha: str, base: Optional[str]=None, kind: str='squash') -> PRRecord:
    if base is None:
        base = _git(repo, 'rev-parse', f'{sha}^').strip()
    if kind == 'squash':
        files_out = _git(repo, 'show', '--name-only', '--format=', '-M', sha)
        num_out = _git(repo, 'show', '--numstat', '--format=', '-M', sha)
        sym_out = _git(repo, 'show', '--format=', '-U0', sha)
        subj = _git(repo, 'log', '-1', '--format=%s', sha).strip()
        date = _git(repo, 'log', '-1', '--format=%ci', sha).strip()
        author = _git(repo, 'log', '-1', '--format=%an', sha).strip()
    else:
        files_out = _git(repo, 'diff', '--name-only', '-M', f'{base}..{sha}')
        num_out = _git(repo, 'diff', '--numstat', '-M', f'{base}..{sha}')
        sym_out = _git(repo, 'diff', '-U0', f'{base}..{sha}')
        subj = _git(repo, 'log', '-1', '--format=%s', sha).strip()
        date = _git(repo, 'log', '-1', '--format=%ci', sha).strip()
        author = _git(repo, 'log', '-1', '--format=%an', sha).strip()
    files = [f for f in files_out.splitlines() if f.strip()]
    add = dele = 0
    for l in num_out.splitlines():
        p = l.split('\t')
        if len(p) == 3 and p[0].isdigit() and p[1].isdigit():
            add += int(p[0])
            dele += int(p[1])
    syms = set()
    for l in sym_out.splitlines():
        m = _SYM.match(l)
        if m:
            syms.add(m.group(2))
    surf = Counter((classify_surface(f) for f in files))
    prnum_m = re.search('\\(#(\\d+)\\)\\s*$', subj)
    prnum = int(prnum_m.group(1)) if prnum_m else -1
    return PRRecord(pr=prnum, sha=sha, base=base, date=date, author=author, subject=subj, kind=kind, n_files=len(files), added=add, deleted=dele, surfaces=dict(surf), n_symbols=len(syms), intent=_classify_intent(subj), files=files, symbols=sorted(syms))
_FEATURE = re.compile('\\b(add|support|implement|introduc|new|feature|allow|enable)\\b', re.I)
_FIX = re.compile('\\b(fix|bug|correct|resolve|patch|repair)\\b', re.I)
_REFACTOR = re.compile('\\b(refactor|cleanup|clean up|rename|reorganiz|simplif|deprecat|remove|drop)\\b', re.I)
_DOC = re.compile('\\b(doc|docs|documentation|typo|changelog|readme|comment)\\b', re.I)
_TEST = re.compile('\\b(test|tests|coverage|ci)\\b', re.I)

def _classify_intent(subject: str) -> str:
    if _FEATURE.search(subject):
        return 'feature'
    if _FIX.search(subject):
        return 'fix'
    if _REFACTOR.search(subject):
        return 'refactor'
    if _DOC.search(subject):
        return 'docs'
    if _TEST.search(subject):
        return 'test'
    return 'other'

def load_manifest(path: str) -> list:
    recs = []
    with open(path) as f:
        content = f.read().strip()
    if content.startswith('['):
        data = json.loads(content)
        for d in data:
            recs.append(d)
    else:
        for line in content.splitlines():
            if line.strip():
                recs.append(json.loads(line))
    return recs

def get_diff(repo: str, base: str, sha: str) -> str:
    return _git(repo, 'diff', f'{base}..{sha}')

def get_file_at(repo: str, ref: str, path: str) -> Optional[str]:
    out = subprocess.run(['git', '-C', repo, 'show', f'{ref}:{path}'], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None

def localize_base_files(repo: str, base: str, task: str, max_files: int=6) -> list:
    files = _git(repo, 'ls-tree', '-r', '--name-only', base).splitlines()
    keywords = set(re.findall(r'[a-z][a-z0-9_]{2,}', task.lower()))
    def score(path):
        terms = set(re.findall(r'[a-z][a-z0-9_]{2,}', path.lower()))
        return (-len(keywords & terms), path.startswith(('tests/', 'docs/')), path)
    return sorted(files, key=score)[:max_files]

def index_history(repo: str, ref='HEAD', before_date=None, limit=200):
    from .skill_store import _timestamp
    if limit < 1:
        raise ValueError('history limit must be positive')
    cutoff = _timestamp(before_date) if before_date else None
    if before_date and cutoff is None:
        raise ValueError('before_date must be an ISO date or timestamp')
    command = ['git', '-C', repo, 'log', '--first-parent', '-z', '--format=%H%x00%P%x00%cI%x00%s', ref, '--']
    raw = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    parts = raw.strip('\x00').split('\x00') if raw else []
    rows = []
    for i in range(0, len(parts), 4):
        sha, parents, date, subject = parts[i:i + 4]
        if not parents or (cutoff and _timestamp(date) >= cutoff):
            continue
        number = re.search(r'\(#(\d+)\)\s*$', subject)
        changed = _git(repo, 'diff', '--name-only', parents.split()[0], sha, '--').splitlines()
        rows.append({'pr': int(number.group(1)) if number else 'commit:' + sha[:12],
                     'sha': sha, 'base': parents.split()[0], 'date': date, 'available_at': date,
                     'subject': subject, 'kind': 'segment', 'source': 'first_parent_commit',
                     'status': 'accepted', 'files': changed})
        if len(rows) == limit:
            break
    return sorted(rows, key=lambda row: _timestamp(row['date']))
