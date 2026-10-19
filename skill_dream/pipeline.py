from __future__ import annotations
import os, json, time, subprocess
from dataclasses import dataclass, field
from typing import Optional
from .llm import LLMClient, TokenMeter, MODEL_MAIN
from .skill_store import SkillStore
from .sandbox import Sandbox
from .leakguard import LeakGuard
from .pr_loader import parse_pr_from_repo, get_diff, PRRecord, localize_base_files
from . import stages
from . import evaluator as ev

@dataclass
class RunConfig:
    repo: str
    workdir: str
    skills_root: str
    python: str
    model: str = MODEL_MAIN
    use_skills: bool = True
    run_existing_tests: bool = True
    test_targets: Optional[list] = None
    ignore_tests: Optional[list] = None
    apply_mode: str = 'robust'

class Pipeline:

    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.meter = TokenMeter()
        self.llm = LLMClient(self.meter)
        self.store = SkillStore(cfg.skills_root)
        self.store.load()
        os.makedirs(cfg.workdir, exist_ok=True)

    def run_pr(self, pr_index_row: dict, pr_history: list, leakguard: LeakGuard) -> dict:
        cfg = self.cfg
        sha = pr_index_row['sha']
        base = pr_index_row['base']
        kind = pr_index_row.get('kind', 'squash')
        task = pr_index_row['subject']
        run_id = f"pr_{pr_index_row['pr']}_{int(time.time())}"
        rundir = os.path.join(cfg.workdir, run_id)
        os.makedirs(rundir, exist_ok=True)
        record = {'pr': pr_index_row['pr'], 'sha': sha, 'base': base, 'task': task, 'run_id': run_id, 'steps': {}}
        gold = parse_pr_from_repo(cfg.repo, sha, base, kind)
        gold_diff = get_diff(cfg.repo, base, sha)
        probed_gold_diff = leakguard.inject(gold_diff)
        record['gold'] = {'files': gold.files, 'surfaces': gold.surfaces, 'symbols': gold.symbols, 'n_files': gold.n_files}
        record['steps']['1_diagnose'] = {'task': task}
        hist = [r for r in pr_history if r['date'] < pr_index_row['date']]
        det = stages.detect_prs(self.llm, task, hist)
        task_type = det.get('task_type', 'feature_addition')
        keywords = det.get('keywords', [])
        record['steps']['2_detect'] = det
        base_files = localize_base_files(cfg.repo, base, task, max_files=6)
        base_ctx_for_synth = stages.build_base_context(cfg.repo, base, base_files, max_files=4)
        leakguard.assert_clean(base_ctx_for_synth, where='synth_base_ctx')
        cands = stages.synthesize_prs(self.llm, task, base_ctx_for_synth, num_candidates=3, leakguard=leakguard)
        record['steps']['3_synthesize'] = {'n_candidates': len(cands), 'candidates': cands}
        (selected, rejected) = stages.verify_and_select(cands, task_type)
        record['steps']['4_5_verify_select'] = {'selected': selected, 'n_rejected': len(rejected)}
        selected_evidence = {'pr': pr_index_row['pr'], 'task_type': task_type, 'surfaces': list(gold.surfaces.keys()), 'plan': selected}
        if cfg.use_skills:
            avail_skills = self.store.retrieve(task_type, keywords, top_k=5, before_date=pr_index_row['date'])
        else:
            avail_skills = []
        gen_base_ctx = stages.build_base_context(cfg.repo, base, base_files, max_files=6)
        leakguard.assert_clean(gen_base_ctx, where='gen_base_ctx')
        gen = stages.generate_patch(self.llm, task, gen_base_ctx, avail_skills, leakguard=leakguard, model=cfg.model)
        record['steps']['8_generate_patch'] = {'skills_used': gen.get('skills_used', []), 'changed_files': gen.get('changed_files', []), 'surfaces_addressed': gen.get('surfaces_addressed', []), 'error': gen.get('error')}
        eval_res = self._evaluate(gold, gen, base, run_id)
        record['steps']['9_evaluate'] = eval_res.to_dict()
        new_skills = stages.generate_skills(self.llm, task, selected_evidence, rejected, gold_diff=gold_diff, gold_surfaces=gold.gold_surfaces())
        for skill in new_skills:
            skill.version_scope.update({'date': pr_index_row['date'], 'source_id': sha, 'base_commit': base})
        record['steps']['6_generate_skills'] = {'n_new_skills': len(new_skills), 'names': [s.name for s in new_skills]}
        ops = stages.decide_skill_ops(self.llm, new_skills, list(self.store.skills.keys()))
        for (op, sk, target) in ops:
            self.store.apply_op(op, sk, target=target, note=f"from PR#{pr_index_row['pr']}")
        for name in gen.get('skills_used', []):
            self.store.update_stats(name, eval_res.task_success)
        self.store.save()
        record['steps']['7_update_skills'] = {'ops': [(o, s.name, t) for (o, s, t) in ops], 'active_skills': len(self.store.skills)}
        record['outcome'] = {'task_success': eval_res.task_success, 'patch_applies_clean': eval_res.patch_applies_clean, 'existing_tests_pass': eval_res.existing_tests_pass, 'surface_f1': eval_res.surface.f1, 'hard_constraints_ok': eval_res.hard_constraints_ok, 'tokens': self.meter.snapshot()}
        record['leakguard'] = leakguard.report()
        with open(os.path.join(rundir, 'record.json'), 'w') as f:
            json.dump(record, f, indent=2)
        return record

    def run_pr_paired(self, pr_index_row: dict, pr_history: list) -> dict:
        cfg = self.cfg
        sha = pr_index_row['sha']
        base = pr_index_row['base']
        kind = pr_index_row.get('kind', 'squash')
        task = pr_index_row['subject']
        leakguard = LeakGuard()
        run_id = f"paired_pr_{pr_index_row['pr']}_{int(time.time())}"
        rundir = os.path.join(cfg.workdir, run_id)
        os.makedirs(rundir, exist_ok=True)
        rec = {'pr': pr_index_row['pr'], 'sha': sha, 'base': base, 'task': task, 'run_id': run_id}
        gold = parse_pr_from_repo(cfg.repo, sha, base, kind)
        gold_diff = get_diff(cfg.repo, base, sha)
        leakguard.inject(gold_diff)
        pr_test_files = [f for f in gold.files if f.startswith('tests/') and f.endswith('.py')]
        rec['gold'] = {'files': gold.files, 'surfaces': gold.surfaces, 'pr_touched_test_files': pr_test_files, 'n_files': gold.n_files}
        hist = [r for r in pr_history if r['date'] < pr_index_row['date']]
        det = stages.detect_prs(self.llm, task, hist)
        task_type = det.get('task_type', 'feature_addition')
        keywords = det.get('keywords', [])
        rec['detect'] = {'task_type': task_type, 'keywords': keywords, 'n_detected': len(det.get('detected', []))}
        base_files = localize_base_files(cfg.repo, base, task, max_files=6)
        gen_base_ctx = stages.build_base_context(cfg.repo, base, base_files, max_files=6)
        leakguard.assert_clean(gen_base_ctx, where='gen_base_ctx')
        avail_skills = self.store.retrieve(task_type, keywords, top_k=5, before_date=pr_index_row['date'])
        rec['skills_available'] = [s.name for s in avail_skills]
        legs = {}
        for (leg_name, skills) in [('skill_guided', avail_skills), ('base_agent', [])]:
            tok0 = self.meter.snapshot()['total_tokens']
            gen = stages.generate_patch(self.llm, task, gen_base_ctx, skills, leakguard=leakguard, model=cfg.model)
            tok1 = self.meter.snapshot()['total_tokens']
            eval_res = self._evaluate_with_ignore(gold, gen, base, f'{run_id}_{leg_name}', ignore_tests=pr_test_files)
            prec = ev.surface_precision_decomp(gold.files, gold.gold_surfaces(), gen.get('changed_files', []))
            legs[leg_name] = {'raw_edits': gen.get('edits', []), 'raw_new_files': list(gen.get('new_files', {}).keys()), 'task_success': eval_res.task_success, 'existing_tests_pass': eval_res.existing_tests_pass, 'cleanly_apply': eval_res.patch_applies_clean, 'surface_f1': round(eval_res.surface.f1, 4), 'surface_precision': round(prec['surface_precision'], 4), 'surface_pred': sorted(eval_res.surface.pred), 'surface_gold': sorted(eval_res.surface.gold), 'changed_files': gen.get('changed_files', []), 'n_files_off_gold_surface': prec['n_files_off_gold_surface'], 'off_gold_files': prec['off_gold_files'], 'off_gold_surfaces': prec['off_gold_surfaces'], 'skills_used': gen.get('skills_used', []), 'tokens': tok1 - tok0, 'pytest': eval_res.detail.get('pytest', {}), 'apply_detail': eval_res.detail.get('apply', {}), 'gen_error': gen.get('error')}
        rec['legs'] = legs
        rec['delta'] = {'task_success': int(legs['skill_guided']['task_success']) - int(legs['base_agent']['task_success']), 'surface_f1': round(legs['skill_guided']['surface_f1'] - legs['base_agent']['surface_f1'], 4), 'existing_tests_pass': int(legs['skill_guided']['existing_tests_pass']) - int(legs['base_agent']['existing_tests_pass'])}
        rec['leakguard'] = leakguard.report()
        selected_evidence = {'pr': pr_index_row['pr'], 'task_type': task_type, 'surfaces': list(gold.surfaces.keys())}
        new_skills = stages.generate_skills(self.llm, task, selected_evidence, [], gold_diff=gold_diff, gold_surfaces=gold.gold_surfaces())
        for skill in new_skills:
            skill.version_scope.update({'date': pr_index_row['date'], 'source_id': sha, 'base_commit': base})
        ops = stages.decide_skill_ops(self.llm, new_skills, list(self.store.skills.keys()))
        for (op, sk, target) in ops:
            self.store.apply_op(op, sk, target=target, note=f"from PR#{pr_index_row['pr']}")
        self.store.save()
        rec['skill_update'] = {'n_new': len(new_skills), 'names': [s.name for s in new_skills], 'active_skills': len(self.store.skills)}
        with open(os.path.join(rundir, 'record.json'), 'w') as f:
            json.dump(rec, f, indent=2)
        return rec

    def _evaluate_with_ignore(self, gold, gen, base, run_id, ignore_tests):
        saved = self.cfg.ignore_tests
        saved_t = self.cfg.test_targets
        self.cfg.ignore_tests = ignore_tests
        self.cfg.test_targets = ['tests/']
        try:
            return self._evaluate(gold, gen, base, run_id)
        finally:
            self.cfg.ignore_tests = saved
            self.cfg.test_targets = saved_t

    def _evaluate(self, gold: PRRecord, gen: dict, base: str, run_id: str) -> ev.EvalResult:
        cfg = self.cfg
        sb_root = os.path.join(cfg.workdir, '_sandboxes')
        sb = Sandbox(cfg.repo, base, sb_root, f'eval_{run_id}')
        applies_clean = False
        existing_pass = False
        detail = {}
        try:
            sb.create()
            if cfg.apply_mode == 'robust':
                from .apply_robust import apply_edits_robust
                ap = apply_edits_robust(sb, gen.get('edits', []), gen.get('new_files', {}))
                applies_clean = ap['clean']
            else:
                ap = stages.apply_edits_to_sandbox(sb, gen.get('edits', []), gen.get('new_files', {}))
                applies_clean = bool(ap['applied']) and (not ap['failed'])
            detail['apply'] = ap
            import subprocess
            gen_diff = subprocess.run(['git', '-C', sb.path, 'diff'], capture_output=True, text=True).stdout
            detail['gen_diff_size'] = len(gen_diff)
            if cfg.run_existing_tests and applies_clean:
                (inst_ok, inst_msg) = sb.pip_install_e(cfg.python)
                detail['install_ok'] = inst_ok
                tr = sb.run_pytest(cfg.python, targets=cfg.test_targets, ignore=cfg.ignore_tests, timeout=900)
                existing_pass = tr.ok
                detail['pytest'] = {'passed': tr.passed, 'failed': tr.failed, 'errors': tr.errors, 'collected': tr.collected}
                detail['pytest_tail'] = tr.raw_tail[-600:]
        except Exception as e:
            detail['eval_error'] = str(e)
        finally:
            sb.destroy()
        surface = ev.surface_f1(gold.gold_surfaces(), gen.get('changed_files', []))
        loc = ev.file_localization(gold.files, gen.get('changed_files', []))
        task_success = applies_clean and existing_pass
        hard_ok = existing_pass
        return ev.EvalResult(patch_applies_clean=applies_clean, existing_tests_pass=existing_pass, gold_tests_pass=False, surface=surface, localization=loc, task_success=task_success, hard_constraints_ok=hard_ok, detail=detail)
