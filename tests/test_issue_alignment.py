import tempfile
import unittest

from skill_dream.issue_alignment import (anchor_score_pr, issue_anchors,
                                         rank_historical_prs, select_bounded_skill_pool)
from skill_dream.skill_store import Skill, SkillStore


def candidate(name, source, repo='example/repo', confidence=0.7, keywords=None):
    return Skill(name, {'task_type': 'feature', 'keywords': keywords or [name],
                        'repository_surfaces': []}, ['Implement ' + name],
                 validation=['Run related tests'], confidence=confidence,
                 version_scope={'repo': repo, 'source_id': source, 'date': '2026-01-01'})


class IssueAlignmentTests(unittest.TestCase):
    def test_issue_anchors_cover_paths_and_identifier_spellings(self):
        anchors = issue_anchors('Fix `qutebrowser/utils/urlutils.py` for ImportAPI and BIG-IP')
        self.assertEqual(anchors['qutebrowser/utils/urlutils.py'], 3)
        self.assertEqual(anchors['importapi'], 2)
        self.assertEqual(anchors['bigip'], 2)
        self.assertGreater(anchor_score_pr({'files': ['qutebrowser/utils/urlutils.py'],
                                            'subject': 'URL fix', 'body': ''}, anchors), 0)

    def test_pr_ranking_uses_anchors_but_excludes_future_and_target(self):
        records = [
            {'sha': 'generic', 'pr': 1, 'date': '2026-01-01',
             'subject': 'Add new feature', 'body': 'Provider API', 'files': ['src/provider.py']},
            {'sha': 'matched', 'pr': 2, 'date': '2026-01-02',
             'subject': 'Fix URL processing', 'body': '', 'files': ['qutebrowser/utils/urlutils.py']},
            {'sha': 'target', 'pr': 3, 'date': '2026-01-03',
             'subject': 'Fix urlutils', 'body': '', 'files': ['qutebrowser/utils/urlutils.py']},
            {'sha': 'future', 'pr': 4, 'date': '2026-03-01',
             'subject': 'Fix urlutils', 'body': '', 'files': ['qutebrowser/utils/urlutils.py']},
        ]
        result = rank_historical_prs('Fix `qutebrowser/utils/urlutils.py`', records,
                                     '2026-02-01', exclude_sources=('target', 3))
        self.assertEqual([row['sha'] for row in result], ['matched', 'generic'])

    def test_pool_reserves_issue_linked_sources_and_rejects_mixed_repos(self):
        skills = [candidate('import_api-publishers', 'pr-a', keywords=['ImportAPI', 'publishers']),
                  candidate('generic-provider', 'pr-a'),
                  candidate('bigip-virtual-server', 'pr-b', keywords=['BIG-IP', 'virtual server']),
                  candidate('documentation-update', 'pr-c')]
        chosen, pinned = select_bounded_skill_pool(
            skills, {'issue-a': ['pr-a'], 'issue-b': ['pr-b']},
            {'issue-a': 'Add ImportAPI publishers', 'issue-b': 'Add BIG-IP virtual server'},
            3, '2026-02-01')
        self.assertEqual(len(chosen), 3)
        self.assertEqual(pinned['issue-a']['skill'], 'import_api-publishers')
        self.assertEqual(pinned['issue-b']['skill'], 'bigip-virtual-server')
        with self.assertRaises(ValueError):
            select_bounded_skill_pool(skills + [candidate('foreign', 'pr-d', 'other/repo')],
                                      {}, {}, 3, '2026-02-01')

    def test_pool_rejects_future_or_excluded_source(self):
        skills = [candidate('old-one', 'pr-a'), candidate('old-two', 'pr-b'),
                  candidate('future', 'pr-c')]
        skills[-1].version_scope['date'] = '2026-03-01'
        chosen, _ = select_bounded_skill_pool(skills, {}, {}, 1, '2026-02-01', ('pr-a',))
        self.assertEqual([skill.name for skill in chosen], ['old-two'])

    def test_anchored_retrieval_filters_mismatched_and_future_skills(self):
        with tempfile.TemporaryDirectory() as root:
            store = SkillStore(root)
            store.apply_op('ADD', candidate('import_api-publishers', 'pr-a',
                                             keywords=['import_api', 'publishers']))
            store.apply_op('ADD', candidate('sql-completion', 'pr-b'))
            later = candidate('ImportAPI-future', 'pr-c', keywords=['ImportAPI', 'publishers'])
            later.version_scope['date'] = '2026-03-01'
            store.apply_op('ADD', later)
            found = store.retrieve('feature', ['publishers'], mode='anchored',
                                   query='Title: Add ImportAPI publishers support',
                                   before_date='2026-02-01')
            self.assertEqual([skill.name for skill in found], ['import_api-publishers'])
            with self.assertRaises(ValueError):
                store.retrieve('feature', [], mode='anchored')


if __name__ == '__main__':
    unittest.main()
