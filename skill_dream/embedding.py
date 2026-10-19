from __future__ import annotations
import urllib.request, json, time, math, os
_MODEL = os.environ.get('SD_EMBEDDING_MODEL', 'text-embedding-3-small')

def embed_batch(texts, max_retries=5, batch=64):
    if batch < 1 or max_retries < 1:
        raise ValueError('batch and max_retries must be positive')
    if not texts:
        return []
    endpoint = os.environ.get('SD_EMBEDDING_ENDPOINT')
    key = os.environ.get('SD_EMBEDDING_API_KEY')
    if not endpoint or not key:
        raise RuntimeError('Set SD_EMBEDDING_ENDPOINT and SD_EMBEDDING_API_KEY before requesting embeddings')
    out = []
    for i in range(0, len(texts), batch):
        chunk = [t[:8000] if t else ' ' for t in texts[i:i + batch]]
        body = json.dumps({'input': chunk, 'model': _MODEL}).encode()
        last = None
        for a in range(max_retries):
            try:
                req = urllib.request.Request(endpoint, data=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key, 'api-key': key})
                r = urllib.request.urlopen(req, timeout=60)
                d = json.load(r)
                embs = [item['embedding'] for item in sorted(d['data'], key=lambda x: x['index'])]
                out.extend(embs)
                break
            except Exception as e:
                last = e
                time.sleep(min(3 * 2 ** a, 30))
        else:
            raise RuntimeError('Embedding request failed after retries; check provider configuration') from None
    return out

def embed_one(text):
    return embed_batch([text])[0]

def cosine(a, b):
    dot = sum((x * y for (x, y) in zip(a, b)))
    na = math.sqrt(sum((x * x for x in a)))
    nb = math.sqrt(sum((y * y for y in b)))
    return dot / (na * nb) if na and nb else 0.0
