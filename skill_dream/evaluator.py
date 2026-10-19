from __future__ import annotations
from dataclasses import dataclass, field
from .pr_loader import classify_surface

@dataclass
class SurfaceScore:
    gold: set
    pred: set
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float

    def to_dict(self):
        return {'gold': sorted(self.gold), 'pred': sorted(self.pred), 'tp': self.tp, 'fp': self.fp, 'fn': self.fn, 'precision': round(self.precision, 4), 'recall': round(self.recall, 4), 'f1': round(self.f1, 4)}

def surface_f1(gold_surfaces: set, pred_files: list) -> SurfaceScore:
    pred = set((classify_surface(f) for f in pred_files))
    gold = set(gold_surfaces) - {'other'}
    pred = pred - {'other'}
    tp = len(gold & pred)
    fp = len(pred - gold)
    fn = len(gold - pred)
    precision = tp / (tp + fp) if tp + fp else 1.0 if not gold else 0.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return SurfaceScore(gold=gold, pred=pred, tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)

def file_localization(gold_files: list, pred_files: list) -> dict:
    gold = set(gold_files)
    pred = set(pred_files)
    tp = len(gold & pred)
    return {'gold_files': sorted(gold), 'pred_files': sorted(pred), 'file_recall': tp / len(gold) if gold else 1.0, 'file_precision': tp / len(pred) if pred else 0.0, 'gold_in_pred': tp}

def surface_precision_decomp(gold_files: list, gold_surfaces: set, pred_files: list) -> dict:
    gold_s = set(gold_surfaces) - {'other'}
    gold_f = set(gold_files)
    (in_gold_files, off_gold_files) = ([], [])
    for f in pred_files:
        s = classify_surface(f)
        if s in gold_s or f in gold_f:
            in_gold_files.append(f)
        else:
            off_gold_files.append((f, s))
    pred_s = set((classify_surface(f) for f in pred_files)) - {'other'}
    hit_s = pred_s & gold_s
    return {'surface_precision': len(hit_s) / len(pred_s) if pred_s else 1.0, 'pred_surfaces': sorted(pred_s), 'off_gold_surfaces': sorted(pred_s - gold_s), 'n_files_pred': len(pred_files), 'n_files_in_gold_surface': len(in_gold_files), 'n_files_off_gold_surface': len(off_gold_files), 'off_gold_files': [f'{f}({s})' for (f, s) in off_gold_files]}

def surface_recall_by_type(gold_surfaces: set, pred_files: list) -> dict:
    pred = set((classify_surface(f) for f in pred_files))
    types = ['tests', 'docs', 'changelog', 'config', 'examples', 'code']
    out = {}
    for t in types:
        g = 1 if t in gold_surfaces else 0
        h = 1 if t in gold_surfaces and t in pred else 0
        out[t] = {'gold': g, 'hit': h}
    return out

@dataclass
class EvalResult:
    patch_applies_clean: bool
    existing_tests_pass: bool
    gold_tests_pass: bool
    surface: SurfaceScore
    localization: dict
    task_success: bool
    hard_constraints_ok: bool
    detail: dict = field(default_factory=dict)

    def to_dict(self):
        return {'patch_applies_clean': self.patch_applies_clean, 'existing_tests_pass': self.existing_tests_pass, 'gold_tests_pass': self.gold_tests_pass, 'surface': self.surface.to_dict(), 'localization': self.localization, 'task_success': self.task_success, 'hard_constraints_ok': self.hard_constraints_ok, 'detail': self.detail}
