from __future__ import annotations
import argparse, os, json, sys, shlex
from .pipeline import Pipeline, RunConfig
from .leakguard import LeakGuard
from .pr_loader import load_manifest
DEF_PY = os.environ.get('SD_PY', sys.executable)

def cmd_index(args):
    from .pr_loader import index_history
    rows = index_history(args.repo, args.ref, args.before_date, args.limit)
    with open(args.output, 'w') as f:
        json.dump(rows, f, indent=2)
    print(json.dumps({'records': len(rows), 'source': 'first_parent_commit_segments'}))

def cmd_init(args):
    from .skill_store import SkillStore
    store = SkillStore(args.skills, max_active=args.max_active_skills).load()
    if args.manifest:
        if not args.before_date:
            raise ValueError('--before-date is required when bootstrapping from historical PRs')
        from .workflow import historical_rows
        from .pr_loader import get_diff
        from .llm import LLMClient
        from . import stages
        rows = historical_rows(load_manifest(args.manifest), {'date': args.before_date, 'sha': '', 'pr': None})
        llm = LLMClient()
        for row in rows:
            if row.get('status') != 'accepted':
                continue
            source = {'pr': row['pr'], 'subject': row['subject'], 'reviews': row.get('reviews', []), 'ci': row.get('ci', []), 'status': 'accepted_historical_record'}
            skills = stages.generate_skills(llm, row['subject'], source, [], gold_diff=get_diff(args.repo, row['base'], row['sha']))
            for sk in skills:
                sk.version_scope.update({'date': row['date'], 'available_at': row.get('available_at', row['date']), 'source_id': row['sha']})
            for op, sk, target in stages.decide_skill_ops(llm, skills, list(store.skills.values())):
                store.apply_op(op, sk, target, note='historical bootstrap')
            store.save()
    store.save()
    print(json.dumps({'initialized': True, 'active_skills': len(store.skills), 'max_active': store.max_active}))

def cmd_pool(args):
    from .skill_store import SkillStore
    store = SkillStore(args.skills, max_active=args.max_active_skills).load()
    archived = []
    if args.prune_stale:
        if not args.repo or not args.base:
            raise ValueError('--repo and --base are required for --prune-stale')
        from .staleness import assess_staleness
        for name, sk in list(store.skills.items()):
            check = assess_staleness(args.repo, args.base, sk)
            if check['stale']:
                store.archive(name, reason=check['reason'])
                archived.append(name)
    archived.extend(store.maintain_pool())
    store.save()
    print(json.dumps({'active_skills': len(store.skills), 'max_active': store.max_active, 'archived': archived}))

def cmd_replay(args):
    pr_index = load_manifest(args.pr_index) if args.pr_index else load_manifest(args.manifest)
    manifest = load_manifest(args.manifest)
    from .skill_store import _timestamp
    dates = [_timestamp(row.get('date')) for row in manifest]
    if any(date is None for date in dates) or dates != sorted(dates):
        raise ValueError('manifest must be ordered by valid ISO timestamps')
    if args.limit < 0:
        raise ValueError('--limit must be nonnegative')
    cfg = RunConfig(repo=args.repo, workdir=args.workdir, skills_root=args.skills, python=args.python, use_skills=not args.no_skills, run_existing_tests=not args.no_tests, test_targets=args.test_targets.split(',') if args.test_targets else None,
                    max_active_skills=args.max_active_skills, retrieve_k=args.retrieve_k,
                    retrieval_mode=args.retrieval_mode, skill_context_chars=args.skill_context_chars,
                    verified_learning=args.verified_learning, learning_candidates=args.learning_candidates,
                    repair_attempts=args.repair_attempts, check_commands=[shlex.split(c) for c in args.check_command])
    pipe = Pipeline(cfg)
    results = []
    n = args.limit or len(manifest)
    for row in manifest[:n]:
        lg = LeakGuard()
        print(f"[replay] PR#{row['pr']} :: {row['subject'][:70]}", flush=True)
        rec = pipe.run_pr(row, pr_index, lg)
        o = rec['outcome']
        print(f"  → success={o['task_success']} apply={o['patch_applies_clean']} tests={o['existing_tests_pass']} surfaceF1={o['surface_f1']:.3f} leak_clean={rec['leakguard']['clean']}", flush=True)
        results.append(rec)
    summ = _summarize(results)
    with open(os.path.join(args.workdir, 'replay_summary.json'), 'w') as f:
        json.dump(summ, f, indent=2)
    print(json.dumps(summ['aggregate'], indent=2))

def _summarize(results):
    n = len(results)

    def rate(k):
        return sum((1 for r in results if r['outcome'][k])) / n if n else 0
    import statistics as st
    f1s = [r['outcome']['surface_f1'] for r in results]
    return {'aggregate': {'n': n, 'task_success_rate': rate('task_success'), 'patch_apply_rate': rate('patch_applies_clean'), 'existing_tests_pass_rate': rate('existing_tests_pass'), 'mean_surface_f1': st.mean(f1s) if f1s else 0, 'all_leak_clean': all((r['leakguard']['clean'] for r in results)), 'total_tokens': results[-1]['outcome']['tokens']['total_tokens'] if results else 0}, 'per_pr': [{'pr': r['pr'], **r['outcome']} for r in results]}

def main():
    ap = argparse.ArgumentParser('skill-dream')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('index')
    p.add_argument('--repo', required=True)
    p.add_argument('--ref', default='HEAD')
    p.add_argument('--before-date')
    p.add_argument('--limit', type=int, default=200)
    p.add_argument('--output', required=True)
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser('init')
    p.add_argument('--repo', required=True)
    p.add_argument('--skills', required=True)
    p.add_argument('--max-active-skills', type=int, default=256)
    p.add_argument('--manifest')
    p.add_argument('--before-date')
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser('maintain')
    p.add_argument('--skills', required=True)
    p.add_argument('--max-active-skills', type=int)
    p.add_argument('--repo')
    p.add_argument('--base')
    p.add_argument('--prune-stale', action='store_true')
    p.set_defaults(fn=cmd_pool)
    p = sub.add_parser('replay')
    p.add_argument('--repo', required=True)
    p.add_argument('--manifest', required=True)
    p.add_argument('--pr-index', dest='pr_index', default=None)
    p.add_argument('--skills', required=True)
    p.add_argument('--workdir', required=True)
    p.add_argument('--python', default=DEF_PY)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--no-skills', action='store_true')
    p.add_argument('--no-tests', action='store_true')
    p.add_argument('--test-targets', default=None)
    p.add_argument('--max-active-skills', type=int, default=256)
    p.add_argument('--retrieve-k', type=int, default=8)
    p.add_argument('--retrieval-mode', choices=['lexical', 'dense', 'hybrid'], default='lexical')
    p.add_argument('--skill-context-chars', type=int, default=12000)
    p.add_argument('--verified-learning', action='store_true')
    p.add_argument('--learning-candidates', type=int, default=3)
    p.add_argument('--repair-attempts', type=int, default=1)
    p.add_argument('--check-command', action='append', default=[])
    p.set_defaults(fn=cmd_replay)
    args = ap.parse_args()
    args.fn(args)
if __name__ == '__main__':
    main()
