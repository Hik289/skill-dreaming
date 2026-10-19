from __future__ import annotations
import argparse, os, json, sys
from .pipeline import Pipeline, RunConfig
from .leakguard import LeakGuard
from .pr_loader import load_manifest
DEF_PY = os.environ.get('SD_PY', sys.executable)

def cmd_init(args):
    os.makedirs(os.path.join(args.skills, 'current'), exist_ok=True)
    os.makedirs(os.path.join(args.skills, 'history'), exist_ok=True)
    print(json.dumps({'initialized': True, 'repo': args.repo, 'skills': args.skills}))

def cmd_replay(args):
    pr_index = load_manifest(args.pr_index) if args.pr_index else load_manifest(args.manifest)
    manifest = load_manifest(args.manifest)
    cfg = RunConfig(repo=args.repo, workdir=args.workdir, skills_root=args.skills, python=args.python, use_skills=not args.no_skills, run_existing_tests=not args.no_tests, test_targets=args.test_targets.split(',') if args.test_targets else None)
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
    p = sub.add_parser('init')
    p.add_argument('--repo', required=True)
    p.add_argument('--skills', required=True)
    p.set_defaults(fn=cmd_init)
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
    p.set_defaults(fn=cmd_replay)
    args = ap.parse_args()
    args.fn(args)
if __name__ == '__main__':
    main()
