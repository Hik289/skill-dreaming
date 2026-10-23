from __future__ import annotations
import json, os, time, hashlib, tempfile, uuid
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone

@dataclass
class Skill:
    name: str
    trigger: dict
    procedure: list
    negative_constraints: list = field(default_factory=list)
    required_surfaces: list = field(default_factory=list)
    validation: list = field(default_factory=list)
    positive_evidence: list = field(default_factory=list)
    negative_evidence: list = field(default_factory=list)
    review_evidence: list = field(default_factory=list)
    version_scope: dict = field(default_factory=dict)
    confidence: float = 0.5
    relations: dict = field(default_factory=dict)
    category: str = 'feature-implementation'
    created_at: str = ''
    updated_at: str = ''
    stats: dict = field(default_factory=lambda : {'used': 0, 'success': 0, 'fail': 0})

    def __post_init__(self):
        import math
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('skill name must be nonempty')
        if not isinstance(self.trigger, dict) or not isinstance(self.procedure, list):
            raise ValueError('skill trigger and procedure must be structured records')
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError('skill confidence must be finite and between zero and one')

    def to_dict(self):
        return asdict(self)

class SkillStore:

    def __init__(self, root: str, max_active: Optional[int]=None):
        if max_active is not None and max_active < 1:
            raise ValueError('max_active must be positive')
        self.root = root
        self.max_active = max_active
        self.metadata_path = os.path.join(root, 'pool.json')
        self.current_dir = os.path.join(root, 'current')
        self.history_dir = os.path.join(root, 'history')
        os.makedirs(self.current_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)
        self.skills: dict = {}
        self.log: list = []

    def load(self):
        self.skills.clear()
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path) as f:
                metadata = json.load(f)
            self.log = metadata.get('operations', [])
            if self.max_active is None:
                self.max_active = metadata.get('max_active')
        for fn in sorted(os.listdir(self.current_dir)):
            if fn.endswith('.json'):
                with open(os.path.join(self.current_dir, fn)) as f:
                    d = json.load(f)
                self.skills[d['name']] = Skill(**d)
        return self

    def save(self):
        self.maintain_pool()
        filenames = {_fname(name) for name in self.skills}
        for name, sk in self.skills.items():
            _atomic_json(os.path.join(self.current_dir, _fname(name)), sk.to_dict())
        for fn in os.listdir(self.current_dir):
            if fn.endswith('.json') and fn not in filenames:
                os.remove(os.path.join(self.current_dir, fn))
        _atomic_json(self.metadata_path, {'max_active': self.max_active, 'operations': self.log})

    def apply_op(self, op: str, skill: Skill, target: Optional[str]=None, note: str=''):
        op = op.upper()
        if not skill.name.strip():
            raise ValueError('skill name must not be empty')
        if op == 'ADD' and skill.name in self.skills:
            op = 'UPDATE'
        if op in {'SPECIALIZE', 'EXTEND', 'CONFLICT', 'SUPERSEDE'}:
            if not target or target not in self.skills or target == skill.name:
                raise ValueError('relation operation requires a distinct active target')
        now = _now()
        entry = {'op': op, 'skill': skill.name, 'target': target, 'note': note, 'ts': now}
        if op == 'ADD':
            skill.created_at = skill.created_at or now
            skill.updated_at = now
            self.skills[skill.name] = skill
        elif op == 'UPDATE':
            if skill.name in self.skills:
                old = self.skills[skill.name]
                self._archive(old)
                skill.created_at = old.created_at
                skill.positive_evidence = _union(old.positive_evidence, skill.positive_evidence)
                skill.negative_evidence = _union(old.negative_evidence, skill.negative_evidence)
                skill.review_evidence = _union(old.review_evidence, skill.review_evidence)
                skill.relations = {**old.relations, **skill.relations}
                skill.stats = dict(old.stats)
            skill.updated_at = now
            self.skills[skill.name] = skill
        elif op == 'SPECIALIZE':
            skill.relations.setdefault('specializes', target)
            skill.created_at = skill.created_at or now
            skill.updated_at = now
            self.skills[skill.name] = skill
        elif op == 'EXTEND':
            skill.relations.setdefault('extends', target)
            skill.created_at = skill.created_at or now
            skill.updated_at = now
            self.skills[skill.name] = skill
        elif op == 'CONFLICT':
            skill.relations['conflicts_with'] = _union(_names(skill.relations.get('conflicts_with')), [target])
            other = self.skills[target]
            other.relations['conflicts_with'] = _union(_names(other.relations.get('conflicts_with')), [skill.name])
            if skill.name in self.skills:
                self._archive(self.skills[skill.name])
            skill.created_at = skill.created_at or now
            skill.updated_at = now
            self.skills[skill.name] = skill
        elif op == 'SUPERSEDE':
            if target and target in self.skills:
                self.archive(target, reason='superseded', replacement=skill.name)
            skill.relations.setdefault('supersedes', target)
            skill.created_at = skill.created_at or now
            skill.updated_at = now
            self.skills[skill.name] = skill
        elif op == 'KEEP':
            pass
        else:
            raise ValueError(f'unknown op {op}')
        self.log.append(entry)

    def _archive(self, sk: Skill):
        fn = os.path.join(self.history_dir, f'{_fname(sk.name)}.{uuid.uuid4().hex}.json')
        _atomic_json(fn, sk.to_dict())

    def archive(self, name, reason='capacity', replacement=None):
        sk = self.skills.pop(name)
        self._archive(sk)
        self.log.append({'op': 'ARCHIVE', 'skill': name, 'reason': reason,
                         'replacement': replacement, 'ts': _now()})

    def maintain_pool(self, max_active=None):
        limit = self.max_active if max_active is None else max_active
        if limit is None:
            return []
        if limit < 1:
            raise ValueError('max_active must be positive')
        self.max_active = limit
        def utility(sk):
            successes = sk.stats.get('success', 0)
            failures = sk.stats.get('fail', 0)
            reliability = (successes + 1) / (successes + failures + 2)
            return (sk.confidence + reliability, sk.stats.get('used', 0),
                    sk.version_scope.get('date', ''), sk.name)
        excess = max(0, len(self.skills) - limit)
        removed = [sk.name for sk in sorted(self.skills.values(), key=utility)[:excess]]
        for name in removed:
            self.archive(name, reason='capacity')
        return removed

    def retrieve(self, task_type: str, keywords: list, top_k: int=5, before_date: Optional[str]=None, min_relevance: float=0.5, *, query=None, mode='lexical', repo=None, base_ref=None, exclude_sources=(), embed=None, min_cos=0.2) -> list:
        from .skill_context import eligible, compatible_subset
        if top_k < 0 or mode not in {'lexical', 'dense', 'hybrid'}:
            raise ValueError('invalid retrieval configuration')
        if top_k == 0:
            return []
        kws = set((w.lower() for w in keywords if len(w) >= 3))
        scored = []
        cutoff = _timestamp(before_date) if before_date else None
        if before_date and cutoff is None:
            raise ValueError('before_date must be an ISO date or timestamp')
        candidates = [sk for sk in self.skills.values() if eligible(sk, before_date, exclude_sources, repo, base_ref)]
        dense_scores = {}
        if mode in {'dense', 'hybrid'} and candidates:
            from .embedding import embed_batch, cosine
            vectors = (embed or embed_batch)([query or ' '.join(keywords)] + [self._skill_text(sk) for sk in candidates])
            if len(vectors) != len(candidates) + 1:
                raise ValueError('embedding response count mismatch')
            dense_scores = {sk.name: cosine(vectors[0], vector) for sk, vector in zip(candidates, vectors[1:])}
        for sk in candidates:
            hay = self._skill_text(sk)
            rel = sum((1 for w in kws if w in hay))
            tt_bonus = 1.0 if sk.trigger.get('task_type') == task_type else 0.0
            dense = dense_scores.get(sk.name, -1)
            if mode == 'dense' and dense < min_cos:
                continue
            if mode != 'dense' and rel == 0 and tt_bonus == 0 and dense < min_cos:
                continue
            score = rel * 1.0 + tt_bonus + sk.confidence * 0.5
            if sk.stats.get('fail', 0) > sk.stats.get('success', 0) + 1:
                score -= 1.0
            if mode == 'dense':
                score = dense
            elif mode == 'hybrid':
                score = 0.5 * score / (1 + abs(score)) + 0.5 * max(0, dense)
            scored.append((score, rel, sk))
        if mode == 'lexical':
            scored = [(s, r, sk) for (s, r, sk) in scored if r >= 1 or s >= 1.0 + min_relevance]
        scored.sort(key=lambda x: (-x[0], x[2].name))
        return compatible_subset([sk for _, _, sk in scored], top_k)

    @staticmethod
    def _skill_text(sk) -> str:
        parts = [sk.name.replace('-', ' ')]
        parts += sk.trigger.get('keywords', [])
        parts += sk.trigger.get('repository_surfaces', [])
        parts += sk.procedure
        parts += sk.required_surfaces
        parts.append(sk.category)
        return ' '.join((str(p) for p in parts)).lower()

    def update_stats(self, name: str, success: bool):
        if name in self.skills:
            st = self.skills[name].stats
            st['used'] = st.get('used', 0) + 1
            key = 'success' if success else 'fail'
            st[key] = st.get(key, 0) + 1

    def snapshot(self) -> dict:
        return {'active_skills': len(self.skills), 'max_active': self.max_active, 'skills': [s.to_dict() for s in self.skills.values()], 'ops_log': self.log}

def _fname(name: str) -> str:
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)[:100]
    return safe + '-' + hashlib.sha256(name.encode()).hexdigest()[:12] + '.json'

def _names(value):
    return [value] if isinstance(value, str) else list(value or [])

def _atomic_json(path, data):
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.pending-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')

def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        value = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _union(a, b):
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out
