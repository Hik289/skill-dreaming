# Skill Dreaming

<div align="center">

**Aligning repository skills with a stream of pull requests**

[![Checks](https://github.com/xfab-xinyuansong/skill-dreaming/actions/workflows/ci.yml/badge.svg)](https://github.com/xfab-xinyuansong/skill-dreaming/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Learning](https://img.shields.io/badge/Learning-training--free-16856B)

[Method](docs/method.md) · [Results](docs/results.md) · [Reproduction](docs/reproduction.md) · [Implementation](#implementation)

[Repository](https://github.com/xfab-xinyuansong/skill-dreaming) · [Hik289](https://github.com/Hik289/skill-dreaming)

</div>

![Skill Dreaming: PR evidence, verification, skill alignment, complete feature PRs, and learning over a PR stream](assets/main_figure.png)

## Why Skill Dreaming?

A feature request rarely explains where a change belongs, which internal API to extend, which earlier feature to imitate, or which tests, documentation, examples, and configuration must change together. Those engineering decisions live in a repository's PR history and review outcomes. They also change as the repository evolves.

Skill Dreaming turns that evidence into a persistent, repository-specific skill set. As new PRs arrive, the system retrieves useful past evidence, creates or revises skills, aligns their relationships, and uses the resulting set to implement complete feature changes. Observed outcomes become evidence for later rounds. Model parameters remain fixed.

- **Learn engineering decisions from PRs.** Capture implementation procedures, maintenance obligations, review constraints, and failure patterns.
- **Evolve a skill set across tasks.** Reuse, update, specialize, extend, mark conflicts, and supersede skills as repository conventions change.
- **Complete the whole PR.** Evaluate source changes together with tests, docs, README, examples, configuration, migration, errors, and compatibility when applicable.

## Method

The intended sequential flow is:

```text
Repository + feature request
  -> retrieve / repair / synthesize PR evidence
  -> verify and select evidence
  -> distill procedures and negative constraints
  -> align the repository skill set
  -> implement and verify the complete feature PR
  -> record outcomes for the next round
```

A skill records a trigger, procedure, negative constraints, required maintenance surfaces, validation steps, evidence provenance, version scope, and relationships to other skills. The update vocabulary is `ADD`, `UPDATE`, `SPECIALIZE`, `EXTEND`, `CONFLICT`, `SUPERSEDE`, and `KEEP`.

**Evaluation boundary:** the current target's accepted patch, gold tests, and final review outcome are held out during generation. In historical replay, the observed target PR can teach skills for subsequent tasks. Timestamp filters and probe checks are useful checks, but do not by themselves establish that all evidence was available at the task cutoff.

See [the method](docs/method.md) for the formal loop and the distinction between the proposed system and the released prototype.

## Reported Results

The following measurements come from the corrected experiment ledger. They are **single-seed, selected-subset results**, not full-dataset leaderboard scores. This release has not rerun the model-backed experiments.

| Benchmark | Target tasks | Base resolved | Skill Dreaming resolved | Difference | Paired exact McNemar p |
| --- | ---: | ---: | ---: | ---: | ---: |
| SWE-bench Pro, 3 repositories | 100 | 79/100 (0.790) | **88/100 (0.880)** | **+9.0 pp** | 0.0117 |
| SWE-bench Verified, 12 repositories | 101 | **93/101 (0.921)** | 91/101 (0.901) | -2.0 pp | 0.625 |

Both rows use the experiment ledger's **Opus-5.5** backbone label. Provider model IDs are configurable; that label should not be treated as a provider ID. Pro and Verified contain different instances. Their contrast motivates further study of agent strength, evidence quality, and remaining task difficulty; it does not establish a causal saturation threshold.

The **released A2 SWE-bench drivers use dense embedding top-8 retrieval**, with a cosine cutoff of 0.20. The click experiments report a separate hybrid BM25+dense and best-of-K configuration. These configurations and their scores are kept separate.

### Same-Benchmark External Adapters

All rows below use the same 101-task Verified subset in the corrected ledger. The named external methods are **local adaptations or approximations**, not executions of the authors' full official systems.

| Method | Resolved / 101 | Rate |
| --- | ---: | ---: |
| Base | 93 | 0.921 |
| SkillLens-inspired adapter | **95** | **0.941** |
| Learning to Commit-inspired adapter | 93 | 0.921 |
| CODESKILL-inspired adapter | 93 | 0.921 |
| Socratic-SWE-inspired adapter | 92 | 0.911 |
| Skill Dreaming, A2 | 91 | 0.901 |

### Complete PRs: click Pilot

This is a small, separate pilot: 18 PRs, one seed; gold-test rates use the 14 gold-evaluable tasks. The table distinguishes regression safety from task-specific gold tests.

| Configuration | Existing tests pass | Maintenance Surface F1 | Gold PR tests pass |
| --- | ---: | ---: | ---: |
| Base, K=1 | 0.833 | 0.620 | **0.286** |
| Base, K=4 | 0.889 | 0.707 | **0.286** |
| Append-only skills, K=4 | 0.944 | 0.716 | 0.143 |
| Skill Dreaming, hybrid + K=4 | **1.000** | **0.737** | 0.143 |

Skills improve regression safety and surface coverage in this pilot, while the gold-test result declines. Surface coverage measures which categories were edited; it does not verify the semantic correctness of every documentation or maintenance change.

[All ten experiments, metric definitions, and limitations](docs/results.md) include online skill evolution, stale-evidence adaptation, candidate cost, and cross-repository pilots. Unmeasured quantities remain `n/a` and pending runs remain pending.

## Quick Start

```bash
git clone https://github.com/xfab-xinyuansong/skill-dreaming.git
cd skill-dreaming
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
skill-dream --help
```

Initialize an empty skill store without model credentials:

```bash
skill-dream init --repo ./your-repository --skills ./workspace/skills
```

Before making model calls, configure `ANTHROPIC_API_KEY` and `SD_MODEL` in your local environment. Dense retrieval additionally needs `SD_EMBEDDING_ENDPOINT` and `SD_EMBEDDING_API_KEY`. A blank configuration template is provided in [.env.example](.env.example); the application reads environment variables and does not automatically load that file.

For repository replay, benchmark data layout, agent configuration, and official-harness evaluation, follow [Reproduction](docs/reproduction.md). Docker and benchmark assets are required for SWE-bench; they are not needed for the local checks below.

## Implementation

| Path | Purpose |
| --- | --- |
| `skill_dream/` | Skill representation, versioned store, PR parsing, replay stages, staleness checks, patch application, model clients, metrics |
| `verified_a2_driver.py` | Verified patch generation with base or A2 dense skill retrieval |
| `verified_a2_driver_sonnet.py` | Verified driver using the alternate skill-pool directory |
| `verified_external_driver.py` | Shared-harness external-method-inspired adapters |
| `verified_eval.py`, `verified_eval_iso.py` | Official Verified harness wrappers and report collection |
| `miniagent/rebuild_a2_driver.py` | Pro generation driver for the three-repository setting |
| `scripts/legacy/` | Historical analysis, pool-building, and rerun utilities; some require research adapters absent from this release |
| `scripts/release_check.py` | Credential/path scan, Python syntax checks, and comment/docstring checks |
| `configs/agent.example.json` | Credential-free agent configuration template |
| `tests/` | Offline checks for temporal boundaries, skill persistence, probes, metrics, and configuration |

**Release scope.** The repository includes research code and summarized results. Raw trajectories, exact historical target splits, trained checkpoints, prebuilt skill pools, the complete hybrid click runner, and some historical adapters are not bundled. The current prototype supports the skill relation operations at the store level; its automatic operation chooser currently emits `ADD` and `UPDATE`. The wider relation policies in the proposal require the corresponding experiment-specific runner.

## Local Checks

```bash
python scripts/release_check.py
python -m unittest discover -s tests -v
python -m skill_dream.cli --help
```

Model inference and SWE-bench evaluation are separate, resource-intensive runs. Keep credentials, private configuration, generated pools, and runtime artifacts out of version control; the provided ignore rules exclude their default locations.

## Citation

```bibtex
@software{skill_dreaming_2026,
  title = {Skill Dreaming: Aligning Repository Skills with a Stream of Pull Requests},
  year = {2026},
  url = {https://github.com/xfab-xinyuansong/skill-dreaming}
}
```
