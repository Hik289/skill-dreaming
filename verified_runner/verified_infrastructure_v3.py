import shlex
import verified_infrastructure_v2 as previous

def normalize_checkout(execute, base, dataset, record, repo=None):
    observed = {}

    def capture(data):
        observed.clear()
        observed.update(data)
        record(observed)
    try:
        return previous.normalize_checkout(execute, base, dataset, capture, repo=repo)
    except RuntimeError as exc:
        if dataset != 'verified' or repo not in {'sympy/sympy', 'django/django'} or str(exc) != 'Official setup includes unrecognized tracked changes':
            raise

    def check(name, command):
        result = execute({'command': command})
        observed[name] = result
        record(observed)
        if result['returncode']:
            raise RuntimeError('Mode-only setup validation failed: ' + name)
        return result['output']
    quoted = shlex.quote(base)
    rows = previous.parse_raw_changes(check('setup_raw_changes', 'git diff --raw --abbrev=40 --no-renames -z ' + quoted + ' HEAD --'))
    if not rows or any((row['old_blob'] != row['new_blob'] for row in rows)):
        raise RuntimeError('Mode-only recovery refuses any content change')
    observed['verified_mode_only_recovery'] = {'files': len(rows), 'all_full_blob_ids_identical': True, 'scope': 'Clean official setup commit; regular-file permission changes only; no added/deleted files.'}
    record(observed)
    check('detach_base', 'git checkout --detach ' + quoted)
    if check('head_after', 'git rev-parse HEAD').strip() != base:
        raise RuntimeError('Base mismatch after mode-only normalization')
    check('exact_worktree_after', 'git diff --exit-code ' + quoted + ' --')
    observed['normalized_official_setup_commit'] = True
    record(observed)
    return observed
