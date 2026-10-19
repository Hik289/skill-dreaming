import sys, time, os
from skill_dream.llm import LLMClient, TokenMeter
deadline = time.time() + float(os.environ.get('PREFLIGHT_MAX', '86400'))
while time.time() < deadline:
    try:
        c = LLMClient(TokenMeter())
        r = c.complete('Say OK', role='preflight', max_tokens=5)
        if r and 'OK' in r.upper() and ((c.meter.snapshot().get('total_tokens') or 0) > 0):
            print('[preflight] proxy healthy:', repr(r))
            sys.exit(0)
    except Exception as e:
        print('[preflight] not ready:', str(e)[:80])
    time.sleep(120)
print('[preflight] gave up')
sys.exit(1)
