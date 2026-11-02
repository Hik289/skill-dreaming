import math
import re
import hashlib
import json
import os
from pathlib import Path
from skill_dream import embedding as EMB

def emb_cached(text):
    text = text[:8000]
    namespace = (os.environ.get('SD_EMBEDDING_ENDPOINT', ''), os.environ.get('SD_EMBEDDING_MODEL', ''))
    key = hashlib.sha256(json.dumps([namespace, text]).encode()).hexdigest()
    folder = Path(os.environ.get('SD_VERIFIED_ROOT', 'workspace/verified')) / 'embedding_cache'
    path = folder / (key + '.json')
    if path.exists():
        return json.loads(path.read_text())
    vector = EMB.embed_one(text)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(vector))
    return vector

def skill_text(sk):
    parts = [sk.name.replace('-', ' ')]
    if isinstance(sk.trigger, dict):
        parts += [str(x) for x in sk.trigger.get('keywords', [])]
        parts.append(str(sk.trigger.get('task_type', '')))
        parts += [str(x) for x in sk.trigger.get('repository_surfaces', [])]
    parts += [str(s) for s in sk.procedure or []]
    parts.append(getattr(sk, 'category', ''))
    return ' '.join(parts)

def render_skill(sk, idx=None):
    head = f'Skill {idx}: {sk.name}' if idx is not None else f'Skill: {sk.name}'
    out = [head]
    if isinstance(sk.trigger, dict):
        kw = sk.trigger.get('keywords', [])
        ts = sk.trigger.get('task_type', '')
        hint = ', '.join([x for x in [ts] + (kw if isinstance(kw, list) else [])][:6])
        if hint:
            out.append(f'  Applies when: {hint}')
    out.append(f'  Approach: {sk.procedure}')
    if sk.negative_constraints:
        out.append(f'  Pitfall to avoid: {sk.negative_constraints}')
    return '\n'.join(out)

def tokenize(t):
    return re.findall('[A-Za-z_][A-Za-z0-9_]{1,}', (t or '').lower())

class BM25:

    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = [tokenize(d) for d in docs]
        self.k1 = k1
        self.b = b
        self.N = len(self.docs)
        self.avgdl = sum((len(d) for d in self.docs)) / max(self.N, 1)
        self.df = {}
        for d in self.docs:
            for w in set(d):
                self.df[w] = self.df.get(w, 0) + 1
        self.idf = {w: math.log(1 + (self.N - f + 0.5) / (f + 0.5)) for (w, f) in self.df.items()}

    def score(self, query):
        q = tokenize(query)
        out = []
        for d in self.docs:
            if not d:
                out.append(0.0)
                continue
            tf = {}
            for w in d:
                tf[w] = tf.get(w, 0) + 1
            s = 0.0
            for w in q:
                if w in tf:
                    idf = self.idf.get(w, 0)
                    f = tf[w]
                    s += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl))
            out.append(s)
        return out

def retrieve(issue_text, skills, mode, model, tau=0.28, topk=8):
    if not skills:
        return ([], {})
    if mode == 'none':
        return ([], {'mode': 'none'})
    if mode != 'a2':
        raise ValueError('This protocol uses a2 retrieval or none')
    q = emb_cached(issue_text)
    texts = [skill_text(s) for s in skills]
    vecs = [emb_cached(t) for t in texts]
    dense = [(EMB.cosine(q, vecs[i]), i) for i in range(len(skills))]
    meta = {'mode': mode}
    if mode == 'a2':
        bm = BM25(texts)
        bs = bm.score(issue_text)
        dense_rank = sorted(range(len(skills)), key=lambda i: dense[i][0], reverse=True)
        bm_rank = sorted(range(len(skills)), key=lambda i: bs[i], reverse=True)
        K = 60
        rrf = {}
        for (r, i) in enumerate(dense_rank):
            rrf[i] = rrf.get(i, 0) + 1.0 / (K + r + 1)
        for (r, i) in enumerate(bm_rank):
            rrf[i] = rrf.get(i, 0) + 1.0 / (K + r + 1)
        order = sorted(rrf, key=lambda i: rrf[i], reverse=True)
        cand = [i for i in order if dense[i][0] >= tau][:topk] or order[:topk]
        sel = [skills[i] for i in cand]
        meta['n_pre'] = len(skills)
        meta['n_sel'] = len(sel)
        return (sel, meta)
