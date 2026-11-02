import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'verified_runner'))
import bedrock_runtime
import build_suite
import distillation
import reporting
import retrieval
import shared_settings
from verified_infrastructure import validated_commands
from verified_infrastructure_v2 import parse_raw_changes
from skill_dream.skill_store import Skill
from scripts import release_check


class VerifiedRunnerTests(unittest.TestCase):
    def test_actor_settings_preserve_distinct_workflows_and_equal_budgets(self):
        base = shared_settings.config('verified', 'test-model', 'base')
        ours = shared_settings.config('verified', 'test-model', 'ours')
        self.assertIn('5. Test edge cases', base['agent']['instance_template'])
        self.assertIn('7. Before submitting', ours['agent']['instance_template'])
        for config in (base, ours):
            self.assertEqual(config['agent']['step_limit'], 250)
            self.assertEqual(config['agent']['wall_time_limit_seconds'], 3000)
            self.assertEqual(config['model']['model_kwargs']['max_tokens'], 8192)
            self.assertEqual(config['environment']['cwd'], '/testbed')
        self.assertEqual(base['model'], ours['model'])
        self.assertEqual(base['environment'], ours['environment'])

    def test_changed_settings_are_rejected(self):
        config = shared_settings.config('verified', 'test-model')
        config['agent']['step_limit'] += 1
        with self.assertRaises(RuntimeError):
            shared_settings.check(config, 'verified', 'test-model')

    def test_credentials_are_local_and_not_inserted_in_config(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(RuntimeError):
                bedrock_runtime.credential()
            config = bedrock_runtime.actor_config({'model_kwargs': {'api_key': 'fixture'}}, 'test-model')
            self.assertNotIn('api_key', config['model_kwargs'])

    def test_release_check_rejects_bedrock_tokens_without_echoing_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.txt'
            value = 'ABS' + 'K' + 'A' * 64
            path.write_text(value)
            with patch.object(release_check, 'ROOT', Path(directory)):
                result = release_check.check([path])
            self.assertFalse(result['passed'])
            self.assertEqual(result['issues'][0]['kind'], 'bedrock_token')
            self.assertNotIn(value, str(result))

    def test_report_flag_changes_only_reporting(self):
        command = 'tox --current-env -epy39 -v -- tests/test_extension.py'
        spec = SimpleNamespace(eval_script_list=['git status', command])
        reporting.ensure_named_test_reporting(spec, 'sphinx-doc/sphinx')
        expected = ['git status', command.replace('-- tests/', '-- -rA tests/')]
        self.assertEqual(spec.eval_script_list, expected)
        reporting.ensure_named_test_reporting(spec, 'sphinx-doc/sphinx')
        self.assertEqual(spec.eval_script_list, expected)
        other = SimpleNamespace(eval_script_list=[command])
        reporting.ensure_named_test_reporting(other, 'django/django')
        self.assertEqual(other.eval_script_list, [command])

    def test_setup_policy_rejects_unrelated_commands(self):
        with self.assertRaises(RuntimeError):
            validated_commands(['rm -rf source.py'])
        with self.assertRaises(RuntimeError):
            validated_commands(["sed -i 's/a/b/' tox.ini; echo unexpected"])

    def test_raw_diff_requires_regular_modified_files(self):
        raw = ':100644 100755 ' + 'a' * 40 + ' ' + 'a' * 40 + ' M\0module.py\0'
        rows = parse_raw_changes(raw)
        self.assertEqual(rows[0]['old_blob'], rows[0]['new_blob'])
        with self.assertRaises(RuntimeError):
            parse_raw_changes(raw.replace('100755', '120000'))

    def test_hybrid_threshold_fallback_and_rendering(self):
        skills = [Skill(name='alpha', trigger={'keywords': ['alpha']}, procedure=['inspect alpha'],
                        negative_constraints=['verify the current path']),
                  Skill(name='beta', trigger={'keywords': ['beta']}, procedure=['inspect beta'])]
        with patch.object(retrieval, 'emb_cached', return_value=[1.0, 0.0]):
            selected, meta = retrieval.retrieve('beta', skills, 'a2', 'test-model', tau=2, topk=1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(meta['n_pre'], 2)
        rendered = retrieval.render_skill(skills[0], 1)
        self.assertIn('Pitfall to avoid:', rendered)
        self.assertIn('verify the current path', rendered)

    def test_split_is_fixed_and_does_not_export_target_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = {f'{repo.replace("/", "__")}-{i:03d}': {
                'instance_id': f'{repo.replace("/", "__")}-{i:03d}', 'repo': repo,
                'base_commit': 'base', 'problem_statement': 'task', 'patch': 'hidden'}
                for repo in build_suite.VERIFIED_REPOS for i in range(80)}
            data = root / 'dataset.jsonl'
            data.write_text('\n'.join(json.dumps(row) for row in rows.values()))

            def git(repo, *args):
                if args[0] == 'merge-base':
                    return 'ancestor\n' if '--octopus' in args else ''
                if args[0] == 'rev-list':
                    return '\n'.join(f'1 source{i}' for i in range(600))
                if args[0] == 'log':
                    return '\n'.join(f'source{i}\x012020-01-01\x01fix {i}' for i in range(600))
                if '--format=%ct' in args:
                    return '2\n'
                return '--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-old\n+new\n'

            with patch.object(build_suite, 'OUT', root), patch.object(build_suite, 'load_rows', return_value=(data, rows)), patch.object(build_suite, 'git', side_effect=git):
                build_suite.prepare('verified')
            tasks = build_suite.read(root / 'verified/tasks.json')
            self.assertEqual(len(tasks), 100)
            self.assertEqual([sum(task['repo'] == repo for task in tasks.values()) for repo in build_suite.VERIFIED_REPOS], [34, 33, 33])
            self.assertTrue(all(set(task) == {'instance_id', 'repo', 'base_commit', 'problem_statement'} for task in tasks.values()))

    def test_pool_freezes_at_200_without_cross_repo_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = build_suite.VERIFIED_REPOS[0]
            source = root / 'sources.json'
            build_suite.save(source, [{'sha': f'source{i}', 'repo': repo, 'date': '2020-01-01',
                'committer_unix': 1, 'subject': 'fix', 'body': '', 'diff': '+++ b/module.py'} for i in range(205)])
            manifest = root / 'verified/manifest.json'
            build_suite.save(manifest, {'sources': {repo: {'path': str(source), 'sha256': build_suite.sha(source)}}})
            counter = iter(range(205))

            def generate(*args, **kwargs):
                return [Skill(name=f'skill-{next(counter)}', trigger={}, procedure=['inspect current code'])]

            with patch.object(build_suite, 'OUT', root), patch.object(distillation, 'generate_skills', side_effect=generate):
                build_suite.build('verified', 'test-model', repo)
            folder = root / 'verified/test-model/pools' / repo.replace('/', '__')
            skills = [build_suite.read(path) for path in (folder / 'current').glob('*.json')]
            self.assertEqual(len(skills), 200)
            self.assertTrue(all(skill['version_scope']['repo'] == repo for skill in skills))
            frozen = build_suite.read(folder / 'manifest.json')
            self.assertEqual(len(frozen['skills']), 200)


if __name__ == '__main__':
    unittest.main()
