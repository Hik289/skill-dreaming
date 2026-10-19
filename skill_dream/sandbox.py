from __future__ import annotations
import subprocess, os, tempfile, shutil, re
from dataclasses import dataclass
from typing import Optional

def _run(cmd, cwd=None, timeout=600, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)

@dataclass
class TestResult:
    passed: int
    failed: int
    errors: int
    collected: int
    ok: bool
    raw_tail: str

class Sandbox:

    def __init__(self, repo: str, ref: str, root: str, name: str):
        self.repo = repo
        self.ref = ref
        self.root = root
        self.path = os.path.join(root, name)

    def create(self):
        os.makedirs(self.root, exist_ok=True)
        if os.path.exists(self.path):
            self.destroy()
        r = _run(['git', '-C', self.repo, 'worktree', 'add', '--detach', self.path, self.ref])
        if r.returncode != 0:
            raise RuntimeError(f'worktree add failed: {r.stderr}')
        return self

    def destroy(self):
        _run(['git', '-C', self.repo, 'worktree', 'remove', '--force', self.path])
        if os.path.exists(self.path):
            shutil.rmtree(self.path, ignore_errors=True)

    def write_file(self, relpath: str, content: str):
        full = os.path.join(self.path, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(content)

    def read_file(self, relpath: str) -> Optional[str]:
        full = os.path.join(self.path, relpath)
        if not os.path.exists(full):
            return None
        with open(full) as f:
            return f.read()

    def apply_patch(self, diff_text: str) -> tuple[bool, str]:
        if not diff_text.strip():
            return (False, 'empty patch')
        pf = os.path.join(self.path, '.sd_patch.diff')
        with open(pf, 'w') as f:
            f.write(diff_text if diff_text.endswith('\n') else diff_text + '\n')
        chk = _run(['git', 'apply', '--check', '--whitespace=nowarn', pf], cwd=self.path)
        if chk.returncode != 0:
            chk3 = _run(['git', 'apply', '--3way', '--check', pf], cwd=self.path)
            if chk3.returncode != 0:
                os.remove(pf)
                return (False, f'apply --check failed: {chk.stderr.strip()[:400]}')
        ap = _run(['git', 'apply', '--whitespace=nowarn', pf], cwd=self.path)
        os.remove(pf)
        if ap.returncode != 0:
            ap = _run(['git', 'apply', '--3way', pf], cwd=self.path)
            if ap.returncode != 0:
                return (False, f'apply failed: {ap.stderr.strip()[:400]}')
        return (True, 'applied cleanly')

    def pip_install_e(self, python: str, timeout=900) -> tuple[bool, str]:
        r = _run([python, '-m', 'pip', 'install', '-e', '.', '--no-deps', '-q'], cwd=self.path, timeout=timeout)
        return (r.returncode == 0, (r.stderr or r.stdout)[-800:])

    def run_pytest(self, python: str, targets: Optional[list]=None, ignore: Optional[list]=None, timeout=900, pythonpath: Optional[str]=None, extra_args: Optional[list]=None) -> TestResult:
        cmd = [python, '-m', 'pytest', '-q', '--no-header', '-p', 'no:cacheprovider']
        if extra_args:
            cmd += extra_args
        if ignore:
            for ig in ignore:
                cmd += ['--ignore', ig]
        if targets:
            cmd += targets
        env = None
        if pythonpath:
            env = dict(os.environ)
            env['PYTHONPATH'] = pythonpath + os.pathsep + env.get('PYTHONPATH', '')
        r = _run(cmd, cwd=self.path, timeout=timeout, env=env)
        return _parse_pytest(r.stdout + '\n' + r.stderr, r.returncode)

def _parse_pytest(out: str, returncode: int) -> TestResult:
    passed = failed = errors = collected = 0
    m = re.search('collected (\\d+) item', out)
    if m:
        collected = int(m.group(1))
    for m in re.finditer('(\\d+) passed', out):
        passed = int(m.group(1))
    for m in re.finditer('(\\d+) failed', out):
        failed = int(m.group(1))
    for m in re.finditer('(\\d+) error', out):
        errors = int(m.group(1))
    ok = returncode == 0 and failed == 0 and (errors == 0)
    tr = TestResult(passed=passed, failed=failed, errors=errors, collected=collected, ok=ok, raw_tail=out[-1500:])
    fails = set()
    for m in re.finditer('^(?:FAILED|ERROR)\\s+(\\S+)', out, re.M):
        fails.add(m.group(1).split('::')[0] + '::' + (m.group(1).split('::', 1)[1] if '::' in m.group(1) else ''))
    tr.failed_ids = fails
    return tr
