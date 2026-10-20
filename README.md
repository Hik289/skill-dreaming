# Skill Dreaming

Python tooling for repository-specific skills and chronological pull-request replay. The source includes a versioned skill store, PR parsing, patch generation, staleness checks, benchmark drivers, and offline tests.

[![Checks](https://github.com/Hik289/skill-dreaming/actions/workflows/ci.yml/badge.svg)](https://github.com/Hik289/skill-dreaming/actions/workflows/ci.yml)

[Running the code](docs/reproduction.md) | [Primary repository](https://github.com/Hik289/skill-dreaming) | [Mirror](https://github.com/xfab-xinyuansong/skill-dreaming)

## Install

Python 3.10 or later and Git are required.

```bash
git clone https://github.com/Hik289/skill-dreaming.git
cd skill-dreaming
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
skill-dream --help
```

## Use

Initialize a skill store without model credentials:

```bash
skill-dream init --repo ./your-repository --skills ./workspace/skills
```

Replay tasks using local repository history and a task manifest:

```bash
skill-dream replay \
  --repo ./your-repository \
  --manifest ./workspace/tasks.json \
  --pr-index ./workspace/history.json \
  --skills ./workspace/skills \
  --workdir ./workspace/replay \
  --limit 1
```

The basic replay generates a patch from the base repository and earlier skills, evaluates it in a separate Git worktree, then distills the observed PR into skills for later tasks. Candidate selection in this prototype operates on plans, not independently executed candidate patches. Its success field is regression-oriented, not proof that a requested feature is correct.

See [Running the code](docs/reproduction.md) for manifest fields, chronological cutoffs, benchmark assets, and optional drivers. Run generated code in an appropriately restricted environment: a Git worktree isolates checkout state, not operating-system permissions.

## Configure

Model-backed commands require `ANTHROPIC_API_KEY` and an explicit `SD_MODEL`. Dense retrieval additionally requires `SD_EMBEDDING_ENDPOINT` and `SD_EMBEDDING_API_KEY`.

[.env.example](.env.example) and [configs/agent.example.json](configs/agent.example.json) contain credential-free templates. The process reads environment variables; it does not automatically load `.env.example`. Local credentials and runtime assets must stay out of version control. Model-backed runs can incur provider charges; the offline checks below do not make model calls.

## Code Layout

| Path | Purpose |
| --- | --- |
| `skill_dream/` | Skill storage, PR parsing, replay, retrieval, patch application, checks, and model clients |
| `verified_a2_driver.py`, `verified_a2_driver_sonnet.py` | Verified patch-generation drivers using different skill-pool directories |
| `verified_external_driver.py` | Local method-inspired retrieval adapters |
| `verified_eval.py`, `verified_eval_iso.py` | Official Verified harness wrappers and report collection |
| `miniagent/rebuild_a2_driver.py` | Pro patch-generation driver |
| `scripts/legacy/` | Historical pool builders and analysis utilities; some need adapters not bundled here |
| `scripts/release_check.py` | Credential/path, source, and code-only publication checks |
| `tests/` | Offline checks for temporal boundaries, persistence, configuration, and publication rules |

The [Skill dataclass](skill_dream/skill_store.py) defines the persisted schema. The store exposes `ADD`, `UPDATE`, `SPECIALIZE`, `EXTEND`, `CONFLICT`, `SUPERSEDE`, and `KEEP`; the default automatic chooser only emits `ADD` and `UPDATE`. Conflict links do not automatically resolve incompatible retrievals.

## Check the Code

```bash
python scripts/release_check.py --staged
python -m unittest discover -s tests -v
python -m skill_dream.cli --help
```

This is a code-only distribution with the configuration templates and instructions needed to use it. Manuscripts, figures, result reports, publication bundles, datasets, prebuilt pools, and credentials are not distributed here. Benchmark drivers require separately prepared assets; the complete hybrid replay runner and several historical adapters are not included.
