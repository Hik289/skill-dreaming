from __future__ import annotations
import os
from .sandbox import Sandbox
from .pr_loader import get_file_at
from .patch_lineref import apply_lineref_edits

def _apply_model_source_edits(sb, gen, file_lines, exclude_tests=True):
    edits = gen.get('edits', [])
    new_files = gen.get('new_files', {})
    if exclude_tests:
        edits = [e for e in edits if not _is_test(e.get('path', ''))]
        new_files = {k: v for (k, v) in new_files.items() if not _is_test(k)}
    return apply_lineref_edits(sb, edits, new_files, file_lines)

def _is_test(path: str) -> bool:
    p = path.lower()
    return p.startswith('tests/') or '/test' in p or os.path.basename(p).startswith('test_')

def real_gold_tests_pass(repo, base, sha, gold, gen, tag, file_lines, work, py, check_base_floor=True):
    pr_test_files = [f for f in gold.files if f.startswith('tests/') and f.endswith('.py')]
    if not pr_test_files:
        return (None, {'reason': 'no gold test files'})
    gold_test_content = {}
    for tf in pr_test_files:
        c = get_file_at(repo, sha, tf)
        if c is not None:
            gold_test_content[tf] = c
    if not gold_test_content:
        return (None, {'reason': 'gold test files not resolvable at sha'})
    detail = {'pr_test_files': pr_test_files}
    base_floor_fail = None
    if check_base_floor:
        sbf = Sandbox(repo, base, os.path.join(work, '_sb'), tag + '_floor')
        try:
            sbf.create()
            for (tf, c) in gold_test_content.items():
                sbf.write_file(tf, c)
            tr = sbf.run_pytest(py, targets=pr_test_files, timeout=600, pythonpath=os.path.join(sbf.path, 'src'))
            base_floor_fail = tr.failed > 0 or tr.errors > 0
            detail['base_floor'] = {'passed': tr.passed, 'failed': tr.failed, 'errors': tr.errors, 'valid_task': base_floor_fail}
        except Exception as e:
            detail['base_floor_err'] = str(e)
        finally:
            sbf.destroy()
    sb = Sandbox(repo, base, os.path.join(work, '_sb'), tag + '_gold')
    ok = False
    try:
        sb.create()
        ap = _apply_model_source_edits(sb, gen, file_lines, exclude_tests=True)
        detail['source_apply_clean'] = ap['clean']
        detail['source_oor'] = ap['n_out_of_range']
        if not ap['clean'] and (not ap['applied']):
            detail['reason'] = 'model source edits did not apply'
            return (False, detail)
        for (tf, c) in gold_test_content.items():
            sb.write_file(tf, c)
        tr = sb.run_pytest(py, targets=pr_test_files, timeout=600, pythonpath=os.path.join(sb.path, 'src'))
        ok = tr.failed == 0 and tr.errors == 0 and (tr.passed > 0)
        detail['gold_pytest'] = {'passed': tr.passed, 'failed': tr.failed, 'errors': tr.errors}
    except Exception as e:
        detail['err'] = str(e)
    finally:
        sb.destroy()
    return (ok, detail)
