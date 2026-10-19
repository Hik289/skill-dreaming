import sys, json
sys.path.insert(0, 'adapter')
import sd_swebench_adapter as A, sd_v2 as V2
from skill_dream.llm import LLMClient, TokenMeter, RateLimitExhausted
targets = ['django__django-15268', 'sphinx-doc__sphinx-8269', 'sympy__sympy-21596']
insts = {r['instance_id']: r for r in A.load_instances('verified')}
for tid in targets:
    inst = insts.get(tid)
    if not inst:
        print(tid, 'NOT in verified pool')
        continue
    llm = LLMClient(TokenMeter())
    task = inst['problem_statement']
    (wt, bare) = A.ensure_repo(inst['repo'], inst['base_commit'])
    kws = V2._kw(task, 60)
    (files, tree) = V2.localize_files(llm, task, wt)
    (ctx, fl) = V2.build_anchored_context(wt, files, kws, task)
    errs = []
    for s in range(3):
        try:
            g = V2.gen_patch(llm, task, ctx, [], seed=s)
            errs.append('llm_failed' if g.get('llm_failed') else 'OK n_edits=%d' % len(g.get('edits', [])))
            if g.get('llm_failed'):
                errs[-1] += ' err=' + str(g.get('error'))[:120]
        except RateLimitExhausted as e:
            errs.append('RATE_LIMIT_EXHAUSTED')
        except Exception as e:
            errs.append('EXC ' + str(e)[:120])
    print(tid, '=>', errs)
