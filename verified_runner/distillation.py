from __future__ import annotations
import json
from skill_dream.llm import LLMClient, MODEL_HEAVY
from skill_dream.skill_store import Skill

def generate_skills(llm: LLMClient, task: str, selected_evidence: dict, rejected_evidence: list, gold_diff: str=None, gold_surfaces: set=None, model: str=None) -> list:
    ev_desc = json.dumps(selected_evidence, ensure_ascii=False)[:1500]
    diff_ctx = ''
    if gold_diff:
        diff_ctx = f'\n\naccepted PR diff (证据, 用于蒸馏 skill, 非复制):\n{gold_diff[:4000]}'
    surf_ctx = f'\ngold maintenance surfaces: {sorted(gold_surfaces)}' if gold_surfaces else ''
    neg_ctx = ''
    if rejected_evidence:
        neg_items = []
        for r in rejected_evidence[:6]:
            if isinstance(r, dict):
                desc = r.get('reason') or r.get('subject') or r.get('body') or json.dumps(r, ensure_ascii=False)[:200]
                neg_items.append(f'- {str(desc)[:250]}')
            else:
                neg_items.append(f'- {str(r)[:250]}')
        if neg_items:
            neg_ctx = '\n\n负向证据 (被拒绝的 PR / 弱候选 / maintainer 否定的做法 —— 务必从中提炼 negative_constraints, 让 skill 明确避免这些):\n' + '\n'.join(neg_items)
    prompt = f"""你在从验证过的 PR 证据中蒸馏可执行的 repository-specific skill。\n不是压缩 diff, 而是提取: 实现决策 / 修改拓扑 / 维护面要求 / 失败模式, 写成可触发可复用的规则。\n{('如果提供了负向证据, 必须把它转成具体的 negative_constraints (不要做 X / 避免 Y), 让未来任务规避这些被拒模式。' if rejected_evidence else '')}\n\n任务类型: {task}\n选中证据: {ev_desc}{surf_ctx}{diff_ctx}{neg_ctx}\n\n产出 1-2 个可执行 skill。只返回 JSON:\n{{"skills": [{{\n  "name": "kebab-case-name",\n  "trigger": {{"task_type": "...", "keywords": ["..."], "repository_surfaces": ["..."]}},\n  "procedure": ["定位 ...", "复用 ...", "增加 ..."],\n  "negative_constraints": ["不要 ..."],\n  "required_surfaces": ["code","tests","changelog"],\n  "validation": ["run existing tests", "..."],\n  "category": "feature-implementation|maintenance-completion|negative-constraints|...",\n  "confidence": 0.6\n}}]}}"""
    try:
        out = llm.complete_json(prompt, role='skill_synth', model=model or MODEL_HEAVY, max_tokens=2048)
        skills = out.get('skills', [])
    except Exception:
        skills = []
    result = []
    for s in skills:
        if 'name' not in s or 'trigger' not in s:
            continue
        result.append(Skill(name=s['name'], trigger=s.get('trigger', {}), procedure=s.get('procedure', []), negative_constraints=s.get('negative_constraints', []), required_surfaces=s.get('required_surfaces', []), validation=s.get('validation', []), category=s.get('category', 'feature-implementation'), confidence=float(s.get('confidence', 0.6)), positive_evidence=[selected_evidence.get('pr')] if selected_evidence.get('pr') else [], negative_evidence=[r.get('pr') if isinstance(r, dict) else None for r in rejected_evidence or [] if isinstance(r, dict) and r.get('pr')]))
    return result
