import sys
sys.path.insert(0, 'adapter')
import sd_swebench_adapter as A, sd_v2 as V2
from skill_dream.llm import LLMClient, TokenMeter
insts = {r['instance_id']: r for r in A.load_instances('verified')}
inst = insts['sphinx-doc__sphinx-8269']
llm = LLMClient(TokenMeter())
task = inst['problem_statement']
(wt, bare) = A.ensure_repo(inst['repo'], inst['base_commit'])
kws = V2._kw(task, 60)
(files, tree) = V2.localize_files(llm, task, wt)
(ctx, fl) = V2.build_anchored_context(wt, files, kws, task)
print('ctx_bytes=', len(ctx), 'nfiles=', len(files))
g = V2.gen_patch(llm, task, ctx, [], seed=0)
print('llm_failed=', g.get('llm_failed'))
print('error=', str(g.get('error'))[:400])
print('n_edits=', len(g.get('edits', [])), 'root_cause=', str(g.get('root_cause'))[:120])
