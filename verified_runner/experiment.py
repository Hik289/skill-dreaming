import argparse
import ast
import collections
import concurrent.futures
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback
from build_suite import ROOT, SWE, OUT, read, save, sha, load_rows, freeze_setup_policy
import bedrock_runtime as bedrock
import shared_settings
import retrieval as harness
from infrastructure import normalize_checkout, pinned_image
os.environ['MSWEA_SILENT_STARTUP'] = '1'
os.environ['MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT'] = '3'
os.umask(63)
RUN = None
SECRETS = []

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result

def command(args, timeout=120):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

def redacted(obj):
    if isinstance(obj, dict):
        return {k: v if k in {'patch', 'submission'} and isinstance(v, str) else '[REDACTED]' if any((s in k.lower() for s in ['api_key', 'authorization', 'access_token'])) else redacted(v) for (k, v) in obj.items()}
    if isinstance(obj, list):
        return [redacted(x) for x in obj]
    if isinstance(obj, str):
        for key in SECRETS:
            if len(key) > 3:
                obj = obj.replace(key, '[REDACTED]')
    return obj

def write(path, data):
    save(path, redacted(data))

def prepare():
    if (RUN / 'manifest.json').exists():
        return verify()
    (dataset, model) = (RUN.parent.name, RUN.name)
    source_manifest = read(RUN.parent / 'manifest.json')
    assert sha(source_manifest['dataset_path']) == source_manifest['dataset_sha256']
    tasks = read(RUN.parent / 'tasks.json')
    cfg = shared_settings.config(dataset, model)
    save(RUN / 'config.json', cfg)
    for arm in ('base', 'ours'):
        save(RUN / ('config_' + arm + '.json'), shared_settings.config(dataset, model, arm))
    (_, raw) = load_rows(dataset)
    from swebench.harness.test_spec.test_spec import make_test_spec
    for (iid, task) in tasks.items():
        task['docker_image'] = make_test_spec(raw[iid], namespace='swebench').instance_image_key
    setup_digest = freeze_setup_policy(raw, list(tasks))
    save(RUN / 'tasks.json', tasks)
    from skill_dream.skill_store import SkillStore
    (retrieval, pools) = ({}, {})
    settings = shared_settings.retrieval()
    (preamble, postamble) = (settings['prefix'], settings['suffix'])
    query_rows = raw
    for repo in source_manifest['repo_task_counts']:
        folder = RUN / 'pools' / repo.replace('/', '__')
        pool = read(folder / 'manifest.json')
        assert pool['model'] == model and len(pool['skills']) == 200
        assert pool['source_manifest_sha256'] == sha(RUN.parent / 'manifest.json')
        assert pool['source_records_sha256'] == source_manifest['sources'][repo]['sha256']
        assert sha(source_manifest['sources'][repo]['path']) == source_manifest['sources'][repo]['sha256']
        for (name, digest) in pool['skills'].items():
            assert sha(folder / 'current' / name) == digest
        store = SkillStore(str(folder)).load()
        assert len(store.skills) == 200
        skills = sorted(store.skills.values(), key=lambda s: s.name)
        pools[repo] = {'manifest_sha256': sha(folder / 'manifest.json'), 'skills': pool['skills']}
        sources = read(source_manifest['sources'][repo]['path'])
        eligible = {r['sha'] for r in sources}
        assert all((set(s.positive_evidence) <= eligible and s.positive_evidence for s in skills))
        for (iid, task) in tasks.items():
            if task['repo'] != repo:
                continue
            query = query_rows[iid]['problem_statement']
            (selected, meta) = harness.retrieve(query, skills, settings['mode'], model, settings['dense_threshold'], settings['top_k'])
            block = preamble + '\n\n'.join((harness.render_skill(s, j + 1) for (j, s) in enumerate(selected))) + '\n\n' + postamble if selected else ''
            retrieval[iid] = {'repo': repo, 'skills': [s.name for s in selected], 'block': block, 'source_commits': sorted({c for s in selected for c in s.positive_evidence}), 'meta': meta, 'query_sha256': hashlib.sha256(query.encode()).hexdigest()}
        print('RETRIEVAL_FROZEN', dataset, model, repo, flush=True)
    save(RUN / 'retrieval.json', retrieval)
    save(RUN / 'manifest.json', {
        'dataset': dataset, 'model': model, 'tasks': source_manifest['tasks'],
        'provider': 'aws_bedrock', 'region': bedrock.REGION,
        'shared_settings_sha256': shared_settings.fingerprint(),
        'setup_policy_sha256': setup_digest,
        'endpoint': bedrock.ENDPOINT, 'inference_profile': bedrock.profile(model),
        'repo_task_counts': source_manifest['repo_task_counts'], 'pools': pools,
        'source_manifest_sha256': sha(RUN.parent / 'manifest.json'),
        'config_sha256': sha(RUN / 'config.json'), 'tasks_sha256': sha(RUN / 'tasks.json'),
        'retrieval_sha256': sha(RUN / 'retrieval.json'), 'harness_sha256': sha(Path(harness.__file__)),
        'runtime_sha256': {path.name: sha(path) for path in Path(harness.__file__).parent.glob('*.py')},
        'generation_attempts': 1, 'seed_for_order_only': 42,
        'sampling': 'Provider default; no unsupported deterministic seed.',
        'pool_size_per_repository': 200, 'pool_size_total': 600,
        'baseline': 'Historical five-step Base versus seven-step Ours with skills; not a skills-only contrast',
        'workflow_by_arm': {'base': 'historical_five_step', 'ours': 'historical_seven_step'},
        'arm_config_sha256': {arm: sha(RUN / ('config_' + arm + '.json')) for arm in ('base', 'ours')},
        'cross_repository_retrieval': False, 'target_answers_used_for_generation': False})
    return verify()

def verify():
    manifest = read(RUN / 'manifest.json')
    assert manifest['shared_settings_sha256'] == shared_settings.fingerprint()
    assert manifest['setup_policy_sha256'] == sha(OUT / 'verified_setup_policy.json')
    for name, digest in manifest['runtime_sha256'].items():
        assert sha(Path(harness.__file__).parent / name) == digest
    assert manifest['provider'] == 'aws_bedrock'
    cfg = read(RUN / 'config.json')['model']
    shared_settings.check(read(RUN / 'config.json'), RUN.parent.name, RUN.name)
    for arm in ('base', 'ours'):
        path = RUN / ('config_' + arm + '.json')
        assert sha(path) == manifest['arm_config_sha256'][arm]
        shared_settings.check(read(path), RUN.parent.name, RUN.name, arm)
    assert cfg == bedrock.actor_config(cfg, RUN.name)
    assert '18820' not in json.dumps(cfg)
    assert sha(RUN.parent / 'manifest.json') == manifest['source_manifest_sha256']
    sources = read(RUN.parent / 'manifest.json')
    assert sha(sources['dataset_path']) == sources['dataset_sha256']
    assert sha(Path(harness.__file__)) == manifest['harness_sha256']
    for name in ['config', 'tasks', 'retrieval']:
        assert sha(RUN / (name + '.json')) == manifest[name + '_sha256']
    for (repo, pool) in manifest['pools'].items():
        folder = RUN / 'pools' / repo.replace('/', '__')
        assert sha(folder / 'manifest.json') == pool['manifest_sha256']
        assert len(list((folder / 'current').glob('*.json'))) == 200
        for (name, digest) in pool['skills'].items():
            assert sha(folder / 'current' / name) == digest
    return manifest

def actor(iid, arm):
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.docker import DockerEnvironment
    from minisweagent.models.litellm_model import LitellmModel
    target = RUN / 'runs' / iid / arm
    target.mkdir(parents=True, exist_ok=True)
    if (target / 'result.json').exists():
        return
    task = read(RUN / 'tasks.json')[iid]
    config = read(RUN / ('config_' + arm + '.json'))
    shared_settings.check(config, RUN.parent.name, RUN.name, arm)
    key = bedrock.configure()
    SECRETS.append(key)
    assert config['model'] == bedrock.actor_config(config['model'], RUN.name)
    config['environment']['image'] = read(target.parent / 'image.json')['Id']
    config['environment']['run_args'] += ['--label', 'skilldreaming.run=' + run_tag(), '--label', 'skilldreaming.task=' + iid, '--label', 'skilldreaming.arm=' + arm]
    retrieval = read(RUN / 'retrieval.json')[iid]
    prompt = task['problem_statement'] + (retrieval['block'] if arm == 'ours' else '')
    result = {'instance_id': iid, 'repo': task['repo'], 'arm': arm, 'model': RUN.name, 'provider': 'aws_bedrock', 'inference_profile': bedrock.profile(RUN.name), 'skills': retrieval['skills'] if arm == 'ours' else [], 'patch': '', 'exit_status': 'not_started', 'workflow': 'historical_five_step' if arm == 'base' else 'historical_seven_step', 'comparison_scope': 'historical_asymmetric_protocol_replication'}
    env = agent = None
    start = time.monotonic()
    try:
        env = DockerEnvironment(**config['environment'])
        result['initial_checkout'] = normalize_checkout(env.execute, task['base_commit'], RUN.parent.name, lambda observations: write(target / 'initial_checkout.json', observations), repo=task['repo'])
        model = LitellmModel(**config['model'])

        class TraceAgent(DefaultAgent):

            def save(self, path=None, *extra_dicts):
                write(target / 'trajectory.json', self.serialize(*extra_dicts, {'instance_id': iid}))
        agent = TraceAgent(model, env, **config['agent'])
        output = agent.run(prompt)
        result.update({'patch': output.get('submission') or '', 'exit_status': output.get('exit_status')})
    except Exception as exc:
        result.update({'exit_status': type(exc).__name__, 'error': str(exc)})
    finally:
        if agent is not None:
            write(target / 'trajectory.json', agent.serialize({'instance_id': iid}))
            result['api_calls'] = agent.n_calls
            result['returned_models'] = sorted({str(m.get('extra', {}).get('response', {}).get('model')) for m in agent.messages if m.get('extra', {}).get('response')})
        result['wall_seconds'] = round(time.monotonic() - start, 3)
        result['patch_sha256'] = hashlib.sha256(result['patch'].encode()).hexdigest()
        write(target / 'result.json', result)
        assert read(target / 'result.json')['patch'] == result['patch']
        if env is not None and env.container_id:
            container = env.container_id
            env.container_id = None
            try:
                cleanup = command(['docker', 'rm', '-f', container], 30)
                if cleanup.returncode:
                    save(target / 'cleanup.json', {'container_id': container, 'returncode': cleanup.returncode})
            except subprocess.TimeoutExpired:
                save(target / 'cleanup.json', {'container_id': container, 'status': 'timeout'})

def run_tag():
    return 'sdbr29-' + hashlib.sha256(str(RUN).encode()).hexdigest()[:10]

def evaluate(iid, arm):
    target = RUN / 'evaluations' / iid / arm
    if (target / 'result.json').exists():
        return read(target / 'result.json')
    import docker
    import swebench.harness.run_evaluation as official
    from swebench.harness.test_spec.test_spec import make_test_spec
    from swebench.harness.grading import get_logs_eval
    (_, rows) = load_rows('verified')
    row = rows[iid]
    spec = make_test_spec(row, namespace='swebench')
    from reporting import ensure_named_test_reporting
    ensure_named_test_reporting(spec, row['repo'])
    patch = row['patch'] if arm == 'gold_sanity' else read(RUN / 'runs' / iid / arm / 'result.json')['patch']
    prediction = {'instance_id': iid, 'model_patch': patch, 'model_name_or_path': arm}
    official.RUN_EVALUATION_LOG_DIR = RUN / 'official_logs'
    log = official.RUN_EVALUATION_LOG_DIR / (run_tag() + '-' + arm) / arm / iid
    start = time.monotonic()
    outcome = official.run_instance(spec, prediction, False, False, docker.from_env(), run_tag() + '-' + arm, timeout=1200)
    (report_file, output_file) = (log / official.LOG_REPORT, log / official.LOG_TEST_OUTPUT)
    report = read(report_file).get(iid, {}) if report_file.exists() else {}
    (statuses, found) = get_logs_eval(spec, str(output_file)) if output_file.exists() else ({}, False)
    passed = {name for (name, status) in statuses.items() if status == 'PASSED'}
    (f2p, p2p) = (set(spec.FAIL_TO_PASS), set(spec.PASS_TO_PASS))
    log_file = log / official.LOG_INSTANCE
    application_failed = log_file.exists() and official.APPLY_PATCH_FAIL in log_file.read_text()
    result = {'instance_id': iid, 'arm': arm, 'official_result': outcome, 'official_report': report, 'resolved': bool(outcome['resolved'] and found and statuses), 'patch_applied': bool(report.get('patch_successfully_applied')), 'n_parsed': len(statuses), 'f2p_total': len(f2p), 'p2p_total': len(p2p), 'f2p_pass': len(f2p & passed), 'p2p_pass': len(p2p & passed), 'missing_f2p': sorted(f2p - passed), 'missing_p2p': sorted(p2p - passed), 'infrastructure_error': not outcome['completed'] and (not application_failed), 'wall_seconds': round(time.monotonic() - start, 3), 'official_eval_module_sha256': sha(Path(official.__file__)), 'official_log_directory': str(log)}
    save(target / 'result.json', result)
    return result

def pair(iid):
    target = RUN / 'runs' / iid
    target.mkdir(parents=True, exist_ok=True)
    task = read(RUN / 'tasks.json')[iid]
    image = task['docker_image']
    if shutil.disk_usage(Path(os.environ.get('SD_DOCKER_STORAGE', str(RUN)))).free < 12 * 1024 ** 3:
        raise RuntimeError('Insufficient disk for next task; unrelated files remain untouched')
    with pinned_image(image, target, run_tag(), iid, command, save):
        solve_and_evaluate_pair(iid, target)
    print('PAIR_DONE', RUN.parent.name, RUN.name, iid, flush=True)

def solve_and_evaluate_pair(iid, target):
    processes = []
    for arm in ['base', 'ours']:
        if (target / arm / 'result.json').exists():
            continue
        log = (target / (arm + '.log')).open('a')
        process = subprocess.Popen([sys.executable, __file__, 'actor', '--run', str(RUN), '--iid', iid, '--arm', arm], stdout=log, stderr=subprocess.STDOUT)
        processes.append((arm, process, log, time.monotonic()))
    for (arm, process, log, start) in processes:
        try:
            process.wait(timeout=max(1, 3300 - (time.monotonic() - start)))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        finally:
            log.close()
        if not (target / arm / 'result.json').exists():
            raise RuntimeError('Actor exited without a persisted result')
    for arm in ['base', 'ours']:
        result = read(target / arm / 'result.json')
        if result.get('exit_status') not in ['Submitted', 'LimitsExceeded', 'RepeatedFormatError']:
            raise RuntimeError('Actor infrastructure error: ' + result['exit_status'])
        if any((not bedrock.model_matches(m, RUN.name) for m in result.get('returned_models', []))):
            raise RuntimeError('Returned actor model mismatch')
    for arm in ['base', 'ours', 'gold_sanity']:
        result = evaluate(iid, arm)
        if result.get('infrastructure_error'):
            raise RuntimeError('Evaluator infrastructure error')
    save(target / 'completed.json', {'complete': True})

def summarize():
    manifest = read(RUN / 'manifest.json')
    rows = []
    tasks = read(RUN / 'tasks.json')
    for iid in manifest['tasks']:
        row = {'instance_id': iid, 'repo': tasks[iid]['repo']}
        if not (RUN / 'runs' / iid / 'completed.json').exists():
            continue
        for arm in ['base', 'ours', 'gold_sanity']:
            row[arm] = read(RUN / 'evaluations' / iid / arm / 'result.json')['resolved']
        rows.append(row)
    accounting = {}
    for arm in ('base', 'ours'):
        totals = collections.Counter()
        statuses = collections.Counter()
        wall = 0.0
        for result_path in (RUN / 'runs').glob('*/' + arm + '/result.json'):
            result = read(result_path)
            statuses[result.get('exit_status', 'unknown')] += 1
            wall += result.get('wall_seconds', 0)
            trace = result_path.parent / 'trajectory.json'
            if not trace.exists():
                continue
            seen = set()
            for message in read(trace).get('messages', []):
                response = message.get('extra', {}).get('response')
                if not isinstance(response, dict):
                    continue
                rid = response.get('id')
                if rid and rid in seen:
                    continue
                if rid:
                    seen.add(rid)
                totals['successful_responses'] += 1
                usage = response.get('usage', {})
                for field in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
                    totals[field] += usage.get(field, 0) or 0
        accounting[arm] = {'usage_fields': dict(totals), 'actor_wall_seconds': wall, 'exit_statuses': dict(statuses), 'scope': 'All saved actor outcomes, including incomplete task pairs. Cache fields are reported separately, not added again to total_tokens.'}
    save(RUN / 'summary.json', {'dataset': manifest['dataset'], 'model': manifest['model'], 'provider': 'aws_bedrock', 'fixed_n': 100, 'completed_pairs': len(rows), 'all_100_complete': len(rows) == 100, 'valid_gold_checks': sum((r['gold_sanity'] for r in rows)), 'raw_counts': {a: sum((r[a] for r in rows)) for a in ['base', 'ours']}, 'actor_accounting': accounting, 'by_repo': {repo: {'completed': sum((r['repo'] == repo for r in rows)), **{a: sum((r[a] for r in rows if r['repo'] == repo)) for a in ['base', 'ours', 'gold_sanity']}} for repo in manifest['repo_task_counts']}, 'per_task': rows, 'workflow_by_arm': {'base': 'historical_five_step', 'ours': 'historical_seven_step'}, 'interpretation': 'Historical protocol replication: Base and Ours differ in workflow prompt as well as skills. Not a skills-only effect. Partial results are not a 100-task headline; gold failures require diagnosis.'})

def run(workers):
    lock = (RUN / 'coordinator.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (RUN / 'blocked.json').exists():
        raise RuntimeError('Inspect blocked.json before recovery')
    manifest = verify()
    ids = manifest['tasks'].copy()
    random.Random(42).shuffle(ids)
    pending = iter((i for i in ids if not (RUN / 'runs' / i / 'completed.json').exists()))
    stop = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        running = {}
        while True:
            while not stop and len(running) < workers:
                iid = next(pending, None)
                if iid is None:
                    break
                running[executor.submit(pair, iid)] = iid
            if not running:
                break
            (done, _) = concurrent.futures.wait(running, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                iid = running.pop(future)
                try:
                    future.result()
                except Exception as exc:
                    save(RUN / 'blocked.json', {'instance_id': iid, 'type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
                    print('BLOCKED', iid, type(exc).__name__, str(exc), flush=True)
                    stop = True
                summarize()
    if stop:
        raise SystemExit(2)

def main():
    global RUN
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['prepare', 'run', 'actor', 'evaluate', 'summarize'])
    ap.add_argument('--run', required=True, type=Path)
    ap.add_argument('--iid')
    ap.add_argument('--arm', choices=['base', 'ours', 'gold_sanity'])
    ap.add_argument('--workers', type=int, default=2)
    args = ap.parse_args()
    RUN = args.run.resolve()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'actor':
        actor(args.iid, args.arm)
    elif args.action == 'evaluate':
        print(json.dumps(evaluate(args.iid, args.arm)))
    elif args.action == 'summarize':
        summarize()
    else:
        run(args.workers)
if __name__ == '__main__':
    main()
