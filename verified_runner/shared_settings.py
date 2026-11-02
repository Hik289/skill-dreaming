import copy
import hashlib
import json
from pathlib import Path
import bedrock_runtime as bedrock
ROOT = Path(__file__).resolve().parent

def load(name):
    folder = ROOT / 'settings'
    path = folder / name
    return json.loads(path.read_text())

def fingerprint():
    files = {name: hashlib.sha256((ROOT / 'settings' / name).read_bytes()).hexdigest()
             for name in ('actor_config.json', 'actor_config_ours.json', 'retrieval.json')}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()

def config(dataset, model, arm='base'):
    if dataset != 'verified':
        raise ValueError('This runner is Verified-only')
    if arm not in ('base', 'ours'):
        raise ValueError('Unknown arm')
    name = 'actor_config.json' if arm == 'base' else 'actor_config_ours.json'
    result = copy.deepcopy(load(name))
    result['model'] = bedrock.actor_config(result['model'], model)
    result['environment']['cwd'] = '/testbed'
    return result

def check(actual, dataset, model, arm='base'):
    if actual != config(dataset, model, arm):
        raise RuntimeError('Run settings differ from the frozen historical arm: ' + arm)

def retrieval():
    return load('retrieval.json')
