import argparse
import ast
import io
import json
import re
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'workspace', 'build', 'dist'}
PUBLICATION_DIRECTORIES = {'paper', 'papers', 'manuscript', 'arxiv', 'overleaf', 'assets'}
PUBLICATION_SUFFIXES = {'.pdf', '.tex', '.bib', '.cls', '.bst', '.sty'}
PUBLICATION_DOCUMENTS = {'docs/method.md', 'docs/results.md'}
PATTERNS = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'provider_token': re.compile(r'\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b'),
    'personal_path': re.compile(r'/(?:Users|home)/[^\s/\x22\x27]+|[A-Z]:\\Users\\[^\\\s]+'),
    'private_endpoint': re.compile(r'https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|[^/\s]+\.services\.ai\.azure\.com)(?::\d+)?'),
    'url_credentials': re.compile(r'https?://[^/@\s]+:[^/@\s]+@'),
}


def public_files(staged=False):
    if staged:
        result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True)
        return [ROOT / name.decode() for name in result.stdout.split(b'\0') if name]
    return [p for p in ROOT.rglob('*') if p.is_file() and not IGNORED.intersection(p.relative_to(ROOT).parts)
            and not any(part.endswith('.egg-info') for part in p.parts)]


def check(paths, forbidden=(), code_only=False):
    issues = []
    count = 0
    for path in sorted(paths):
        relative_path = path.relative_to(ROOT)
        relative = str(relative_path)
        if code_only and (PUBLICATION_DIRECTORIES.intersection(part.casefold() for part in relative_path.parts)
                          or path.suffix.casefold() in PUBLICATION_SUFFIXES
                          or relative_path.as_posix().casefold() in PUBLICATION_DOCUMENTS
                          or relative.casefold().endswith(('.zip', '.tar.gz'))):
            issues.append({'file': relative, 'line': 0, 'kind': 'non_code_publication_artifact'})
        for word in forbidden:
            if word.casefold() in relative.casefold():
                issues.append({'file': relative, 'line': 0, 'kind': 'forbidden_filename'})
        if path.is_symlink():
            issues.append({'file': relative, 'line': 0, 'kind': 'symlink'})
            continue
        raw = path.read_bytes()
        if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.ico'}:
            continue
        try:
            source = raw.decode('utf-8')
        except UnicodeDecodeError:
            issues.append({'file': relative, 'line': 0, 'kind': 'unexpected_binary'})
            continue
        count += 1
        for number, line in enumerate(source.splitlines(), 1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    issues.append({'file': relative, 'line': number, 'kind': name})
            for word in forbidden:
                if word.casefold() in line.casefold():
                    issues.append({'file': relative, 'line': number, 'kind': 'forbidden_text'})
        if path.suffix.lower() in {'.md', '.html'} and '<!--' in source:
            issues.append({'file': relative, 'line': 0, 'kind': 'html_comment'})
        if path.suffix != '.py':
            continue
        try:
            tree = ast.parse(source, filename=relative)
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == tokenize.COMMENT:
                    issues.append({'file': relative, 'line': token.start[0], 'kind': 'python_comment'})
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node):
                    issues.append({'file': relative, 'line': getattr(node, 'lineno', 1), 'kind': 'docstring'})
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value
                    names = [n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)]
                    sensitive = any(re.search(r'(?:^|_)(?:key|secret|password|api_key|access_token)$', name, re.I) for name in names)
                    if sensitive and isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) >= 20:
                        issues.append({'file': relative, 'line': node.lineno, 'kind': 'hardcoded_credential'})
        except (SyntaxError, tokenize.TokenError) as exc:
            issues.append({'file': relative, 'line': getattr(exc, 'lineno', 0), 'kind': 'python_syntax'})
    return {'text_files_checked': count, 'issues': issues, 'passed': not issues}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--forbid', action='append', default=[])
    args = parser.parse_args()
    result = check(public_files(args.staged), args.forbid, code_only=args.staged)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
