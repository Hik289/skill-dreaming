def ensure_named_test_reporting(spec, repo):
    if repo != 'sphinx-doc/sphinx':
        return
    prefix = 'tox --current-env -epy39 -v -- '
    spec.eval_script_list = [
        command.replace(prefix, prefix + '-rA ', 1)
        if command.startswith(prefix) and '-rA' not in command.split() else command
        for command in spec.eval_script_list
    ]
