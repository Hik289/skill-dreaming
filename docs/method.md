# Method

## Engineering Motivation

Each repository develops conventions that a feature request leaves implicit: the internal API to extend, the nearest analogous feature, tests to add, the shape of error handling and logging, and the documentation, configuration, migration, and example changes expected by maintainers. Earlier PRs expose these decisions. Later PRs may revise them.

Skill Dreaming treats the repository skill set as persistent external state. A new PR can introduce a skill, revise an existing procedure, narrow its trigger, expose a conflict, or replace a rule made obsolete by an API change. The same evolving set supports feature implementation and the work needed to make the PR complete.

## Sequential Learning Loop

Let `R_t` be the base repository, `tau_t` the incoming task, `S_t` the skill set, and `H_t` the observable history at the task cutoff.

1. **Find evidence.** Retrieve related past PRs from `H_t`; identify missing, incomplete, or stale evidence.
2. **Construct candidates.** Reuse, repair, or synthesize PR candidates from the observable repository and task.
3. **Verify and select.** Check candidate correctness, regressions, repository conventions, and required maintenance surfaces. Retain both useful procedures and grounded failure constraints.
4. **Distill and align.** Produce skill changes from this evidence and resolve their relationship to `S_t`, yielding `S'_t`.
5. **Implement a complete PR.** Generate the feature with `R_t`, `tau_t`, and `S'_t`; include the applicable maintenance work.
6. **Observe the outcome.** Verify the final patch and record outcomes and newly available evidence for future tasks.

```text
E_t = Detect(R_t, tau_t, H_t)
P_t = E_t union Repair(E_t) union Synthesize(R_t, tau_t, S_t)
(P_t^+, P_t^-) = Verify(P_t)
S'_t = Align(S_t, Distill(P_t^+, P_t^-))
Patch_t = Agent(R_t, tau_t, S'_t)
O_t = Evaluate(Patch_t)
(R_{t+1}, S_{t+1}, H_{t+1}) = Record(R_t, S'_t, H_t, Patch_t, O_t)
```

Synthesized candidates are agent-produced evidence, not the target's held-out accepted solution. A target's accepted patch, gold tests, or eventual review decision becomes learning evidence only after that target has been attempted. In historical replay, a known accepted PR is distilled for later rounds.

## Skill Representation

The `Skill` dataclass records:

| Field | Meaning |
| --- | --- |
| `name`, `category` | Stable skill identity and engineering role |
| `trigger` | Task type, keywords, and repository surfaces |
| `procedure` | Concrete implementation or maintenance steps |
| `negative_constraints` | Evidence-grounded mistakes to avoid |
| `required_surfaces` | Code, tests, docs, changelog, configuration, migration, or examples to consider |
| `validation` | Checks required before considering the change complete |
| `positive_evidence`, `negative_evidence`, `review_evidence` | Sources supporting the procedure or constraint |
| `version_scope` | Source identity, evidence date, optional availability date, and version scope |
| `relations` | Links to related, conflicting, or superseded skills |
| `confidence`, `stats` | Confidence and observed usage outcomes |

Typical skills include feature analogy, internal API integration, PR diff shape, cross-file coupling, test expansion, documentation/README synchronization, configuration/migration, examples, logging/errors, and compatibility conventions.

## Skill Set Alignment

| Operation | Effect in `SkillStore` |
| --- | --- |
| `ADD` | Insert a new skill |
| `UPDATE` | Archive the old version, preserve accumulated evidence and usage statistics, and write the revision |
| `SPECIALIZE` | Add a skill linked to a more general parent |
| `EXTEND` | Add a skill linked to an existing capability |
| `CONFLICT` | Record a conflict link for an existing skill |
| `SUPERSEDE` | Archive and remove the target skill from the active set, then add its replacement |
| `KEEP` | Leave the active set unchanged |

The proposed system decides operations using new evidence, previous evidence, repository state, and skill relationships. The released basic stage chooser only emits `ADD` or `UPDATE` by name; the store exposes the full operation vocabulary for experiment-specific policies and future implementations. Conflict links alone do not automatically resolve incompatible skills during retrieval.

## Retrieval Configurations

The released SWE-bench A2 generation drivers embed the task and skill text, rank by cosine similarity, select at most eight skills, and discard similarities below 0.20. Skill text combines the name, trigger keywords, repository surfaces, and procedure. The Verified driver filters by stored source date; the Pro driver obtains source commit dates from local repository mirrors.

The corrected click experiment ledger describes a separate hybrid BM25+dense retriever, followed by candidate generation and a regression-based best-of-K selector. That hybrid module and complete click runner are not included in this source package. The basic `SkillStore.retrieve` is a keyword/task-type prototype, not the A2 dense or hybrid retriever.

## Evaluation Boundaries

- Generation uses the base repository, task text, and skills from admissible evidence. The basic replay localizer uses only the base file tree and task text.
- The basic replay's newly observed target patch is distilled after generation and evaluation, tagged with its source date, and made available to later rounds.
- A temporal retrieval cutoff rejects unknown, same-time, and future source dates; an explicit later `available_at` date also excludes a skill until that date.
- Timestamp correctness depends on the input provenance. Issue/PR creation time is not necessarily the time its final patch became available. Reconstruct availability from merge/review/commit history before making strict temporal-validity claims.
- The historical target/evidence splits and raw pools are absent from this release. The supplied filters do not independently establish split disjointness, source-patch availability, or absence of overlapping implementation content.
- `LeakGuard` detects registered marker strings in generation context. It is a runtime check, not a complete information-flow proof.
- Official benchmark evaluation is run after patch generation. Gold tests must not choose candidates or write current-task skills.

## What Is Currently Implemented?

The release provides a skill store, staleness/reference checks, PR parsing, model and embedding clients, a basic replay prototype, A2 benchmark generation drivers, external-method-inspired retrieval adapters, and Verified evaluation wrappers.

In the basic replay, candidate synthesis produces plans and the selector uses a surface-based heuristic. It does not execute every candidate before selection. Replay `task_success` is patch application plus existing-test success; it is not official SWE-bench `resolved`. The full verified-candidate pipeline, complete hybrid runner, all relation-decision policies, and automated maintenance correctness checks remain outside this bundled implementation.
