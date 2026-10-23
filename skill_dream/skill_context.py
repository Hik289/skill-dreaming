from __future__ import annotations
import json
from dataclasses import fields
from .skill_store import Skill, _timestamp, _names


def as_skill(record):
    if isinstance(record, Skill):
        return record
    allowed = {f.name for f in fields(Skill)}
    return Skill(**{key: value for key, value in record.items() if key in allowed})


def eligible(record, before_date=None, exclude_sources=(), repo=None, base_ref=None):
    sk = as_skill(record)
    scope = sk.version_scope or {}
    if scope.get('status', 'active') != 'active':
        return False
    if before_date is not None:
        cutoff = _timestamp(before_date)
        if cutoff is None:
            raise ValueError('before_date must be an ISO date or timestamp')
        dates = [_timestamp(scope.get('date') or scope.get('valid_from_date'))]
        if scope.get('available_at'):
            dates.append(_timestamp(scope['available_at']))
        if any(value is None or value >= cutoff for value in dates):
            return False
    sources = [scope.get('source_id'), *scope.get('source_ids', []), *sk.positive_evidence,
               *sk.negative_evidence, *sk.review_evidence]
    ids = {str(value.get('source_id', value.get('pr', ''))) if isinstance(value, dict) else str(value)
           for value in sources if value is not None}
    if ids.intersection(str(value) for value in exclude_sources):
        return False
    if repo and base_ref:
        from .staleness import assess_staleness
        if assess_staleness(repo, base_ref, sk)['stale']:
            return False
    return True


def compatible_subset(records, top_k):
    retired = {name for record in records for name in _names(as_skill(record).relations.get('supersedes'))}
    selected = []
    seen = set()
    for record in records:
        sk = as_skill(record)
        fingerprint = json.dumps([sk.trigger, sk.procedure, sk.negative_constraints,
                                  sk.required_surfaces, sk.validation], sort_keys=True)
        if sk.name in retired or fingerprint in seen:
            continue
        if any(other.name in _names(sk.relations.get('conflicts_with')) or
               sk.name in _names(other.relations.get('conflicts_with')) for other in selected):
            continue
        selected.append(sk)
        seen.add(fingerprint)
        if len(selected) >= top_k:
            break
    return selected if top_k > 0 else []


def pack_skills(records, max_chars=12000):
    if max_chars < 0:
        raise ValueError('max_chars must be nonnegative')
    prefix = '<repository_skills>\nUse only applicable procedures; validate against the current checkout.\n'
    suffix = '\n</repository_skills>'
    chunks = []
    included, omitted = [], []
    size = len(prefix) + len(suffix)
    for sk in compatible_subset(records, len(records)):
        data = {'skill': sk.name, 'trigger': sk.trigger, 'procedure': sk.procedure,
                'avoid': sk.negative_constraints, 'maintenance': sk.required_surfaces,
                'validation': sk.validation}
        chunk = json.dumps(data, ensure_ascii=False) + '\n'
        if size + len(chunk) > max_chars:
            omitted.append(sk.name)
            continue
        chunks.append(chunk)
        included.append(sk)
        size += len(chunk)
    text = prefix + ''.join(chunks) + suffix if chunks else ''
    return text, included, {'included': [sk.name for sk in included], 'omitted_for_budget': omitted,
                            'characters': len(text), 'max_characters': max_chars}
