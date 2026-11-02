import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
from infrastructure import normalize_checkout as original_checkout, pinned_image
FILES = {'setup.py', 'tox.ini'}

def validated_commands(commands):
    for command in commands:
        if any((char in command for char in ('\n', '\r', '`', '$', ';'))):
            raise RuntimeError('Unsupported shell syntax in official setup command')
        words = shlex.split(command)
        (segments, current) = ([], [])
        for word in words:
            if word in ('&&', '||'):
                segments.append(current)
                current = []
            else:
                current.append(word)
        segments.append(current)
        for part in segments:
            if len(part) != 4 or part[3] not in FILES:
                raise RuntimeError('Unsupported official setup command')
            if part[:2] == ['sed', '-i']:
                if not part[2].startswith('s/') or not part[2].endswith(('/', '/g')):
                    raise RuntimeError('Unsupported sed transformation')
            elif part[:2] != ['grep', '-q']:
                raise RuntimeError('Unsupported official setup command')
    return commands

def expected_files(original, commands):
    validated_commands(commands)
    with tempfile.TemporaryDirectory(prefix='sd-verified-setup-') as directory:
        folder = Path(directory)
        for name in FILES:
            (folder / name).write_text(original[name])
        for command in commands:
            subprocess.run(['/bin/bash', '-e', '-c', command], cwd=folder, check=True, capture_output=True, text=True, timeout=20, env={'PATH': '/usr/bin:/bin', 'HOME': directory, 'LC_ALL': 'C'})
        return {name: (folder / name).read_text() for name in FILES}

def setup_policy(base):
    import swebench.harness.constants.python as official
    from build_suite import OUT
    policy_file = OUT / 'verified_setup_policy.json'
    policy = json.loads(policy_file.read_text())
    actual = hashlib.sha256(Path(official.__file__).read_bytes()).hexdigest()
    if actual != policy['official_module_sha256']:
        raise RuntimeError('Official harness source changed after policy freeze')
    row = policy['by_base_commit'][base]
    return (row, hashlib.sha256(policy_file.read_bytes()).hexdigest())

def normalize_checkout(execute, base, dataset, record, repo=None):
    if dataset != 'verified' or repo != 'sphinx-doc/sphinx':
        return original_checkout(execute, base, dataset, record, repo=repo)
    observations = {}

    def capture(data):
        observations.clear()
        observations.update(data)
        record(observations)
    try:
        return original_checkout(execute, base, dataset, capture, repo=repo)
    except RuntimeError as exc:
        if str(exc) != 'Official setup includes unrecognized tracked changes':
            raise
    changed = set(observations['setup_changed_files']['output'].splitlines())
    if not changed <= FILES or 'setup.py' not in changed:
        raise RuntimeError('Setup changed files outside the official Sphinx installation policy')

    def check(name, command):
        value = execute({'command': command})
        observations[name] = value
        record(observations)
        if value['returncode']:
            raise RuntimeError('Official setup validation failed: ' + name)
        return value['output']
    quoted = shlex.quote(base)
    if check('setup_mode_changes', 'git diff --summary ' + quoted + ' HEAD --').strip():
        raise RuntimeError('Official setup has unexpected file mode or file creation changes')
    (original, installed) = ({}, {})
    for name in sorted(FILES):
        original[name] = check('base_' + name, 'git show ' + quoted + ':' + name)
        installed[name] = check('setup_' + name, 'git show HEAD:' + name)
    (policy, digest) = setup_policy(base)
    expected = expected_files(original, policy['pre_install'])
    if installed != expected:
        raise RuntimeError('Sphinx setup does not exactly match official version-specific installation')
    observations['official_setup_policy'] = {'version': policy['version'], 'policy_sha256': digest, 'changed_files': sorted(changed), 'comparison': 'Exact full-file equality after official pre_install'}
    record(observations)
    check('detach_base', 'git checkout --detach ' + quoted)
    if check('head_after', 'git rev-parse HEAD').strip() != base:
        raise RuntimeError('Frozen base still mismatches after official setup normalization')
    observations['normalized_official_setup_commit'] = True
    record(observations)
    return observations
