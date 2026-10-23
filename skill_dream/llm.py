from __future__ import annotations
import json, time, os
from dataclasses import dataclass, field
from typing import Optional
MAX_RETRIES = 6
MODEL_MAIN = os.environ.get('SD_MODEL') or ''
MODEL_HEAVY = os.environ.get('SD_MODEL_HEAVY') or MODEL_MAIN
MODEL_CHEAP = os.environ.get('SD_MODEL_CHEAP') or MODEL_MAIN

class RateLimitExhausted(RuntimeError):
    pass

@dataclass
class TokenMeter:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    by_role: dict = field(default_factory=dict)

    def add(self, role: str, itok: int, otok: int):
        self.input_tokens += itok
        self.output_tokens += otok
        self.calls += 1
        r = self.by_role.setdefault(role, {'in': 0, 'out': 0, 'calls': 0})
        r['in'] += itok
        r['out'] += otok
        r['calls'] += 1

    def snapshot(self):
        return {'input_tokens': self.input_tokens, 'output_tokens': self.output_tokens, 'total_tokens': self.input_tokens + self.output_tokens, 'calls': self.calls, 'by_role': {role: dict(values) for role, values in self.by_role.items()}}

class LLMClient:

    def __init__(self, meter: Optional[TokenMeter]=None):
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise RuntimeError('Set ANTHROPIC_API_KEY before making model calls')
        from anthropic import Anthropic
        options = {'api_key': api_key, 'max_retries': MAX_RETRIES}
        base_url = os.environ.get('ANTHROPIC_BASE_URL')
        if base_url:
            options['base_url'] = base_url
        self._client = Anthropic(**options)
        self.meter = meter or TokenMeter()

    def complete(self, prompt: str, *, role: str='generic', model: str=MODEL_MAIN, max_tokens: int=2048, system: Optional[str]=None, temperature: float=0.0) -> str:
        model = model or os.environ.get('SD_MODEL', '')
        if not model:
            raise RuntimeError('Set SD_MODEL before making model calls')
        kwargs = dict(model=model, max_tokens=max_tokens, messages=[{'role': 'user', 'content': prompt}])
        if system:
            kwargs['system'] = system
        if os.environ.get('SD_SEND_TEMPERATURE', '1') != '0':
            kwargs['temperature'] = temperature
        kwargs['timeout'] = 120.0
        last_err = None
        for attempt in range(10):
            try:
                r = self._client.messages.create(**kwargs)
                itok = getattr(r.usage, 'input_tokens', 0) or 0
                otok = getattr(r.usage, 'output_tokens', 0) or 0
                self.meter.add(role, itok, otok)
                parts = [b.text for b in r.content if getattr(b, 'type', None) == 'text']
                return ''.join(parts).strip()
            except Exception as e:
                last_err = e
                time.sleep(min(6 * 2 ** attempt, 120))
        if getattr(last_err, 'status_code', None) == 429:
            raise RateLimitExhausted('Model rate limit exhausted after retries') from None
        raise RuntimeError('Model call failed after retries; check provider configuration') from None

    def complete_json(self, prompt: str, **kw) -> dict:
        txt = self.complete(prompt, **kw)
        return _parse_json_lenient(txt)

def _parse_json_lenient(txt: str) -> dict:
    t = txt.strip()
    if t.startswith('```'):
        lines = t.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        t = '\n'.join(lines).strip()
    dec = json.JSONDecoder()
    i = t.find('{')
    if i >= 0:
        try:
            (obj, _) = dec.raw_decode(t[i:])
            return obj
        except Exception:
            pass
    try:
        return json.loads(t)
    except Exception:
        k = t.find('[')
        if k >= 0:
            try:
                (arr, _) = dec.raw_decode(t[k:])
                return {'_list': arr}
            except Exception:
                pass
        raise
