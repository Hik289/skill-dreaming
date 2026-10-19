from __future__ import annotations
import json, os, time
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

    def to_dict(self):
        return asdict(self)

class SkillStore:

    def __init__(self, root: str):
        self.root = root
        self.current_dir = os.path.join(root, 'current')
        self.history_dir = os.path.join(root, 'history')
        os.makedirs(self.current_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)
        self.skills: dict = {}
        self.log: list = []

    def load(self):
        self.skills.clear()
        for fn in os.listdir(self.current_dir):
            if fn.endswith('.json'):
                with open(os.path.join(self.current_dir, fn)) as f:
                    d = json.load(f)
                self.skills[d['name']] = Skill(**d)
        return self

    def save(self):
        for fn in os.listdir(self.current_dir):
            if fn.endswith('.json'):
                os.remove(os.path.join(self.current_dir, fn))
        for (name, sk) in self.skills.items():
            with open(os.path.join(self.current_dir, _fname(name)), 'w') as f:
                json.dump(sk.to_dict(), f, indent=2)

    def apply_op(self, op: str, skill: Skill, target: Optional[str]=None, note: str=''):
        op = op.upper()
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
                skill.stats = old.stats
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
            if skill.name in self.skills:
                self.skills[skill.name].relations.setdefault('conflicts_with', target)
        elif op == 'SUPERSEDE':
            if target and target in self.skills:
                self._archive(self.skills.pop(target))
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
        fn = os.path.join(self.history_dir, f'{_fname(sk.name)}.{int(time.time() * 1000)}.json')
        with open(fn, 'w') as f:
            json.dump(sk.to_dict(), f, indent=2)

    def retrieve(self, task_type: str, keywords: list, top_k: int=5, before_date: Optional[str]=None, min_relevance: float=0.5) -> list:
        kws = set((w.lower() for w in keywords if len(w) >= 3))
        scored = []
        cutoff = _timestamp(before_date) if before_date else None
        if before_date and cutoff is None:
            raise ValueError('before_date must be an ISO date or timestamp')
        for sk in self.skills.values():
            if cutoff is not None:
                scope = sk.version_scope or {}
                dates = [_timestamp(scope.get('date'))]
                if scope.get('available_at'):
                    dates.append(_timestamp(scope['available_at']))
                if any(date is None or date >= cutoff for date in dates):
                    continue
            hay = self._skill_text(sk)
            rel = sum((1 for w in kws if w in hay))
            tt_bonus = 1.0 if sk.trigger.get('task_type') == task_type else 0.0
            if rel == 0 and tt_bonus == 0:
                continue
            score = rel * 1.0 + tt_bonus + sk.confidence * 0.5
            if sk.stats.get('fail', 0) > sk.stats.get('success', 0) + 1:
                score -= 1.0
            scored.append((score, rel, sk))
        scored = [(s, r, sk) for (s, r, sk) in scored if r >= 1 or s >= 1.0 + min_relevance]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [sk for (s, r, sk) in scored[:top_k]]

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
            st['used'] += 1
            st['success' if success else 'fail'] += 1

    def snapshot(self) -> dict:
        return {'active_skills': len(self.skills), 'skills': [s.to_dict() for s in self.skills.values()], 'ops_log': self.log}

def _fname(name: str) -> str:
    return ''.join((c if c.isalnum() or c in '-_' else '_' for c in name)) + '.json' if not name.endswith('.json') else name.replace('.json', '') + '.json'

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
