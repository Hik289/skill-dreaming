from __future__ import annotations
import json, re
from .llm import LLMClient, MODEL_MAIN, MODEL_HEAVY
from .skill_store import Skill
from .pr_loader import get_file_at

def diagnose(llm: LLMClient, repo_summary: str) -> list:
    return [{'note': 'MVP uses replay PR subjects as tasks_t'}]

def detect_prs(llm: LLMClient, task: str, pr_index: list, top_k: int=5) -> dict:
    cand_lines = []
    for r in pr_index[:60]:
        cand_lines.append(f"PR#{r['pr']} [{r.get('intent', '?')}] {r['subject'][:90]}")
    prompt = f'你在为一个代码仓库任务检测相关的历史 PR 证据。\n\n当前任务: {task}\n\n历史 PR 列表 (只含标题, 均早于当前任务):\n{chr(10).join(cand_lines)}\n\n请判断哪些历史 PR 与当前任务相关, 并给每个相关 PR 一个类别。\n只返回 JSON: {{"detected": [{{"pr": <int>, "relevance": <0-1>, "class": "usable|repairable|outdated|irrelevant"}}], "task_type": "<provider_integration|feature_addition|bugfix|refactor|...>", "keywords": ["..."]}}\n最多返回 {top_k} 个最相关的。'
    try:
        out = llm.complete_json(prompt, role='detect', model=MODEL_MAIN, max_tokens=1024)
    except Exception:
        out = {'detected': [], 'task_type': 'feature_addition', 'keywords': task.lower().split()[:6]}
    out.setdefault('detected', [])
    out.setdefault('task_type', 'feature_addition')
    out.setdefault('keywords', [w for w in re.findall('[a-z_]{3,}', task.lower())][:6])
    return out

def synthesize_prs(llm: LLMClient, task: str, base_files_context: str, num_candidates: int=3, leakguard=None) -> list:
    if leakguard is not None:
        leakguard.assert_clean(task + base_files_context, where='synthesize_prs')
    strategies = ['minimal', 'internal-API-first', 'complete-with-tests-and-docs'][:num_candidates]
    prompt = f'你在为一个代码仓库任务合成 {num_candidates} 个不同实现策略的候选 PR 计划。\n⚠️ 你只能看到 base commit 的信息, 不知道真实 PR 的实现。\n\n任务: {task}\n\nbase commit 仓库结构 (节选):\n{base_files_context[:3000]}\n\n对每个策略给出一个候选 PR 计划 (目标文件 / 需要的维护面 / 核心步骤)。\n策略: {strategies}\n只返回 JSON: {{"candidates": [{{"strategy": "...", "target_files": ["..."], "surfaces": ["code","tests",...], "plan": ["step1","step2"]}}]}}'
    try:
        out = llm.complete_json(prompt, role='synthesize', model=MODEL_MAIN, max_tokens=1536)
        return out.get('candidates', [])
    except Exception:
        return [{'strategy': s, 'target_files': [], 'surfaces': ['code'], 'plan': []} for s in strategies]

def verify_and_select(candidates: list, task_type: str) -> tuple:

    def score(c):
        s = len(set(c.get('surfaces', [])) - {'other'})
        if 'tests' in c.get('surfaces', []):
            s += 2
        if 'code' in c.get('surfaces', []):
            s += 1
        s += 0.3 * len(c.get('plan', []))
        return s
    if not candidates:
        return (None, [])
    ranked = sorted(candidates, key=score, reverse=True)
    return (ranked[0], ranked[1:])

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

def decide_skill_ops(llm: LLMClient, new_skills: list, existing_names: list) -> list:
    ops = []
    for sk in new_skills:
        if sk.name in existing_names:
            ops.append(('UPDATE', sk, None))
        else:
            ops.append(('ADD', sk, None))
    return ops

def generate_patch(llm: LLMClient, task: str, base_context: str, skills: list, leakguard=None, model: str=MODEL_MAIN) -> dict:
    skills_text = _render_skills(skills)
    full_context = task + base_context + skills_text
    if leakguard is not None:
        leakguard.assert_clean(full_context, where='generate_patch')
    prompt = f'你是一个 coding agent, 在 skill 引导下完成一个代码仓库任务, 生成完整修改 (代码+测试+文档+changelog 等必要维护面)。\n⚠️ 你只能看到 base commit 的文件内容, 不知道真实 PR 怎么改的。\n\n任务: {task}\n\n可用 repository skills (触发条件匹配当前任务, 请遵循其 procedure 与 negative_constraints):\n{skills_text}\n\nbase commit 相关文件内容:\n{base_context[:9000]}\n\n用 **search/replace** 方式修改已有文件: search 必须是 base 文件里 *逐字符精确* 出现的一段 (含缩进/空行), replace 是替换后的内容。新文件用 new_files。\n只返回 JSON:\n{{"edits": [{{"path": "src/click/...py", "search": "<base 中精确的原文片段>", "replace": "<修改后片段>"}}],\n  "new_files": [{{"path": "tests/test_new.py", "content": "<完整新文件内容>"}}],\n  "surfaces_addressed": ["code","tests","changelog"], "rationale": "..."}}\n注意: search 片段要足够独特 (含上下文行) 以唯一定位; 保持缩进与原文一致。'
    try:
        out = llm.complete_json(prompt, role='patch_gen', model=model, max_tokens=6000)
    except Exception as e:
        return {'edits': [], 'new_files': {}, 'changed_files': [], 'skills_used': [s.name for s in skills], 'error': str(e)}
    edits = [e for e in out.get('edits', []) if e.get('path') and e.get('search') is not None]
    new_files = {}
    for nf in out.get('new_files', []):
        if nf.get('path') and nf.get('content') is not None:
            new_files[nf['path']] = nf['content']
    changed = sorted(set([e['path'] for e in edits]) | set(new_files.keys()))
    return {'edits': edits, 'new_files': new_files, 'changed_files': changed, 'surfaces_addressed': out.get('surfaces_addressed', []), 'skills_used': [s.name for s in skills], 'rationale': out.get('rationale', '')}

def generate_patch_lineref(llm, task: str, base_context_numbered: str, skills: list, leakguard=None, model: str=MODEL_MAIN, seed: int=0) -> dict:
    skills_text = _render_skills(skills)
    full_context = task + base_context_numbered + skills_text
    if leakguard is not None:
        leakguard.assert_clean(full_context, where='generate_patch_lineref')
    prompt = f'你是一个 coding agent, 在 skill 引导下完成一个代码仓库任务, 生成完整修改 (代码+测试+文档+changelog 等必要维护面)。\n⚠️ 你只能看到 base commit 的文件内容 (下方每行带行号), 不知道真实 PR 怎么改的。\n\n任务: {task}\n\n可用 repository skills (触发条件匹配当前任务, 请遵循其 procedure 与 negative_constraints):\n{skills_text}\n\nbase commit 相关文件内容 (行号| 内容):\n{base_context_numbered[:45000]}\n\n用 **行号区间** 指定对已有文件的修改: 每个 edit 给 start_line/end_line (base 文件中要替换的行区间, 1-indexed, 含首尾) 和 replacement (替换这些行的新内容; 空字符串=删除这些行)。\n⚠️ 不要复现原文片段, 只需引用上面显示的行号。新增文件用 new_files。\n同一文件多个 edit 的行区间不能交叠。\n只返回 JSON:\n{{"edits": [{{"path": "src/click/core.py", "start_line": 42, "end_line": 45, "replacement": "    new code line1\\n    new code line2"}}],\n  "new_files": [{{"path": "tests/test_new.py", "content": "<完整新文件内容>"}}],\n  "surfaces_addressed": ["code","tests","changelog"], "rationale": "..."}}'
    try:
        sysmsg = f'You are attempt variant #{seed}. Think independently.' if seed else None
        out = llm.complete_json(prompt, role='patch_gen', model=model, max_tokens=6000, system=sysmsg, temperature=0.0 if seed == 0 else 0.7)
    except Exception as e:
        return {'edits': [], 'new_files': {}, 'changed_files': [], 'skills_used': [s.name for s in skills], 'error': str(e), 'llm_failed': True}
    edits = [e for e in out.get('edits', []) if e.get('path') and e.get('start_line') is not None]
    new_files = {}
    for nf in out.get('new_files', []):
        if nf.get('path') and nf.get('content') is not None:
            new_files[nf['path']] = nf['content']
    changed = sorted(set([e['path'] for e in edits]) | set(new_files.keys()))
    return {'edits': edits, 'new_files': new_files, 'changed_files': changed, 'surfaces_addressed': out.get('surfaces_addressed', []), 'skills_used': [s.name for s in skills], 'rationale': out.get('rationale', '')}

def apply_edits_to_sandbox(sandbox, edits: list, new_files: dict) -> dict:
    (applied, failed) = ([], [])
    for e in edits:
        (path, search, replace) = (e['path'], e['search'], e.get('replace', ''))
        content = sandbox.read_file(path)
        if content is None:
            failed.append({'path': path, 'reason': 'file not found'})
            continue
        if search not in content:
            failed.append({'path': path, 'reason': 'search fragment not found (not clean)'})
            continue
        if content.count(search) > 1:
            failed.append({'path': path, 'reason': 'search fragment ambiguous (>1 match)'})
            continue
        sandbox.write_file(path, content.replace(search, replace, 1))
        applied.append(path)
    for (path, content) in new_files.items():
        sandbox.write_file(path, content)
        applied.append(path)
    return {'applied': applied, 'failed': failed}

def _render_skills(skills: list) -> str:
    if not skills:
        return '(无可用 skill —— base agent 模式)'
    lines = []
    for sk in skills:
        lines.append(f'### skill: {sk.name} (confidence={sk.confidence})')
        lines.append(f'  trigger: {sk.trigger}')
        lines.append(f'  procedure: {sk.procedure}')
        if sk.negative_constraints:
            lines.append(f'  negative_constraints: {sk.negative_constraints}')
        if sk.required_surfaces:
            lines.append(f'  required_surfaces: {sk.required_surfaces}')
    return '\n'.join(lines)

def build_base_context(repo: str, base: str, hint_files: list, max_files: int=6) -> str:
    parts = []
    for f in hint_files[:max_files]:
        content = get_file_at(repo, base, f)
        if content:
            parts.append(f'=== FILE: {f} ===\n{content[:4000]}')
    if not parts:
        import subprocess
        tree = subprocess.run(['git', '-C', repo, 'ls-tree', '-r', '--name-only', base], capture_output=True, text=True).stdout
        parts.append('=== REPO FILE TREE (base) ===\n' + '\n'.join(tree.splitlines()[:200]))
    return '\n\n'.join(parts)

def files_to_diff(repo, base, files_dict, sandbox):
    for (path, content) in files_dict.items():
        sandbox.write_file(path, content)
    import subprocess
    out = subprocess.run(['git', '-C', sandbox.path, 'diff'], capture_output=True, text=True)
    return out.stdout
