import shlex
import verified_infrastructure as previous

def parse_raw_changes(text):
    fields = text.split('\x00')
    if fields[-1] == '':
        fields.pop()
    if len(fields) % 2:
        raise RuntimeError('Malformed raw Git diff')
    rows = []
    for i in range(0, len(fields), 2):
        (header, path) = (fields[i], fields[i + 1])
        if not header.startswith(':'):
            raise RuntimeError('Malformed raw Git diff header')
        values = header[1:].split()
        if len(values) != 5 or values[4] != 'M':
            raise RuntimeError('Unexpected file creation, deletion, or rename')
        (old_mode, new_mode, old_blob, new_blob, _) = values
        if (old_mode, new_mode) not in {('100644', '100755'), ('100644', '100644'), ('100755', '100755')}:
            raise RuntimeError('Unexpected tracked file mode transition')
        if path in {r['path'] for r in rows}:
            raise RuntimeError('Repeated raw Git diff path')
        rows.append({'path': path, 'old_mode': old_mode, 'new_mode': new_mode, 'old_blob': old_blob, 'new_blob': new_blob})
    return rows

def normalize_checkout(execute, base, dataset, record, repo=None):
    observed = {}

    def capture(data):
        observed.clear()
        observed.update(data)
        record(observed)
    try:
        return previous.normalize_checkout(execute, base, dataset, capture, repo=repo)
    except RuntimeError as exc:
        if dataset != 'verified' or repo != 'sphinx-doc/sphinx' or str(exc) not in {'Setup changed files outside the official Sphinx installation policy', 'Official setup has unexpected file mode or file creation changes'}:
            raise

    def check(name, command):
        result = execute({'command': command})
        observed[name] = result
        record(observed)
        if result['returncode']:
            raise RuntimeError('Sphinx mode validation failed: ' + name)
        return result['output']
    quoted = shlex.quote(base)
    rows = parse_raw_changes(check('setup_raw_changes', 'git diff --raw --abbrev=40 --no-renames -z ' + quoted + ' HEAD --'))
    (policy, digest) = previous.setup_policy(base)
    commands = previous.validated_commands(policy['pre_install'])
    required = {shlex.split(command)[-1] for command in commands}
    content_changed = {r['path'] for r in rows if r['old_blob'] != r['new_blob']}
    if not content_changed <= required:
        raise RuntimeError('Sphinx setup contains non-installation content changes')
    (original, installed) = ({}, {})
    for name in sorted(required):
        original[name] = check('base_' + name, 'git show ' + quoted + ':' + shlex.quote(name))
        installed[name] = check('setup_' + name, 'git show HEAD:' + shlex.quote(name))
    expected = previous.expected_files({name: original.get(name, '') for name in previous.FILES}, commands)
    if any((installed[name] != expected[name] for name in required)):
        raise RuntimeError('Sphinx content does not exactly match official installation commands')
    observed['verified_mode_recovery'] = {'policy_sha256': digest, 'version': policy['version'], 'mode_changes': sum((r['old_mode'] != r['new_mode'] for r in rows)), 'content_changed_files': sorted(content_changed), 'other_file_blobs_identical': True, 'scope': 'Sphinx-only; clean official setup commit; exact installation contents; no added/deleted files.'}
    record(observed)
    check('detach_base', 'git checkout --detach ' + quoted)
    if check('head_after', 'git rev-parse HEAD').strip() != base:
        raise RuntimeError('Base mismatch after checked Sphinx normalization')
    observed['normalized_official_setup_commit'] = True
    record(observed)
    return observed
