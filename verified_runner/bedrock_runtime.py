import copy
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import quote
REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
ENDPOINT = f'https://bedrock-runtime.{REGION}.amazonaws.com'

def forbid_legacy_proxy(event, args):
    if event == 'socket.connect' and len(args) > 1:
        address = args[1]
        if isinstance(address, tuple) and len(address) > 1 and (address[1] == 18820):
            raise RuntimeError('Legacy proxy connections are prohibited in Bedrock runs')
sys.addaudithook(forbid_legacy_proxy)

def credential():
    key = os.environ.get('AWS_BEARER_TOKEN_BEDROCK', '').strip()
    if key:
        return key
    filename = os.environ.get('SD_BEDROCK_KEY_FILE')
    if not filename:
        raise RuntimeError('Set AWS_BEARER_TOKEN_BEDROCK or SD_BEDROCK_KEY_FILE locally')
    path = Path(filename).expanduser()
    if path.stat().st_mode & 63:
        raise RuntimeError('Bedrock credential file permissions must be 0600')
    key = path.read_text().strip()
    if not key.startswith('ABSK'):
        raise RuntimeError('Missing Bedrock bearer credential')
    return key

def configure():
    key = credential()
    os.environ['AWS_BEARER_TOKEN_BEDROCK'] = key
    os.environ['AWS_REGION_NAME'] = REGION
    os.environ['AWS_DEFAULT_REGION'] = REGION
    os.environ['AWS_EC2_METADATA_DISABLED'] = 'true'
    os.environ['LITELLM_LOG'] = 'ERROR'
    for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_API_BASE', 'ANTHROPIC_BASE_URL', 'OPENAI_API_BASE', 'OPENAI_BASE_URL'):
        os.environ.pop(name, None)
    return key

def profile(model):
    if not model or not isinstance(model, str):
        raise ValueError('A provider model ID is required')
    return os.environ.get('SD_BEDROCK_PROFILE', 'us.anthropic.' + model)

def actor_config(original, model):
    config = copy.deepcopy(original)
    config['model_name'] = 'bedrock/' + profile(model)
    kwargs = config['model_kwargs']
    for name in ('api_key', 'api_base', 'base_url', 'api_version', 'extra_headers'):
        kwargs.pop(name, None)
    kwargs['aws_region_name'] = REGION
    kwargs['aws_bedrock_runtime_endpoint'] = ENDPOINT
    assert '18820' not in json.dumps(config)
    return config

def clean_error(value, key):
    text = str(value).replace(key, '[REDACTED]')
    text = re.sub('arn:aws[^\\s\\"\\\']+', '[REDACTED_ARN]', text)
    return re.sub('\\b\\d{12}\\b', '[REDACTED_ACCOUNT]', text)[:1200]

def invoke(model, prompt, max_tokens):
    key = credential()
    payload = {'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': max_tokens, 'messages': [{'role': 'user', 'content': prompt}]}
    request = urllib.request.Request(ENDPOINT + '/model/' + quote(profile(model), safe='') + '/invoke', data=json.dumps(payload).encode(), method='POST', headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        message = clean_error(exc.read().decode('utf-8', errors='replace'), key)
        raise RuntimeError(f'Bedrock HTTP {exc.code}: {message}') from None
    if payload.get('model') != model:
        raise RuntimeError('Bedrock returned an unexpected model identity')
    return payload

def model_matches(returned, requested):
    return returned in (requested, profile(requested), 'bedrock/' + profile(requested))
