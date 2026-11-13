from __future__ import annotations

import math
import re
from collections import Counter

from .skill_store import _timestamp


SUFFIXES = ('.py', '.rst', '.md', '.yml', '.yaml', '.toml', '.json', '.ini', '.cfg')
GENERIC = {'code', 'docs', 'file', 'module', 'option', 'test', 'tests', 'value',
           'python', 'error', 'config', 'feature', 'import'}
STOPWORDS = GENERIC | {'add', 'change', 'fix', 'new', 'the', 'with', 'from', 'into',
                       'for', 'and', 'use', 'using', 'repo', 'repository', 'support'}


def canonical_identifiers(value):
    return {re.sub(r'[^a-z0-9]', '', item.lower()) for item in
            re.findall(r'[A-Za-z][A-Za-z0-9_.-]*', str(value))}


def terms(value):
    result = set()
    for raw in re.findall(r'[A-Za-z][A-Za-z0-9_]*', str(value)):
        parts = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', raw).replace('_', ' ').split()
        result.update(part.lower() for part in [raw, *parts]
                      if len(part) >= 3 and part.lower() not in STOPWORDS)
    return result


def issue_anchors(query):
    text = str(query)[:1800]
    anchors = {}
    for value in re.findall(r'`([^`\n]{3,120})`', text):
        value = value.strip().lower()
        if value not in GENERIC:
            anchors[value] = max(anchors.get(value, 0),
                                 3 if '/' in value or value.endswith(SUFFIXES) else 1)
    for value in re.findall(r'\b[A-Za-z0-9_./-]+\.(?:py|rst|md|yml|yaml|toml|json)\b', text):
        value = value.lower()
        anchors[value] = max(anchors.get(value, 0), 3)
    for value in re.findall(r'\b(?:[A-Z][a-z]+[A-Z][A-Za-z0-9]*|[A-Za-z]+_[A-Za-z0-9_]+)\b', text[:700]):
        value = value.lower()
        if value not in GENERIC:
            anchors[value] = max(anchors.get(value, 0), 2)
    for value in re.findall(r'\b[A-Z]{2,}(?:-[A-Z]{2,})+\b', text[:400]):
        anchors[value.lower().replace('-', '')] = 2
    return anchors


def anchor_score_pr(record, anchors):
    files = ' '.join(map(str, record.get('files', []))).lower()
    description = (str(record.get('subject', '')) + ' ' +
                   str(record.get('body', ''))[:500]).lower()
    identifiers = canonical_identifiers(files + ' ' + description)
    score = 0
    for anchor, weight in anchors.items():
        basename = anchor.rsplit('/', 1)[-1]
        if anchor in files or (weight >= 3 and basename in files):
            score += weight
        elif anchor in description or re.sub(r'[^a-z0-9]', '', anchor) in identifiers:
            score += max(1, weight - 1)
    return score


def _bm25(documents, query):
    docs = [re.findall(r'[a-z][a-z0-9_]+', str(doc).lower()) for doc in documents]
    words = re.findall(r'[a-z][a-z0-9_]+', str(query).lower())
    count = len(docs)
    average = sum(map(len, docs)) / max(count, 1)
    frequency = Counter(word for doc in docs for word in set(doc))
    scores = []
    for doc in docs:
        term_frequency = Counter(doc)
        score = 0.0
        for word in words:
            occurrences = term_frequency[word]
            if occurrences:
                inverse = math.log1p((count - frequency[word] + 0.5) /
                                     (frequency[word] + 0.5))
                score += inverse * 2.5 * occurrences / (
                    occurrences + 1.5 * (0.25 + 0.75 * len(doc) / max(average, 1)))
        scores.append(score)
    return scores


def rank_historical_prs(query, records, before_date, exclude_sources=(), limit=None):
    cutoff = _timestamp(before_date)
    if cutoff is None or limit is not None and limit < 0:
        raise ValueError('valid before_date and nonnegative limit required')
    excluded = {str(source) for source in exclude_sources}
    eligible = []
    for record in records:
        date = _timestamp(record.get('date'))
        available = _timestamp(record.get('available_at') or record.get('date'))
        if date is None or available is None or max(date, available) >= cutoff:
            continue
        if str(record.get('sha')) in excluded or str(record.get('pr')) in excluded:
            continue
        eligible.append(record)
    documents = [str(row.get('subject', '')) + ' ' + str(row.get('body', ''))[:500] +
                 ' ' + ' '.join(map(str, row.get('files', [])[:25])) for row in eligible]
    lexical = _bm25(documents, query)
    anchors = issue_anchors(query)
    ranked = sorted(enumerate(eligible), key=lambda item: (
        -anchor_score_pr(item[1], anchors), -lexical[item[0]],
        -_timestamp(item[1]['date']).timestamp(), str(item[1].get('sha', ''))))
    result = [record for _, record in ranked]
    return result if limit is None else result[:limit]


def skill_anchor_score(skill, anchors):
    trigger = skill.trigger or {}
    text = ' '.join([skill.name, *(str(x) for x in trigger.get('keywords', [])),
                     *(str(x) for x in trigger.get('repository_surfaces', []))]).lower()
    identifiers = canonical_identifiers(text)
    return sum(weight for anchor, weight in anchors.items()
               if anchor in text or re.sub(r'[^a-z0-9]', '', anchor) in identifiers or
               weight >= 3 and anchor.rsplit('/', 1)[-1] in text)


def select_bounded_skill_pool(candidates, task_sources, task_queries, capacity,
                              before_date, exclude_sources=()):
    if capacity < 1:
        raise ValueError('capacity must be positive')
    cutoff = _timestamp(before_date)
    if cutoff is None:
        raise ValueError('before_date must be an ISO date or timestamp')
    excluded = {str(source) for source in exclude_sources}
    repos = {skill.version_scope.get('repo') for skill in candidates}
    if len(repos) != 1 or None in repos:
        raise ValueError('build each repository pool from one repository at a time')
    candidates = [skill for skill in candidates
                  if str(skill.version_scope.get('source_id')) not in excluded
                  and (date := _timestamp(skill.version_scope.get('date'))) is not None
                  and (available := _timestamp(skill.version_scope.get('available_at') or
                                                skill.version_scope.get('date'))) is not None
                  and max(date, available) < cutoff]
    ranked = sorted(candidates, key=lambda skill: (
        -skill.confidence, -len(skill.validation), skill.name))
    selected, names, signatures, source_counts, category_counts, pinned = [], set(), set(), Counter(), Counter(), {}
    limits = {'maintenance': math.ceil(capacity * 0.45),
              'constraint': math.ceil(capacity * 0.225), 'implementation': capacity}

    def category(skill):
        value = skill.category.lower()
        if 'maintenance' in value or 'documentation' in value:
            return 'maintenance'
        if 'negative' in value or 'constraint' in value:
            return 'constraint'
        return 'implementation'

    def add(skill, apply_limits, allow_same_trigger=False):
        if len(selected) >= capacity:
            return False
        source = skill.version_scope.get('source_id')
        if not source:
            return False
        trigger = skill.trigger or {}
        signature = (str(trigger.get('task_type', '')).lower(),
                     tuple(sorted(str(x).lower() for x in
                                  (trigger.get('keywords') or []) +
                                  (trigger.get('repository_surfaces') or []))))
        group = category(skill)
        if skill.name in names or signature in signatures and not allow_same_trigger:
            return False
        if apply_limits and (category_counts[group] >= limits[group] or source_counts[source] >= 2):
            return False
        selected.append(skill)
        names.add(skill.name)
        signatures.add(signature)
        source_counts[source] += 1
        category_counts[group] += 1
        return True

    by_source = {}
    for skill in ranked:
        by_source.setdefault(skill.version_scope.get('source_id'), []).append(skill)
    for task_id, sources in sorted(task_sources.items()):
        anchors = issue_anchors(task_queries[task_id])
        choices = [skill for source in sources for skill in by_source.get(source, [])]
        choices.sort(key=lambda skill: (-skill_anchor_score(skill, anchors),
                     -skill.confidence, -len(skill.validation), skill.name))
        for allow_same_trigger in (False, True):
            for skill in choices:
                if add(skill, False, allow_same_trigger):
                    pinned[task_id] = {'skill': skill.name,
                                       'source_id': skill.version_scope['source_id'],
                                       'anchor_score': skill_anchor_score(skill, anchors)}
                    break
            if task_id in pinned:
                break
    for apply_limits in (True, False):
        for skill in ranked:
            add(skill, apply_limits)
        if len(selected) == capacity:
            break
    if len(selected) != capacity:
        raise ValueError('not enough distinct valid skills for the requested capacity')
    return selected, pinned


def rank_anchored_skills(query, skills, top_k):
    if top_k < 0:
        raise ValueError('top_k must be nonnegative')
    title = str(query).splitlines()[0].removeprefix('Title:').strip()
    anchors = issue_anchors(title)
    strong = {anchor for anchor, weight in anchors.items() if weight >= 2}
    title_terms = terms(title)
    query_terms = terms(str(query)[:1800])
    scored = []
    for skill in skills:
        trigger = skill.trigger or {}
        text = ' '.join([skill.name, *(str(x) for x in trigger.get('keywords', [])),
                         *(str(x) for x in trigger.get('repository_surfaces', []))])
        identifiers = canonical_identifiers(text)
        matched = {anchor for anchor in anchors if anchor in text.lower() or
                   re.sub(r'[^a-z0-9]', '', anchor) in identifiers or
                   anchor.rsplit('/', 1)[-1] in text.lower() and anchors[anchor] >= 3}
        if strong and not matched.intersection(strong) or anchors and not matched:
            continue
        skill_terms = terms(text)
        title_hits = title_terms.intersection(skill_terms)
        body_hits = query_terms.intersection(skill_terms)
        if not title_hits and not matched or len(title_hits) < 2 and len(body_hits) < 2:
            continue
        score = 6 * len(matched) + 3 * len(title_hits) + len(body_hits) + skill.confidence
        scored.append((score, skill.name, skill))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [skill for _, _, skill in scored[:top_k]]
