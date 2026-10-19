import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = Path(os.environ.get('SD_BENCH_ROOT', PROJECT_ROOT / 'workspace' / 'benchmark')).expanduser().resolve()
AGENT_CONFIG = Path(os.environ.get('SD_AGENT_CONFIG', PROJECT_ROOT / 'configs' / 'agent.json')).expanduser().resolve()
