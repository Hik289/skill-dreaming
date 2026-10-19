from __future__ import annotations
import uuid
from dataclasses import dataclass, field
PROBE_PREFIX = 'SKILLDREAM_LEAK_PROBE_'

class LeakViolation(Exception):
    pass

def make_probe() -> str:
    return PROBE_PREFIX + uuid.uuid4().hex

@dataclass
class LeakGuard:
    probes: list = field(default_factory=list)
    violations: list = field(default_factory=list)

    def inject(self, text: str) -> str:
        p = make_probe()
        self.probes.append(p)
        return f'{p}\n{text}\n{p}'

    def register_probe(self, probe: str):
        self.probes.append(probe)

    def scan(self, context_text: str, where: str='generation_context') -> bool:
        hit = [p for p in self.probes if p in context_text]
        if hit:
            self.violations.append({'where': where, 'probes_found': hit})
            return False
        return True

    def assert_clean(self, context_text: str, where: str='generation_context'):
        ok = self.scan(context_text, where)
        if not ok:
            raise LeakViolation(f"[anchor_4] LEAK DETECTED at {where}: forbidden probe(s) visible to generation step: {self.violations[-1]['probes_found']}")
        return True

    def report(self) -> dict:
        return {'n_probes': len(self.probes), 'n_violations': len(self.violations), 'violations': self.violations, 'clean': len(self.violations) == 0}
