import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from skill_dream.pr_stream import (align_approved_skills, select_prebase_pr_sources,
                                   selected_validation_steps)


class PRStreamTests(unittest.TestCase):
    def test_full_history_selection_stays_before_task_base(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            def git(*args):
                return subprocess.run(['git', '-C', str(repo), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '-q')
            git('config', 'user.name', 'Example')
            git('config', 'user.email', 'example@example.com')
            (repo / 'src').mkdir()
            (repo / 'src/factory.py').write_text('value = 1\n')
            git('add', '.')
            git('commit', '-qm', 'Initial repository')
            (repo / 'src/factory.py').write_text('value = 2\n')
            git('commit', '-qam', 'Factory provider integration (#12)')
            historical = git('rev-parse', 'HEAD')
            (repo / 'src/exporter.py').write_text('value = 3\n')
            git('add', '.')
            git('commit', '-qm', 'Exporter extension (#13)')
            base = git('rev-parse', 'HEAD')
            (repo / 'src/factory.py').write_text('value = 4\n')
            git('commit', '-qam', 'Future provider integration (#14)')
            future = git('rev-parse', 'HEAD')
            found = select_prebase_pr_sources(repo, base,
                'Title: Add provider factory integration\nUpdate `src/factory.py`.')
            shas = [row['sha'] for row in found['selected']]
            self.assertIn(historical, shas)
            self.assertNotIn(future, shas)
            self.assertIn('src/factory.py', found['selected'][0]['exact_target_files'])

    def test_only_approved_skills_enter_bounded_pool(self):
        catalog = {
            'old-a': {'name': 'old-a', 'version_scope': {'repo': 'r', 'committer_unix': 1},
                      'confidence': 0.5},
            'old-b': {'name': 'old-b', 'version_scope': {'repo': 'r', 'committer_unix': 2},
                      'confidence': 0.5}}
        good = {'name': 'new-a', 'version_scope': {'repo': 'r', 'source_id': 'pr-a',
                                                 'committer_unix': 3}, 'confidence': 0.8}
        bad = {'name': 'new-b', 'version_scope': {'repo': 'r', 'source_id': 'pr-b',
                                                'committer_unix': 3}, 'confidence': 0.8}
        good_id = hashlib.sha256(b'task\0pr-a\0new-a').hexdigest()
        bad_id = hashlib.sha256(b'task\0pr-b\0new-b').hexdigest()
        approvals = {good_id: {'applicable': True, 'grounded': True},
                     bad_id: {'applicable': True, 'grounded': False}}
        selected, updated, operations = align_approved_skills(
            'task', 'r', ['old-a', 'old-b'], catalog, [good, bad], approvals, capacity=2)
        self.assertEqual(selected, sorted(['old-b', good_id]))
        self.assertNotIn(bad_id, updated)
        self.assertEqual(operations[0]['operation'], 'ADD')
        with self.assertRaises(ValueError):
            align_approved_skills('task', 'r', ['old-a', 'old-b'], catalog,
                                  [good, bad], {good_id: approvals[good_id]}, capacity=2)

    def test_validation_steps_match_frozen_feedback_budget(self):
        self.assertEqual(selected_validation_steps([{'validation': ['Run related tests']}]),
                         '- Run related tests')
        self.assertEqual(len(selected_validation_steps([{'validation': ['x' * 1000]}])), 800)


if __name__ == '__main__':
    unittest.main()
