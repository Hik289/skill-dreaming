from contextlib import contextmanager
import json
import shlex
import subprocess
import time
import uuid

def normalize_checkout(execute, base, dataset, record, repo=None):
    observations = {}

    def check(name, text, allowed=(0,)):
        outcome = execute({'command': text})
        observations[name] = outcome
        record(observations)
        if outcome['returncode'] not in allowed:
            raise RuntimeError('Initial checkout validation failed: ' + name)
        return outcome.get('output', '').strip()
    head = check('head_before', 'git rev-parse HEAD')
    if head == base:
        observations['normalized_official_setup_commit'] = False
        record(observations)
        return observations
    if dataset != 'verified':
        raise RuntimeError('Frozen base commit mismatch')
    quoted = shlex.quote(base)
    if check('tracked_status', 'git status --porcelain --untracked-files=no'):
        raise RuntimeError('Official image has modified tracked files')
    check('base_is_ancestor', 'git merge-base --is-ancestor ' + quoted + ' HEAD')
    subjects = check('setup_commits', 'git log --format=%s ' + quoted + '..HEAD')
    if not subjects or any((s != 'SWE-bench' for s in subjects.splitlines())):
        raise RuntimeError('Unexpected commits after frozen Verified base')
    check('same_tree', 'git diff --exit-code ' + quoted + ' HEAD --', allowed=(0, 1))
    if observations['same_tree']['returncode']:
        files = check('setup_changed_files', 'git diff --name-only ' + quoted + ' HEAD --')
        if repo != 'sphinx-doc/sphinx' or files != 'tox.ini':
            raise RuntimeError('Official setup includes unrecognized tracked changes')
        check('base_tox', 'git show ' + quoted + ':tox.ini')
        check('setup_tox', 'git show HEAD:tox.ini')
        original = observations['base_tox']['output']
        installed = observations['setup_tox']['output']
        expected = ''.join((line.replace('pytest', 'pytest -rA', 1) for line in original.splitlines(keepends=True)))
        if original == installed or installed != expected:
            raise RuntimeError('Sphinx setup differs from the official test-reporting-only change')
        observations['official_setup_change'] = 'Sphinx tox.ini pytest -rA reporting flag only'
        record(observations)
    check('detach_base', 'git checkout --detach ' + quoted)
    if check('head_after', 'git rev-parse HEAD') != base:
        raise RuntimeError('Frozen base still mismatches after setup normalization')
    observations['normalized_official_setup_commit'] = True
    record(observations)
    return observations

def image_record(result):
    if result.returncode:
        raise RuntimeError('Docker image inspection failed: ' + result.stderr[-1000:])
    try:
        records = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError('Docker image inspection did not return JSON') from exc
    if not isinstance(records, list) or not records or (not isinstance(records[0], dict)) or (not records[0].get('Id')):
        raise RuntimeError('Docker image inspection returned no image')
    return records[0]

@contextmanager
def pinned_image(image, target, tag, task, command, save, attempts=3):
    target.mkdir(parents=True, exist_ok=True)
    existed = command(['docker', 'image', 'inspect', image]).returncode == 0
    holder = None
    info = None
    failures = []
    for attempt in range(1, attempts + 1):
        name = tag + '-pin-' + uuid.uuid4().hex[:12]
        try:
            pull = command(['docker', 'pull', image], 1800)
            (target / f'image_pull_{attempt}.log').write_text(pull.stdout + pull.stderr)
            if pull.returncode:
                raise RuntimeError('Image pull failed')
            start = command(['docker', 'run', '-d', '--pull=never', '--name', name, '--label', 'skilldreaming.run=' + tag, '--label', 'skilldreaming.task=' + task, '--label', 'skilldreaming.role=image-pin', '--entrypoint', '/bin/sh', image, '-c', 'while :; do sleep 3600; done'], 120)
            if start.returncode:
                raise RuntimeError('Image pin failed: ' + start.stderr[-1000:])
            inspection = command(['docker', 'inspect', name])
            if inspection.returncode:
                raise RuntimeError('Image pin inspection failed')
            container = json.loads(inspection.stdout)[0]
            if not container['State']['Running']:
                raise RuntimeError('Image pin is not running')
            info = image_record(command(['docker', 'image', 'inspect', container['Image']]))
            holder = name
            save(target / 'image.json', {k: info.get(k) for k in ['Id', 'RepoDigests', 'Size']})
            save(target / 'image_preparation.json', {'image': image, 'pin': name, 'attempt': attempt, 'previous_failures': failures, 'existed_before': existed})
            break
        except (RuntimeError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as exc:
            failures.append({'attempt': attempt, 'type': type(exc).__name__, 'error': str(exc)})
            save(target / 'image_preparation_failures.json', failures)
            command(['docker', 'rm', '-f', name], 60)
            if attempt == attempts:
                raise RuntimeError('Image preparation failed before model calls') from exc
            time.sleep(attempt)
    succeeded = False
    try:
        yield info
        succeeded = True
    finally:
        try:
            cleanup = command(['docker', 'rm', '-f', holder], 60)
            save(target / 'image_pin_cleanup.json', {'name': holder, 'returncode': cleanup.returncode})
            if succeeded and (not existed):
                deletion = command(['docker', 'image', 'rm', image], 180)
                save(target / 'image_cleanup.json', {'image': image, 'returncode': deletion.returncode})
        except subprocess.TimeoutExpired:
            save(target / 'image_cleanup.json', {'status': 'timeout', 'pin': holder, 'image': image})
