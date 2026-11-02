from pathlib import Path
import shutil
import sys
from experiment_verified_v4 import driver
original_pair = driver.pair
original_summarize = driver.summarize

def pair(iid):
    if shutil.disk_usage(driver.RUN).free < 12 * 1024 ** 3:
        raise RuntimeError('Insufficient output-volume space; preserved results are unchanged')
    return original_pair(iid)

def summarize():
    original_summarize()
    ledger_path = driver.RUN / 'user_interrupted_attempts.json'
    if not ledger_path.exists():
        return
    ledger = driver.read(ledger_path)
    summary = driver.read(driver.RUN / 'summary.json')
    summary['user_interrupted_attempts'] = ledger
    totals = {}
    for arm in ('base', 'ours'):
        totals[arm] = dict(summary['actor_accounting'][arm]['usage_fields'])
        for attempt in ledger['attempts']:
            if attempt['arm'] != arm:
                continue
            for (field, value) in attempt['usage_fields'].items():
                totals[arm][field] = totals[arm].get(field, 0) + value
    summary['usage_including_archived_user_interruptions'] = totals
    summary['interruption_accounting_scope'] = 'Includes all recorded responses in the archived unfinished attempts. Requests interrupted before a response was persisted may not be measurable. No submitted answer or scored failure was retried during this resumption.'
    driver.save(driver.RUN / 'summary.json', summary)
driver.pair = pair
driver.summarize = summarize
driver.__file__ = __file__
if __name__ == '__main__':
    if '--run' in sys.argv:
        run = Path(sys.argv[sys.argv.index('--run') + 1]).resolve()
        if run.parent.name != 'verified':
            raise RuntimeError('This continuation is Verified-only')
    driver.main()
