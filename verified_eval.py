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
    for a in (['image', 'prune', '-f'], ['builder', 'prune', '-f'], ['container', 'prune', '-f']):
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--method', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--batch', type=int, default=10)
    ap.add_argument('--eval_workers', type=int, default=3)
    ap.add_argument('--model_name', default='skilldream_verified')
    ap.add_argument('--timeout', type=int, default=1800)
    ap.add_argument('--min_disk_gb', type=float, default=35.0)
    ap.add_argument('--max_retries', type=int, default=2)
    ap.add_argument('--no_prune', action='store_true')
    a = ap.parse_args()
    predp = os.path.join(SWE, f'verified_preds_{a.method}_{a.tag}.jsonl')
    preds = [json.loads(l) for l in open(predp)]
    for p in preds:
        p.setdefault('model_name_or_path', a.model_name)
    all_ids = [p['instance_id'] for p in preds]
    outp = os.path.join(SWE, f'verified_eval_{a.method}_{a.tag}.json')
    results = {}
    if os.path.exists(outp):
        try:
            results = json.load(open(outp))
        except Exception:
            results = {}
    todo = [i for i in all_ids if i not in results]
    print(f'[eval:{a.method}:{a.tag}] total={len(all_ids)} done={len(results)} todo={len(todo)}', flush=True)
    pred_by_id = {p['instance_id']: p for p in preds}
    i = 0
    while i < len(todo):
        if disk_free_gb() < a.min_disk_gb:
            prune_docker()
            if disk_free_gb() < a.min_disk_gb:
                print('[eval] disk low STOP', flush=True)
                break
        batch = todo[i:i + a.batch]
        run_id = f'veri_{a.method}_{a.tag}_b{i // a.batch}_{int(time.time())}'
        bp = os.path.join(SWE, f'_veri_batch_{run_id}.jsonl')
        with open(bp, 'w') as f:
            for iid in batch:
                f.write(json.dumps(pred_by_id[iid]) + '\n')
        cmd = [sys.executable, '-m', 'swebench.harness.run_evaluation', '--dataset_name', HF, '--split', 'test', '--predictions_path', bp, '--instance_ids', *batch, '--max_workers', str(a.eval_workers), '--cache_level', 'env', '--run_id', run_id, '--timeout', str(a.timeout)]
        print(f'[harness] run_id={run_id} ids={len(batch)}', flush=True)
        try:
            subprocess.run(cmd, cwd=SWE, timeout=a.timeout * max(1, len(batch)) + 2400)
        except subprocess.TimeoutExpired:
            print('[eval] harness TIMEOUT, prune+retry batch', flush=True)
            prune_docker()
            time.sleep(20)
            try:
                os.remove(bp)
            except Exception:
                pass
            continue
        except Exception as e:
            print('[eval] harness ERR', e, flush=True)
            time.sleep(20)
        rep = load_reports(run_id, a.model_name, batch)
        for iid in batch:
            if iid not in rep:
                continue
            pe = rep.get(iid, {})
            pr = pred_by_id[iid]
            results[iid] = {'resolved': bool(pe.get('resolved', False)), 'patch_applied': pe.get('patch_applied'), 'empty_patch': pe.get('patch_is_None') or len(pr.get('model_patch', '')) == 0, 'f2p': f"{pe.get('f2p_pass', '?')}/{pe.get('f2p_pass', 0) + pe.get('f2p_fail', 0)}", 'p2p': f"{pe.get('p2p_pass', '?')}/{pe.get('p2p_pass', 0) + pe.get('p2p_fail', 0)}", 'n_skills': pr.get('n_skills'), 'exit_status': pr.get('exit_status'), 'diff_bytes': len(pr.get('model_patch', '')), 'has_report': True}
        json.dump(results, open(outp, 'w'), indent=1)
        missing = [iid for iid in batch if iid not in results]
        nres = sum((1 for v in results.values() if v.get('resolved')))
        print(f'[eval:{a.method}:{a.tag}] done={len(results)}/{len(all_ids)} resolved={nres} batch_missing={len(missing)} disk={disk_free_gb():.0f}G', flush=True)
        try:
            os.remove(bp)
        except Exception:
            pass
        if not a.no_prune:
            prune_docker()
        i += a.batch
    for attempt in range(a.max_retries):
        missing = [i for i in all_ids if i not in results]
        if not missing:
            break
        print(f'[eval:{a.method}:{a.tag}] RETRY {attempt + 1}: {len(missing)} missing reports {missing[:5]}...', flush=True)
        run_id = f'veri_{a.method}_{a.tag}_retry{attempt}_{int(time.time())}'
        bp = os.path.join(SWE, f'_veri_batch_{run_id}.jsonl')
        with open(bp, 'w') as f:
            for iid in missing:
                f.write(json.dumps(pred_by_id[iid]) + '\n')
        cmd = [sys.executable, '-m', 'swebench.harness.run_evaluation', '--dataset_name', HF, '--split', 'test', '--predictions_path', bp, '--instance_ids', *missing, '--max_workers', str(a.eval_workers), '--cache_level', 'env', '--run_id', run_id, '--timeout', str(a.timeout)]
        try:
            subprocess.run(cmd, cwd=SWE, timeout=a.timeout * max(1, len(missing)) + 2400)
        except Exception as e:
            print('[eval] retry harness ERR', e, flush=True)
        rep = load_reports(run_id, a.model_name, missing)
        for iid in missing:
            if iid not in rep:
                continue
            pe = rep[iid]
            pr = pred_by_id[iid]
            results[iid] = {'resolved': bool(pe.get('resolved', False)), 'patch_applied': pe.get('patch_applied'), 'empty_patch': pe.get('patch_is_None') or len(pr.get('model_patch', '')) == 0, 'f2p': f"{pe.get('f2p_pass', '?')}/{pe.get('f2p_pass', 0) + pe.get('f2p_fail', 0)}", 'p2p': f"{pe.get('p2p_pass', '?')}/{pe.get('p2p_pass', 0) + pe.get('p2p_fail', 0)}", 'n_skills': pr.get('n_skills'), 'exit_status': pr.get('exit_status'), 'diff_bytes': len(pr.get('model_patch', '')), 'has_report': True}
        json.dump(results, open(outp, 'w'), indent=1)
        try:
            os.remove(bp)
        except Exception:
            pass
        if not a.no_prune:
            prune_docker()
    nres = sum((1 for v in results.values() if v.get('resolved')))
    still_missing = [i for i in all_ids if i not in results]
    complete = len(results) == len(all_ids) and (not still_missing)
    print(f'[eval:{a.method}:{a.tag}] ALL DONE resolved={nres}/{len(results)} (preds={len(all_ids)}) COMPLETE={complete} missing={len(still_missing)} -> {outp}', flush=True)
    if not complete:
        print(f'[eval:{a.method}:{a.tag}] !!! INTEGRITY FAIL: {len(still_missing)} instances have NO harness report (NOT counted as resolved=False): {still_missing}', flush=True)
        sys.exit(2)
    print(f'[eval:{a.method}:{a.tag}] INTEGRITY OK: completed==preds=={len(all_ids)}, no silent skips', flush=True)
if __name__ == '__main__':
    main()
