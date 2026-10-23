# Skill Dreaming

**PR streams teach reusable skills. Skills help extend and maintain the repository.**

[![Checks](https://github.com/Hik289/skill-dreaming/actions/workflows/ci.yml/badge.svg)](https://github.com/Hik289/skill-dreaming/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-research%20code-3776AB?logo=python&logoColor=white)

![Skill Dreaming: PR-guided skill generation, alignment, and repository maintenance](assets/main_figure.png)

An incoming feature request is rarely just a code edit. It also requires choosing existing abstractions, following repository conventions, and completing the associated tests, documentation, configuration, and compatibility work. Skill Dreaming turns development records into reusable, repository-specific procedures and updates those procedures as later PRs arrive. The model weights stay fixed; the skill set evolves.

## Workflow

1. **Retrieve development records.** Localize the request in the base checkout and screen earlier PRs. Exclude the target PR, unavailable records, and future information.
2. **Construct and verify candidates.** Reuse, repair, or synthesize a candidate change; execute local tests and configured checks before using it to teach a skill.
3. **Distill and align skills.** Generate procedures, constraints, maintenance obligations, and validation steps. Add, update, specialize, extend, flag conflicts, supersede, or keep existing records.
4. **Retrieve and inject.** Select applicable active skills, exclude stale or conflicting records, and pack complete instructions into a bounded context.
5. **Implement and maintain.** Generate the feature and its required maintenance changes, verify, and perform bounded repair when necessary. Persist outcomes and usage for later requests.

The active pool has a configurable capacity. Superseded and capacity-evicted skills are archived rather than discarded; old versions and operation records remain available locally. Retrieval and injected context have separate budgets.

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

The default replay preserves the original evaluate-then-learn protocol: generate from the base checkout and earlier skills, evaluate, then distill the observed PR for **later** tasks. Plan ranking in this mode is a heuristic, not execution verification.

To enable candidate verification and skill alignment **before** final implementation, add:

```bash
  --verified-learning \
  --learning-candidates 3 \
  --repair-attempts 1 \
  --max-active-skills 256 \
  --retrieve-k 8 \
  --retrieval-mode lexical \
  --skill-context-chars 12000
```

These are configurable budgets, not experimental results. `dense` and `hybrid` retrieval are also supported. The final actor receives skill procedures, not the verified candidate patch as a ready-made answer. Held-out target changes are used only after final evaluation. Each replay task starts from its recorded base; generated patches are not silently merged into the next task.

Bootstrap an initial pool from accepted, earlier PR records with `init --manifest ... --before-date ...`. Inspect and bound an existing pool with:

```bash
skill-dream maintain --skills ./workspace/skills --max-active-skills 256
```

See [Running the code](docs/reproduction.md) for manifest fields, chronological cutoffs, benchmark assets, and optional drivers. Run generated code in an appropriately restricted environment: a Git worktree isolates checkout state, not operating-system permissions.

## Configure

Model-backed commands require `ANTHROPIC_API_KEY` and an explicit `SD_MODEL`. Dense retrieval additionally requires `SD_EMBEDDING_ENDPOINT`, `SD_EMBEDDING_API_KEY`, and `SD_EMBEDDING_MODEL`. No concrete model ID or private endpoint is built in. Set `SD_SEND_TEMPERATURE=0` for providers that reject sampling-temperature parameters.

[.env.example](.env.example) and [configs/agent.example.json](configs/agent.example.json) contain credential-free templates. The process reads environment variables; it does not automatically load `.env.example`. Local credentials and runtime assets must stay out of version control. Model-backed runs can incur provider charges; the offline checks below do not make model calls.

## Code Layout

| Path | Purpose |
| --- | --- |
| `skill_dream/skill_store.py` | Persistent pool, relation operations, retrieval, usage statistics, and archival |
| `skill_dream/skill_context.py` | Temporal eligibility, conflict exclusion, and bounded skill injection |
| `skill_dream/workflow.py` | Verified candidate learning, maintenance planning, and bounded repair |
| `skill_dream/pipeline.py` | Chronological replay and final evaluation |
| `verified_a2_driver.py`, `verified_a2_driver_sonnet.py` | Verified patch-generation drivers using different skill-pool directories |
| `verified_external_driver.py` | Local method-inspired retrieval adapters |
| `verified_eval.py`, `verified_eval_iso.py` | Official Verified harness wrappers and report collection |
| `miniagent/rebuild_a2_driver.py` | Pro patch-generation driver |
| `scripts/legacy/` | Historical pool builders and analysis utilities; some need adapters not bundled here |
| `scripts/release_check.py` | Credential, private-path, model-ID, and publication checks |
| `tests/` | Offline checks for temporal boundaries, persistence, configuration, and publication rules |

The [Skill dataclass](skill_dream/skill_store.py) defines the persisted schema. Alignment supports `ADD`, `UPDATE`, `SPECIALIZE`, `EXTEND`, `CONFLICT`, `SUPERSEDE`, and `KEEP`. Invalid model decisions fall back to add/update. Supersession requires an explicit replacement relation and a later source date; keyword overlap alone cannot retire a skill. Conflicting alternatives are retained but never injected together.

## Check the Code

```bash
python scripts/release_check.py --staged
python -m unittest discover -s tests -v
python -m skill_dream.cli --help
```

## Evaluation Scope

Local test success is a regression signal, **not** proof of feature correctness or maintainer approval. The maintenance check verifies required file-surface coverage; semantic correctness still needs task-specific tests and review. Use `--check-command` for additional build or static checks. Official benchmark resolution comes from the benchmark harness, not this local proxy.

The Verified and Pro drivers use separately prepared datasets and skill pools. Named external adapters are explicitly **method-inspired approximations**, not author implementations. Historical utilities retain their entry points; several need external adapters. See [Running the code](docs/reproduction.md) for these boundaries and the supported commands.

This repository distributes code, usage instructions, and the overview figure only. Manuscripts, publication bundles, result reports, datasets, prebuilt pools, and credentials stay outside the release. New workflow components are covered by offline tests; no new benchmark scores are claimed by this update.
