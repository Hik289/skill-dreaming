import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from skill_dream.embedding import cosine
from skill_dream.pipeline import Pipeline, RunConfig
from skill_dream.sandbox import Sandbox, _parse_pytest
from skill_dream.skill_context import eligible, pack_skills, compatible_subset
from skill_dream.skill_store import Skill, SkillStore
from skill_dream.stages import decide_skill_ops, generate_patch
from skill_dream.staleness import assess_staleness, record_version_scope
from skill_dream.workflow import historical_rows, generate_verified, prepare


def skill(name, date='2026-01-01', **extra):
    return Skill(name, {'task_type': 'feature', 'keywords': ['provider']},
                 ['Implement ' + name], version_scope={'date': date}, **extra)


class SkillLifecycleTests(unittest.TestCase):
    def test_long_stream_bounds_pool_and_preserves_archives(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root, max_active=12)
            for index in range(120):
                store.apply_op('ADD', skill('provider-' + str(index)))
                store.save()
                self.assertLessEqual(len(store.skills), 12)
            restored = SkillStore(root).load()
            self.assertEqual(restored.max_active, 12)
            self.assertEqual(len(restored.skills), 12)
            self.assertEqual(len(list(Path(root, 'history').glob('*.json'))), 108)
            self.assertEqual(sum(op['op'] == 'ARCHIVE' for op in restored.log), 108)

    def test_same_name_add_preserves_provenance_and_statistics(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            original = skill('provider', positive_evidence=['a'], review_evidence=['review'])
            store.apply_op('ADD', original)
            store.update_stats('provider', True)
            store.apply_op('ADD', skill('provider', positive_evidence=['b']))
            current = store.skills['provider']
            self.assertEqual(current.positive_evidence, ['a', 'b'])
            self.assertEqual(current.review_evidence, ['review'])
            self.assertEqual(current.stats['success'], 1)
            self.assertEqual(store.log[-1]['op'], 'UPDATE')

    def test_names_cannot_escape_store_or_collide_after_sanitizing(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            for name in ['../outside.json', 'a/b', 'a_b']:
                store.apply_op('ADD', skill(name))
            store.save()
            self.assertEqual(len(list(Path(root, 'current').glob('*.json'))), 3)
            self.assertFalse(Path(root, 'outside.json').exists())
            self.assertEqual(len(SkillStore(root).load().skills), 3)

    def test_conflicting_skills_are_persisted_but_not_injected_together(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', skill('first'))
            store.apply_op('CONFLICT', skill('second'), target='first')
            store.save()
            restored = SkillStore(root).load()
            self.assertEqual(len(restored.skills), 2)
            self.assertEqual(len(restored.retrieve('feature', ['provider'])), 1)

    def test_specialize_extend_and_keep_preserve_parent(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', skill('parent'))
            store.apply_op('SPECIALIZE', skill('child'), 'parent')
            store.apply_op('EXTEND', skill('extension'), 'parent')
            store.apply_op('KEEP', skill('parent'))
            self.assertEqual(len(store.skills), 3)
            self.assertEqual(store.skills['child'].relations['specializes'], 'parent')
            self.assertEqual(store.skills['extension'].relations['extends'], 'parent')

    def test_invalid_relation_cannot_delete_a_skill(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', skill('old'))
            with self.assertRaises(ValueError):
                store.apply_op('SUPERSEDE', skill('new'), 'missing')
            self.assertIn('old', store.skills)

    def test_admission_filters_target_source_and_unknown_dates(self):
        candidate = skill('source', positive_evidence=['target'])
        self.assertFalse(eligible(candidate, '2026-02-01', ['target']))
        candidate.version_scope['available_at'] = '2026-03-01'
        self.assertFalse(eligible(candidate, '2026-02-01'))
        with self.assertRaises(ValueError):
            eligible(candidate, 'invalid')

    def test_version_scope_writer_is_compatible_with_retriever(self):
        candidate = skill('source')
        record_version_scope(candidate, {'date': '2026-01-01T00:00:00Z', 'sha': 'abc'}, [], [])
        self.assertTrue(eligible(candidate, '2026-02-01'))

    def test_pack_keeps_constraints_maintenance_and_validation(self):
        candidate = skill('source', negative_constraints=['Never use removed call'],
                          required_surfaces=['tests', 'docs'], validation=['Run regression suite'])
        text, included, info = pack_skills([candidate], 2000)
        self.assertIn('Never use removed call', text)
        self.assertIn('Run regression suite', text)
        self.assertIn('maintenance', text)
        self.assertNotIn('positive_evidence', text)
        self.assertEqual(info['characters'], len(text))
        self.assertEqual(included, [candidate])

    def test_oversized_skill_is_omitted_not_truncated(self):
        big, small = skill('big'), skill('small')
        big.procedure = ['x' * 2000]
        text, included, info = pack_skills([big, small], 500)
        self.assertLessEqual(len(text), 500)
        self.assertEqual([s.name for s in included], ['small'])
        self.assertEqual(info['omitted_for_budget'], ['big'])
        self.assertEqual(pack_skills([small], 0)[0], '')

    def test_dedup_and_supersession_filter(self):
        first, duplicate, new = skill('first'), skill('duplicate'), skill('new')
        duplicate.procedure = first.procedure
        self.assertEqual(len(compatible_subset([first, duplicate], 8)), 1)
        new.relations['supersedes'] = 'first'
        self.assertEqual([s.name for s in compatible_subset([first, new], 8)], ['new'])

    def test_dense_retrieval_filters_before_embedding(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', skill('earlier'))
            store.apply_op('ADD', skill('later', '2026-03-01'))
            embed = Mock(return_value=[[1., 0.], [1., 0.]])
            result = store.retrieve('feature', ['provider'], before_date='2026-02-01', mode='dense', embed=embed)
            self.assertEqual([s.name for s in result], ['earlier'])
            self.assertEqual(len(embed.call_args.args[0]), 2)

    def test_hybrid_and_zero_budget(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', skill('earlier'))
            result = store.retrieve('feature', ['provider'], mode='hybrid', embed=lambda _: [[1.], [1.]])
            self.assertEqual(len(result), 1)
            self.assertEqual(store.retrieve('feature', ['provider'], top_k=0), [])
            with self.assertRaises(ValueError):
                store.retrieve('feature', ['provider'], top_k=-1)

    def test_embedding_dimension_mismatch_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            cosine([1, 2], [1])

    def test_alignment_fallback_and_guarded_supersession(self):
        old, new = skill('old'), skill('new', '2026-02-01')
        llm = Mock()
        llm.complete_json.return_value = {'operations': [{'name': 'new', 'op': 'SUPERSEDE', 'target': 'old', 'reason': 'similar'}]}
        self.assertEqual(decide_skill_ops(llm, [new], [old])[0][0], 'CONFLICT')
        new.relations['supersedes'] = 'old'
        self.assertEqual(decide_skill_ops(llm, [new], [old])[0][0], 'SUPERSEDE')
        llm.complete_json.side_effect = RuntimeError('offline')
        self.assertEqual(decide_skill_ops(llm, [new], [old])[0][0], 'ADD')
        self.assertEqual(decide_skill_ops(llm, [old], ['old'])[0][0], 'UPDATE')

    def test_generation_reports_only_injected_skills(self):
        llm = Mock()
        llm.complete_json.return_value = {'edits': [], 'new_files': []}
        result = generate_patch(llm, 'task', 'base', [skill('huge')], max_skill_chars=1)
        self.assertEqual(result['skills_used'], [])
        self.assertEqual(result['skill_injection']['characters'], 0)

    def test_history_uses_availability_and_normalized_timestamps(self):
        target = {'pr': 3, 'sha': 'target', 'date': '2026-02-01T00:00:00Z'}
        rows = [{'pr': 1, 'sha': 'a', 'date': '2026-01-01'},
                {'pr': 2, 'sha': 'b', 'date': '2026-01-01', 'available_at': '2026-03-01'},
                {'pr': 3, 'sha': 'target', 'date': '2026-01-01'},
                {'pr': 4, 'sha': 'c', 'date': '2026-01-31T23:30:00-02:00'}]
        self.assertEqual([r['pr'] for r in historical_rows(rows, target)], [1])

    def test_empty_tests_and_skipped_only_tests_are_not_success(self):
        self.assertFalse(_parse_pytest('no tests ran', 0).ok)
        self.assertFalse(_parse_pytest('4 skipped', 0).ok)
        self.assertTrue(_parse_pytest('2 passed in 0.1s', 0).ok)

    def test_sandbox_rejects_traversal_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as root:
            sb = Sandbox(root, 'HEAD', root, 'checkout')
            Path(sb.path).mkdir()
            for path in ['../escape', '/tmp/escape', '.git/config']:
                with self.assertRaises(ValueError):
                    sb.write_file(path, 'not written')
            Path(sb.path, 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                sb.write_file('link/escape', 'not written')

    def test_removed_symbol_in_existing_file_is_stale(self):
        with patch('skill_dream.staleness._path_exists_at', return_value=True), patch('skill_dream.staleness._symbol_exists_at', return_value=False):
            candidate = skill('stale')
            candidate.version_scope.update({'referenced_paths': ['src/main.py'], 'referenced_symbols': ['removed']})
            self.assertTrue(assess_staleness('repo', 'base', candidate)['stale'])

    def test_repair_loop_is_bounded_and_uses_no_target_diff(self):
        pipe = SimpleNamespace(cfg=SimpleNamespace(repair_attempts=1, model='configured', skill_context_chars=1000), llm=Mock())
        failure = {'accepted': False, 'patch_applies': True, 'tests_pass': False, 'missing_surfaces': ['docs'], 'checks': {}}
        with patch('skill_dream.workflow.verify', return_value=failure) as checker, patch('skill_dream.stages.generate_patch', return_value={}) as generator:
            _, checks = generate_verified(pipe, 'feature', 'base context', [], {'base': 'base'}, 'run', ['docs'], None)
        self.assertEqual(checker.call_count, 2)
        self.assertEqual(len(checks), 2)
        self.assertIn('previous candidate failed', generator.call_args.args[1])

    def test_failed_candidate_cannot_generate_a_skill(self):
        pipe = SimpleNamespace(cfg=SimpleNamespace(run_existing_tests=True, model='configured', learning_candidates=2), llm=Mock())
        row = {'pr': 2, 'sha': 'target', 'date': '2026-02-01', 'subject': 'feature', 'base': 'base'}
        with patch('skill_dream.workflow.maintenance_plan', return_value={'required_surfaces': []}), patch('skill_dream.workflow.generate_verified', return_value=({}, [{'accepted': False}])) as generator, patch('skill_dream.stages.generate_skills') as distill:
            skills, record = prepare(pipe, row, [], {}, 'base', [], 'run', None)
        self.assertEqual(generator.call_count, 2)
        distill.assert_not_called()
        self.assertEqual(skills, [])
        self.assertEqual(record['status'], 'no_verified_candidate')

    def test_verified_learning_cannot_disable_tests(self):
        with self.assertRaises(ValueError):
            RunConfig('repo', 'work', 'skills', 'python', verified_learning=True, run_existing_tests=False)

    def test_real_worktree_evaluation_counts_actual_changes(self):
        import sys
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root, 'repo')
            repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            Path(repo, 'value.py').write_text('VALUE = 1\n')
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-qm', 'fixture'], check=True)
            pipe = Pipeline.__new__(Pipeline)
            pipe.cfg = RunConfig(str(repo), str(Path(root, 'runs')), str(Path(root, 'skills')), sys.executable)
            candidate = {'edits': [{'path': 'value.py', 'search': 'VALUE = 1', 'replace': 'VALUE = 2'}],
                         'new_files': {'tests/test_value.py': 'def test_value():\n    assert 2 == 2\n'},
                         'changed_files': ['fake/docs.md']}
            gold = SimpleNamespace(files=['value.py', 'tests/test_value.py'], gold_surfaces=lambda: {'code', 'tests'})
            with patch.object(Sandbox, 'pip_install_e', return_value=(True, '')), patch.object(Sandbox, 'run_pytest', return_value=_parse_pytest('1 passed', 0)):
                result = pipe._evaluate(gold, candidate, 'HEAD', 'fixture')
            self.assertTrue(result.task_success)
            self.assertEqual(result.detail['actual_changed_files'], ['tests/test_value.py', 'value.py'])
            self.assertEqual(result.surface.f1, 1.0)
            self.assertEqual(Path(repo, 'value.py').read_text(), 'VALUE = 1\n')

    def test_complete_verified_replay_orders_learning_before_actor(self):
        import sys
        from skill_dream.llm import TokenMeter
        from skill_dream.leakguard import LeakGuard
        from skill_dream.pr_loader import index_history
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root, 'repo')
            repo.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
            git('init', '-q')
            Path(repo, 'value.py').write_text('VALUE = 1\n')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-qm', 'initial')
            base = git('rev-parse', 'HEAD')
            Path(repo, 'value.py').write_text('VALUE = 3\nHELD_OUT_ONLY = True\n')
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-qm', 'add feature (#2)')
            target = git('rev-parse', 'HEAD')
            rows = index_history(str(repo))
            self.assertEqual(rows[0]['sha'], target)
            self.assertEqual(rows[0]['base'], base)
            self.assertEqual(rows[0]['files'], ['value.py'])
            pipe = Pipeline.__new__(Pipeline)
            pipe.cfg = RunConfig(str(repo), str(Path(root, 'runs')), str(Path(root, 'skills')), sys.executable,
                                 verified_learning=True, repair_attempts=0)
            pipe.store = SkillStore(pipe.cfg.skills_root, max_active=3)
            pipe.meter = TokenMeter()
            events = []
            def answer(prompt, **kwargs):
                role = kwargs['role']
                events.append((role, prompt))
                if role == 'detect':
                    return {'detected': [], 'task_type': 'feature', 'keywords': ['value']}
                if role == 'synthesize':
                    return {'candidates': []}
                if role == 'maintenance_plan':
                    return {'required_surfaces': ['tests'], 'obligations': []}
                if role == 'patch_gen':
                    return {'edits': [{'path': 'value.py', 'search': 'VALUE = 1', 'replace': 'VALUE = 2'}],
                            'new_files': [{'path': 'tests/test_value.py', 'content': 'def test_value():\n    assert True\n'}]}
                if role == 'skill_synth':
                    return {'skills': [{'name': 'value-extension', 'trigger': {'task_type': 'feature', 'keywords': ['value']},
                                        'procedure': ['Extend value and add regression coverage'], 'validation': ['Run tests']}]}
                return {'operations': []}
            pipe.llm = SimpleNamespace(complete_json=answer)
            row = {'pr': 2, 'sha': target, 'base': base, 'date': '2026-02-01', 'available_at': '2026-02-02', 'subject': 'Add value support'}
            with patch.object(Sandbox, 'pip_install_e', return_value=(True, '')), patch.object(Sandbox, 'run_pytest', return_value=_parse_pytest('1 passed', 0)):
                result = pipe.run_pr(row, [], LeakGuard())
            self.assertTrue(result['outcome']['accepted_locally'])
            actor_prompts = [prompt for role, prompt in events if role == 'patch_gen']
            self.assertEqual(len(actor_prompts), 2)
            self.assertNotIn('HELD_OUT_ONLY', ''.join(actor_prompts))
            self.assertNotIn('value-extension', actor_prompts[0])
            self.assertIn('value-extension', actor_prompts[1])
            writer_prompts = [prompt for role, prompt in events if role == 'skill_synth']
            self.assertNotIn('HELD_OUT_ONLY', writer_prompts[0])
            self.assertIn('HELD_OUT_ONLY', writer_prompts[1])
            self.assertEqual(pipe.store.skills['value-extension'].version_scope['available_at'], '2026-02-02')
            self.assertTrue(Path(pipe.cfg.workdir, result['run_id'], 'record.json').exists())
            self.assertIn('HELD_OUT_ONLY', Path(repo, 'value.py').read_text())


if __name__ == '__main__':
    unittest.main()
