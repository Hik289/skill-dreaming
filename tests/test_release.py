import tempfile
import unittest
from unittest.mock import patch

from skill_dream.embedding import embed_batch
from skill_dream.evaluator import surface_f1
from skill_dream.leakguard import LeakGuard, LeakViolation
from skill_dream.llm import LLMClient
from skill_dream.pr_loader import localize_base_files
from skill_dream.skill_store import Skill, SkillStore


def make_skill(name, date=None, available_at=None):
    scope = {'date': date} if date else {}
    if available_at:
        scope['available_at'] = available_at
    return Skill(name=name, trigger={'task_type': 'feature', 'keywords': ['provider']},
                 procedure=['Register a provider'], version_scope=scope)


class ReleaseTests(unittest.TestCase):
    def test_chronological_retrieval_rejects_unknown_same_and_future_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            for name, date in [('past', '2026-01-01'), ('same', '2026-02-01'),
                               ('future', '2026-03-01'), ('unknown', None)]:
                store.apply_op('ADD', make_skill(name, date))
            store.apply_op('ADD', make_skill('late_merge', '2026-01-01', '2026-03-01'))
            found = store.retrieve('feature', ['provider'], before_date='2026-02-01', top_k=20)
            self.assertEqual([skill.name for skill in found], ['past'])

    def test_cutoff_normalizes_timezones(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', make_skill('earlier', '2026-01-01T23:30:00-02:00'))
            found = store.retrieve('feature', ['provider'], before_date='2026-01-02T01:00:00Z')
            self.assertEqual(found, [])

    def test_supersede_persists_replacement_and_archives_old_skill(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', make_skill('old', '2026-01-01'))
            store.apply_op('SUPERSEDE', make_skill('new', '2026-02-01'), target='old')
            store.save()
            restored = SkillStore(root).load()
            self.assertEqual(set(restored.skills), {'new'})
            self.assertEqual(restored.skills['new'].relations['supersedes'], 'old')
            from pathlib import Path
            self.assertTrue(list((Path(root) / 'history').glob('*.json')))

    def test_probe_in_generation_context_fails(self):
        guard = LeakGuard()
        forbidden = guard.inject('held-out patch')
        with self.assertRaises(LeakViolation):
            guard.assert_clean(forbidden)
        self.assertFalse(guard.report()['clean'])

    def test_localizer_uses_only_base_tree_and_task(self):
        with patch('skill_dream.pr_loader._git', return_value='src/provider.py\nsrc/core.py\ntests/test_core.py\n') as git:
            result = localize_base_files('repo', 'base-sha', 'add provider support', max_files=1)
            self.assertEqual(result, ['src/provider.py'])
            git.assert_called_once_with('repo', 'ls-tree', '-r', '--name-only', 'base-sha')

    def test_missing_credentials_fail_before_network(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'ANTHROPIC_API_KEY'):
                LLMClient()
            with self.assertRaisesRegex(RuntimeError, 'SD_EMBEDDING_ENDPOINT'):
                embed_batch(['text'])

    def test_surface_f1_measures_types_not_file_count(self):
        score = surface_f1({'code', 'tests', 'docs'}, ['src/a.py', 'src/b.py', 'tests/test_a.py'])
        self.assertAlmostEqual(score.precision, 1.0)
        self.assertAlmostEqual(score.recall, 2 / 3)
        self.assertAlmostEqual(score.f1, 0.8)


if __name__ == '__main__':
    unittest.main()
