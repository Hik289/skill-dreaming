import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import bedrock_runtime as bedrock
ROOT = Path(__file__).resolve().parents[1]
SWE = Path(os.environ.get('SD_BENCH_ROOT', 'workspace/benchmark')).resolve()
OUT = Path(os.environ.get('SD_VERIFIED_ROOT', 'workspace/verified')).resolve()
VERIFIED_REPOS = ['django/django', 'sympy/sympy', 'sphinx-doc/sphinx']
os.umask(63)
sys.path.insert(0, str(ROOT))

def read(path):
    return json.loads(Path(path).read_text())

def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git(repo, *args):
    path = SWE / 'repos_cache' / (repo.replace('/', '__') + '.git')
    result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    result.check_returncode()
    return result.stdout

def load_rows(dataset):
    if dataset != 'verified':
        raise ValueError('This runner is Verified-only')
    path = Path(os.environ.get('SD_VERIFIED_DATA', str(SWE / 'data/swebench_verified.jsonl'))).resolve()
    return (path, {r['instance_id']: r for r in map(json.loads, path.read_text().splitlines())})

def prepare(dataset):
    folder = OUT / dataset
    if (folder / 'manifest.json').exists():
        print('FROZEN_MANIFEST_EXISTS', dataset, flush=True)
        return
    (file, rows) = load_rows(dataset)
    repos = VERIFIED_REPOS
    rng = random.Random(42)
    ids = []
    for (repo, n) in zip(repos, [34, 33, 33]):
        available = sorted((i for (i, r) in rows.items() if r['repo'] == repo))
        ids.extend(sorted(rng.sample(available, n)))
    assert len(ids) == len(set(ids)) == 100
    tasks = {i: {k: rows[i][k] for k in ['instance_id', 'repo', 'base_commit', 'problem_statement']} for i in ids}
    save(folder / 'tasks.json', tasks)
    save(folder / 'ids.json', ids)
    sources = {}
    for repo in repos:
        bases = sorted({rows[i]['base_commit'] for i in ids if rows[i]['repo'] == repo})
        common = git(repo, 'merge-base', '--octopus', *bases).strip()
        assert common and '\n' not in common
        for base in bases:
            git(repo, 'merge-base', '--is-ancestor', common, base)
        cutoff = min((int(git(repo, 'show', '-s', '--format=%ct', b).strip()) for b in bases))
        lineage = {line.split()[1]: int(line.split()[0]) for line in git(repo, 'rev-list', '--timestamp', common).splitlines()}
        dest = folder / 'sources' / (repo.replace('/', '__') + '.json')
        if dest.exists():
            records = read(dest)
            assert len(records) == 600
            assert all((r['repo'] == repo and r['sha'] in lineage and (r['committer_unix'] == lineage[r['sha']] < cutoff) for r in records))
            print('SOURCE_CHECKPOINT_REUSED', dataset, repo, len(records), flush=True)
        else:
            commits = git(repo, 'log', '--no-merges', '-3000', '--format=%H%x01%cI%x01%s', common).splitlines()
            records = []
            for line in commits:
                (commit, date, subject) = line.split('\x01', 2)
                if lineage[commit] >= cutoff:
                    continue
                diff = git(repo, 'show', '--format=', '--unified=3', commit)
                if not diff.strip() or len(diff) > 50000:
                    continue
                files = re.findall('^\\+\\+\\+ b/(.+)$', diff, re.M)
                if not files or not any((f.endswith(('.py', '.js', '.ts', '.rst', '.md')) for f in files)):
                    continue
                records.append({'sha': commit, 'date': date, 'subject': subject, 'body': '', 'diff': diff, 'source_selection': 'Recent eligible non-merge history; no target issue or answer ranking.'})
                if len(records) % 100 == 0:
                    print('SOURCE_PROGRESS', dataset, repo, len(records), flush=True)
                if len(records) >= 600:
                    break
        if len(records) < 200:
            raise RuntimeError('Insufficient distinct historical source records: ' + repo)
        for record in records:
            record['committer_unix'] = lineage[record['sha']]
            record['repo'] = repo
        save(dest, records)
        sources[repo] = {'path': str(dest), 'sha256': sha(dest), 'records': len(records), 'common_ancestor': common, 'earliest_target_base_unix': cutoff, 'all_sources_ancestors_of_every_target': True}
        print('SOURCES_FROZEN', dataset, repo, len(records), flush=True)
    save(folder / 'manifest.json', {'dataset': dataset, 'tasks': ids, 'seed': 42, 'repo_task_counts': dict(collections.Counter((rows[i]['repo'] for i in ids))), 'dataset_path': str(file), 'dataset_sha256': sha(file), 'tasks_sha256': sha(folder / 'tasks.json'), 'sources': sources, 'skill_capacity_per_repo': 200, 'source_policy': 'Common-ancestor, pre-base historical commits, not target answers.', 'sampling_policy': 'Seed-42 stratified sample from sorted official repository task IDs, before model outcomes.', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})

def freeze_setup_policy(rows, ids):
    import swebench.harness.constants.python as official
    from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
    records = {}
    for iid in ids:
        row = rows[iid]
        if row['repo'] != 'sphinx-doc/sphinx':
            continue
        version = str(row['version'])
        spec = MAP_REPO_VERSION_TO_SPECS[row['repo']][version]
        records[row['base_commit']] = {'version': version, 'pre_install': spec.get('pre_install', [])}
    policy = {'official_module_sha256': sha(Path(official.__file__)), 'by_base_commit': records}
    path = OUT / 'verified_setup_policy.json'
    if path.exists() and read(path) != policy:
        raise RuntimeError('Official setup policy changed; preserve the frozen run')
    save(path, policy)
    return sha(path)

class LoggedClient:

    def __init__(self, folder, model):
        (self.folder, self.model, self.error) = (folder, model, None)

    def complete_json(self, prompt, **kwargs):
        from skill_dream.llm import _parse_json_lenient
        save(self.folder / 'request.json', {'model': self.model, 'prompt': prompt, 'max_tokens': kwargs['max_tokens'], 'temperature': 'provider-default', 'provider': 'aws_bedrock', 'endpoint': bedrock.ENDPOINT, 'inference_profile': bedrock.profile(self.model)})
        start = time.monotonic()
        try:
            if (self.folder / 'response.json').exists():
                payload = read(self.folder / 'response.json')['response']
            else:
                payload = bedrock.invoke(self.model, prompt, kwargs['max_tokens'])
                save(self.folder / 'response.json', {'response': payload, 'wall_seconds': time.monotonic() - start})
            if payload['model'] != self.model:
                raise RuntimeError('Returned model differs from requested model')
            text = ''.join((b['text'] for b in payload['content'] if b['type'] == 'text'))
            return _parse_json_lenient(text)
        except Exception as exc:
            self.error = exc
            if not (self.folder / 'error.json').exists():
                save(self.folder / 'error.json', {'type': type(exc).__name__, 'status_code': getattr(exc, 'status_code', None), 'wall_seconds': time.monotonic() - start})
            raise

def build(dataset, model, repo):
    import distillation as stages
    from skill_dream.skill_store import Skill
    import surfaces as methods
    if dataset != 'verified' or not model or repo not in VERIFIED_REPOS:
        raise ValueError('Supply a model and one of the Verified repositories')
    manifest = read(OUT / dataset / 'manifest.json')
    source = manifest['sources'][repo]
    assert sha(source['path']) == source['sha256']
    folder = OUT / dataset / model / 'pools' / repo.replace('/', '__')
    if (folder / 'manifest.json').exists():
        data = read(folder / 'manifest.json')
        assert len(data['skills']) == 200
        print('POOL_ALREADY_FROZEN', dataset, model, repo, flush=True)
        return
    (skills, ops) = ({}, [])
    for (index, record) in enumerate(read(source['path'])):
        attempt = folder / 'distillation' / ('%04d_' % index + record['sha'])
        if (attempt / 'skills.json').exists():
            candidates = [Skill(**s) for s in read(attempt / 'skills.json')]
        else:
            if (attempt / 'error.json').exists() and read(attempt / 'error.json')['type'] != 'JSONDecodeError':
                raise RuntimeError('Unresolved distillation interruption: ' + str(attempt))
            files = methods.changed_files_from_patch(record['diff'])
            surfaces = set(methods.surfaces_from_files(files))
            summary = {'pr': record['sha'], 'task_type': 'bugfix', 'surfaces': sorted(surfaces), 'subject': record['subject'][:300]}
            llm = LoggedClient(attempt, model)
            candidates = stages.generate_skills(llm, (record['subject'] + '\n' + record['body'])[:800], summary, [], gold_diff=record['diff'], gold_surfaces=surfaces, model=model)
            if isinstance(llm.error, json.JSONDecodeError):
                save(attempt / 'invalid_response.json', {'reason': 'Invalid JSON; no replacement generation.'})
            elif llm.error is not None:
                raise RuntimeError('Distillation interrupted; preserved response and stopped: ' + type(llm.error).__name__)
            for sk in candidates:
                sk.positive_evidence = [record['sha']]
                sk.version_scope = {'source_id': record['sha'], 'date': record['date'], 'committer_unix': record['committer_unix'], 'repo': repo}
            save(attempt / 'skills.json', [sk.to_dict() for sk in candidates])
        for sk in candidates:
            if not sk.name or not isinstance(sk.trigger, dict) or (not sk.procedure):
                ops.append({'source': record['sha'], 'op': 'INVALID_RECORD'})
                continue
            old = skills.get(sk.name)
            if old:
                sk.positive_evidence = list(dict.fromkeys(old.positive_evidence + sk.positive_evidence))
            ops.append({'source': record['sha'], 'skill': sk.name, 'op': 'UPDATE' if old else 'ADD'})
            skills[sk.name] = sk
            if len(skills) == 200:
                break
        save(folder / 'build_progress.json', {'completed_sources': index + 1, 'active_skills': len(skills), 'model': model, 'repo': repo, 'operations': ops})
        if (index + 1) % 10 == 0 or len(skills) == 200:
            print('DISTILL', dataset, model, repo, index + 1, len(skills), flush=True)
        if len(skills) == 200:
            break
    if len(skills) != 200:
        raise RuntimeError('Source list exhausted before 200 unique valid skills: ' + repo)
    files = {}
    for (name, skill) in skills.items():
        file = folder / 'current' / (hashlib.sha256(name.encode()).hexdigest() + '.json')
        save(file, skill.to_dict())
        files[file.name] = sha(file)
    assert len(list((folder / 'current').glob('*.json'))) == 200
    save(folder / 'manifest.json', {'model': model, 'repo': repo, 'dataset': dataset, 'skills': files, 'source_manifest_sha256': sha(OUT / dataset / 'manifest.json'), 'source_records_sha256': source['sha256'], 'operations': ops, 'retrieval': {'mode': 'a2', 'dense_threshold': 0.28, 'top_k': 8, 'rrf_k': 60}, 'prompt_function': 'distillation.generate_skills', 'prompt_module_sha256': sha(Path(stages.__file__)), 'existing_generation_cache_used': False, 'target_gold_input': False})
    print('POOL_FROZEN', dataset, model, repo, len(skills), flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['prepare', 'build'])
    ap.add_argument('--dataset', choices=['verified'], default='verified')
    ap.add_argument('--model', default=os.environ.get('SD_MODEL'))
    ap.add_argument('--repo')
    args = ap.parse_args()
    if args.action == 'prepare':
        prepare(args.dataset)
    else:
        build(args.dataset, args.model, args.repo)
if __name__ == '__main__':
    main()
