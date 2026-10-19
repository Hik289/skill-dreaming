import os, sys, json, subprocess, argparse, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_dream.config import BENCHMARK_ROOT, AGENT_CONFIG
SWE = str(BENCHMARK_ROOT)
HF = 'SWE-bench/SWE-bench_Verified'

def disk_free_gb(p=SWE):
    st = os.statvfs(p)
    return st.f_bavail * st.f_frsize / 1000000000.0

def prune_docker():
    for a in (['image', 'prune', '-f'], ['container', 'prune', '-f']):
        subprocess.run(['docker', *a], capture_output=True)

def load_reports(run_id, model_name, ids):
    res = {}
    base = os.path.join(SWE, 'logs', 'run_evaluation', run_id, model_name)
    for iid in ids:
        rp = os.path.join(base, iid, 'report.json')
        if os.path.exists(rp):
            try:
                d = json.load(open(rp))[iid]
                ts = d.get('tests_status', {})
                res[iid] = {'resolved': bool(d.get('resolved', False)), 'patch_applied': d.get('patch_successfully_applied'), 'patch_is_None': d.get('patch_is_None'), 'f2p_pass': len(ts.get('FAIL_TO_PASS', {}).get('success', [])), 'f2p_fail': len(ts.get('FAIL_TO_PASS', {}).get('failure', [])), 'p2p_pass': len(ts.get('PASS_TO_PASS', {}).get('success', [])), 'p2p_fail': len(ts.get('PASS_TO_PASS', {}).get('failure', []))}
            except Exception as e:
                res[iid] = {'parse_error': str(e)}
    return res

def run_batch(batch, pred_by_id, run_id, eval_workers, inst_timeout, hard_timeout):
    bp = os.path.join(SWE, f'_veriiso_{run_id}.jsonl')
    with open(bp, 'w') as f:
        for iid in batch:
            f.write(json.dumps(pred_by_id[iid]) + '\n')
    cmd = [sys.executable, '-m', 'swebench.harness.run_evaluation', '--dataset_name', HF, '--split', 'test', '--predictions_path', bp, '--instance_ids', *batch, '--max_workers', str(eval_workers), '--cache_level', 'env', '--run_id', run_id, '--timeout', str(inst_timeout)]
    timed_out = False
    try:
        subprocess.run(cmd, cwd=SWE, timeout=hard_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        print(f'[iso] batch {run_id} HARD-TIMEOUT after {hard_timeout}s -> killing harness children', flush=True)
        subprocess.run(['pkill', '-9', '-f', run_id], capture_output=True)
        subprocess.run(['pkill', '-9', '-f', 'swebench.harness.run_evaluation'], capture_output=True)
        time.sleep(3)
    except Exception as e:
        print(f'[iso] batch {run_id} ERR {e}', flush=True)
    try:
        os.remove(bp)
    except Exception:
        pass
    return timed_out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--method', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--eval_workers', type=int, default=1)
    ap.add_argument('--model_name', default='skilldream_verified')
    ap.add_argument('--inst_timeout', type=int, default=1800)
    ap.add_argument('--hard_timeout', type=int, default=1500)
    ap.add_argument('--max_rounds', type=int, default=4)
    a = ap.parse_args()
    predp = os.path.join(SWE, f'verified_preds_{a.method}_{a.tag}.jsonl')
    preds = [json.loads(l) for l in open(predp)]
    for p in preds:
        p.setdefault('model_name_or_path', a.model_name)
    all_ids = [p['instance_id'] for p in preds]
    pred_by_id = {p['instance_id']: p for p in preds}
    outp = os.path.join(SWE, f'verified_eval_{a.method}_{a.tag}.json')
    results = {}
    if os.path.exists(outp):
        try:
            results = json.load(open(outp))
        except Exception:
            results = {}

    def is_final(v):
        return isinstance(v, dict) and (v.get('has_report') or v.get('errored'))
    results = {k: v for (k, v) in results.items() if is_final(v)}
    print(f'[iso:{a.method}:{a.tag}] preds={len(all_ids)} already_final={len(results)}', flush=True)
    for rnd in range(a.max_rounds):
        todo = [i for i in all_ids if i not in results]
        if not todo:
            break
        print(f'[iso:{a.method}:{a.tag}] ROUND {rnd}: {len(todo)} todo', flush=True)
        i = 0
        while i < len(todo):
            if disk_free_gb() < 35:
                prune_docker()
            batch = todo[i:i + a.batch]
            run_id = f'veriiso_{a.method}_{a.tag}_r{rnd}_b{i // a.batch}_{int(time.time())}'
            ht = a.hard_timeout + (len(batch) - 1) * a.hard_timeout // 2
            print(f'[iso] {run_id} ids={len(batch)} hard_to={ht}s', flush=True)
            run_batch(batch, pred_by_id, run_id, a.eval_workers, a.inst_timeout, ht)
            rep = load_reports(run_id, a.model_name, batch)
            for iid in batch:
                if iid not in rep:
                    continue
                pe = rep[iid]
                pr = pred_by_id[iid]
                results[iid] = {'resolved': bool(pe.get('resolved', False)), 'patch_applied': pe.get('patch_applied'), 'empty_patch': pe.get('patch_is_None') or len(pr.get('model_patch', '')) == 0, 'f2p': f"{pe.get('f2p_pass', '?')}/{pe.get('f2p_pass', 0) + pe.get('f2p_fail', 0)}", 'p2p': f"{pe.get('p2p_pass', '?')}/{pe.get('p2p_pass', 0) + pe.get('p2p_fail', 0)}", 'n_skills': pr.get('n_skills'), 'exit_status': pr.get('exit_status'), 'diff_bytes': len(pr.get('model_patch', '')), 'has_report': True}
            json.dump(results, open(outp, 'w'), indent=1)
            nres = sum((1 for v in results.values() if v.get('resolved')))
            print(f'[iso:{a.method}:{a.tag}] r{rnd} done={len(results)}/{len(all_ids)} resolved={nres} disk={disk_free_gb():.0f}G', flush=True)
            prune_docker()
            i += a.batch
    still = [i for i in all_ids if i not in results]
    for iid in still:
        pr = pred_by_id[iid]
        results[iid] = {'resolved': None, 'errored': 'persistent_build_failure_after_%d_rounds' % a.max_rounds, 'has_report': False, 'exit_status': pr.get('exit_status'), 'diff_bytes': len(pr.get('model_patch', '')), 'n_skills': pr.get('n_skills')}
    json.dump(results, open(outp, 'w'), indent=1)
    nres = sum((1 for v in results.values() if v.get('resolved') is True))
    nerr = sum((1 for v in results.values() if v.get('errored')))
    ndone_report = sum((1 for v in results.values() if v.get('has_report')))
    print(f'[iso:{a.method}:{a.tag}] FINAL resolved={nres} errored={nerr} with_report={ndone_report} total={len(results)}/{len(all_ids)}', flush=True)
    complete = len(results) == len(all_ids)
    if not complete:
        print(f'[iso:{a.method}:{a.tag}] !!! INTEGRITY FAIL total={len(results)} != preds={len(all_ids)}', flush=True)
        sys.exit(2)
    print(f'[iso:{a.method}:{a.tag}] INTEGRITY OK: every instance classified (resolved/unresolved/errored), none silently dropped. errored={nerr} (excluded from resolved-rate numerator AND denominator per discipline)', flush=True)
if __name__ == '__main__':
    main()
