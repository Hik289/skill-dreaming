# Running the Code

## Installation

Python 3.10 or later and Git are required. Start from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python scripts/release_check.py
python -m unittest discover -s tests -v
skill-dream --help
```

The checks and skill-store initialization do not make model calls. Benchmark generation makes paid provider calls when configured; the release preparation checks do not run those experiments.

## Local Configuration

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Model provider credential, required for model calls |
| `ANTHROPIC_BASE_URL` | Optional endpoint override for the Anthropic SDK; leave unset for its default |
| `SD_MODEL` | Provider model ID used by the core replay |
| `SD_MODEL_HEAVY`, `SD_MODEL_CHEAP` | Optional role-specific overrides; default to `SD_MODEL` |
| `SD_EMBEDDING_ENDPOINT` | Full embeddings request URL for the dense retriever |
| `SD_EMBEDDING_API_KEY` | Embedding provider credential |
| `SD_EMBEDDING_MODEL` | Required embedding model ID, supplied locally |
| `SD_SEND_TEMPERATURE` | Set to `0` when the provider rejects temperature parameters |
| `SD_SKILL_POOL`, `SD_ALTERNATE_SKILL_POOL`, `SD_PRO_SKILL_POOL` | Optional paths to locally prepared pools |
| `SD_SKILL_CONTEXT_CHARS` | Context-character budget used by benchmark drivers |
| `SD_BENCH_ROOT` | Benchmark assets and output root; default `workspace/benchmark` |
| `SD_AGENT_CONFIG` | Mini-agent JSON configuration; default `configs/agent.json` |

Environment variables are read by the process. `.env.example` is an empty template, not an automatic dotenv loader. The embedding client expects an endpoint that accepts `input` and `model` and returns indexed `data[].embedding`; it sends bearer and `api-key` headers. No private service endpoint is bundled.

Set `SD_MODEL` explicitly; there is no hardcoded backbone. The mini-agent uses the model name in its own JSON configuration, so set both deliberately; changing only one does not align distiller and agent. Existing pool directories can be used through the pool-path environment overrides without moving their contents.

## Basic Repository Replay

```bash
skill-dream init --repo ./your-repository --skills ./workspace/skills
skill-dream replay \
  --repo ./your-repository \
  --manifest ./workspace/tasks.json \
  --pr-index ./workspace/history.json \
  --skills ./workspace/skills \
  --workdir ./workspace/replay \
  --limit 1
```

Supply JSON arrays or JSONL manifests with fields `pr`, `sha`, `base`, `subject`, `date`, and optional `kind` (`squash` by default). `sha` and `base` must exist in the local repository. Dates must be chronological, comparable ISO timestamps. `--python` selects the target repository's Python interpreter for tests; `--test-targets` accepts comma-separated targets. `--no-skills` runs the base condition.

The default replay generates from the base tree and prior skills, evaluates in a separate Git worktree, and distills the observed target PR for later rounds. Its plan selector remains a heuristic. Alignment now compares structured skill records and validates all seven relation operations; invalid decisions fall back to add/update.

`--verified-learning` enables a different, explicit sequence: retrieve earlier records; derive a conditional maintenance plan; construct candidate changes; execute tests and configured checks with bounded repair; distill the first passing candidate; align the active pool; inject selected skills into a fresh final implementation; verify; then observe the held-out PR for later rounds. Historical PRs and generated plans are not labeled execution-verified merely because an LLM approves them. The first passing candidate is used; this is not a claim to reproduce the historical best-of-K experiment.

Both modes preserve recorded task bases instead of chaining unapproved generated changes. Per-task `record.json` stores the final structured patch, checks, operation decisions, injected names, and token usage. No generated patch is pushed, merged, or submitted for review automatically. A final local pass requires successful installation, a nonempty passing test run, configured extra checks, and (in verified mode) the inferred maintenance surfaces. `task_success` remains the regression proxy for compatibility; `accepted_locally` also includes the verified-mode surface gate.

Optional manifest fields include `available_at`, `reviews`, `ci`, and `required_surfaces`. A supplied availability date must also precede the task. A missing or malformed timestamp fails closed. Keep rows in chronological order; ties cannot teach one another. Never substitute issue creation time for the availability of an accepted diff.

### Initial Skills and Pool Maintenance

When PR metadata is unavailable, `skill-dream index --repo ./your-repository --ref main --before-date <ISO timestamp> --output ./workspace/history.json` reconstructs chronological first-parent commit segments. Each segment spans a commit and its first parent, so a merge commit includes the merged change. PR numbers are recovered from conventional commit subjects when present; other segments retain a commit identifier. Choose a ref representing accepted repository history. This command does not infer missing maintainer reviews or prove merge-time availability; commit dates should be supplemented with observed availability when needed.

`init` creates an empty pool without model calls. To bootstrap from historical changes, provide `--manifest ./workspace/history.json --before-date <ISO timestamp>`; only rows explicitly marked `status: accepted` are distilled. This performs model calls and treats those records as accepted history, not as a fresh execution-verified result.

`--max-active-skills` bounds the active pool after each update (default 256 in the replay CLI). Capacity eviction ranks confidence plus smoothed success rate, then usage and source date, with deterministic tie-breaking. Evicted records and superseded skills are saved under `history/`; `pool.json` persists the policy and operation log. This keeps a bounded active pool, not an exactly constant number of useful skills. Historical storage is intentionally not bounded. Use a single writer for each store.

`skill-dream maintain --skills ./workspace/skills --max-active-skills 256` applies the budget. Add `--prune-stale --repo ./your-repository --base <commit>` to explicitly archive skills with missing referenced files or symbols. Retrieval checks version references without globally deleting them, which matters when replaying different historical bases.

### Retrieval and Injection

`--retrieval-mode lexical|dense|hybrid` selects keyword/type scoring, cosine similarity, or a weighted combination. All modes filter by source availability, target exclusion, active status, and referenced files/symbols when a checkout is available. Conflict and duplicate exclusion apply after ranking. Dense retrieval fails explicitly if its provider is unavailable; it does not silently switch the experiment to lexical retrieval.

`--retrieve-k` limits the retrieved set independently of active pool capacity. `--skill-context-chars` limits the serialized skill block (default 12000 characters). Complete records are packed or omitted; constraints and validation steps are not cut off mid-record. This is a character budget, not an exact token count. Actual provider token counts are recorded separately. Raw supporting PR patches and review text are not part of the injected skill block.

Use repeated `--check-command 'python -m compileall -q src'` arguments for trusted, repository-specific checks. Commands are executed as argument lists, not shell programs. A required maintenance surface means an actual touched file of that type, not a model's assertion; this remains weaker than semantic maintenance verification.

Run generated code in an environment with permissions appropriate to the repository. A Git worktree isolates checkout state but is not an OS security sandbox.

## SWE-bench Verified Generation

The benchmark extras pin the mini-agent version recorded in the drivers. Install them in a suitable benchmark environment and start Docker:

```bash
python -m pip install -e '.[benchmark]'
cp configs/agent.example.json configs/agent.json
```

Edit the local, ignored `configs/agent.json` with the model ID, prompt templates, and budgets for your run. The example is a starting point, not a recovered copy of the historical experiment configuration. The model credentials are supplied through the provider/mini-agent environment, not stored in this JSON file. The Pro environment needs its appropriate working directory, usually `/app`, instead of Verified's `/testbed`.

Prepare this benchmark directory layout:

```text
workspace/benchmark/
  data/
    swebench_verified.jsonl
    swebench_pro.jsonl
    pro_created_at.json
  verified_main100.json
  verified_pool/
    owner__repository/current/*.json
  verified_pool_alternate/
    owner__repository/current/*.json
  miniagent/
    pro_related_nogold/owner__repository/current/*.json
    skill_emb_cache/
  repos_cache/
    ansible__ansible.git/
    internetarchive__openlibrary.git/
    qutebrowser__qutebrowser.git/
```

Only prepare the assets needed for the chosen benchmark. `swebench_verified.jsonl` contains the official dataset rows; the driver needs at least `instance_id`, `repo`, `problem_statement`, and `created_at`. The Pro driver additionally uses `dockerhub_tag`, per-instance dates, and source commit dates from the repository mirrors. Skill JSON files follow the [Skill dataclass](../skill_dream/skill_store.py). The pool contents, target split, and model configuration must be prepared separately.

`verified_main100.json` is a historical filename; it must contain the actual evaluation IDs for your run. Do not infer the number of targets from the filename. External memory adapters exclude these IDs from their evidence collection.

After setting the local environment, generate both conditions on the same target IDs:

```bash
python verified_a2_driver.py --method none --ids_file ./workspace/target_ids.json --tag local --workers 1
python verified_a2_driver.py --method a2 --ids_file ./workspace/target_ids.json --tag local --workers 1
```

Generation writes `verified_preds_none_local.jsonl` and `verified_preds_a2_local.jsonl` under `SD_BENCH_ROOT`. The alternate `verified_a2_driver_sonnet.py` uses the other pool directory, but the actual agent backbone still comes from the JSON model configuration.

The A2 driver uses dense top-8 retrieval with cosine threshold 0.20, temporal/availability filtering, conflict exclusion, and the shared bounded skill block. Embedding-cache keys include the configured model and endpoint so changing either cannot reuse another embedding space. Validate source availability and overlap independently; a source issue creation date alone does not prove its accepted diff was available at target time.

## Official Verified Evaluation

```bash
python verified_eval_iso.py --method none --tag local --eval_workers 1
python verified_eval_iso.py --method a2 --tag local --eval_workers 1
```

Both wrappers call `swebench.harness.run_evaluation` after generation. They write parsed `verified_eval_METHOD_TAG.json` reports under `SD_BENCH_ROOT` and collect official `FAIL_TO_PASS` and `PASS_TO_PASS` outcomes. Persistent infrastructure errors have `resolved=null` in the isolated wrapper. Report their count and do not present them as ordinary unresolved tasks or silently remove them from the target denominator.

The historical wrappers may prune unused Docker resources and terminate timed-out harness processes. Use a dedicated benchmark environment. Exact reproduction requires the original target IDs, evidence pools, model configuration, and predictions in addition to these wrappers.

## External Adapters

```bash
python verified_external_driver.py --method skilllens --ids_file ./workspace/target_ids.json --tag local --workers 1
```

Supported method identifiers are `skilllens`, `codeskill`, `l2c`, and `socratic`. These select lightweight local approximations of aspects of the named work. They do not include author training, complete self-evolution procedures, or a faithful reproduction guarantee. The same evaluation wrappers accept their method identifiers.

## Pro Generation

```bash
python miniagent/rebuild_a2_driver.py --method a2 --ids_file ./workspace/pro_target_ids.json --tag local --workers 1
```

The driver writes `miniagent/rebuild_preds_a2_local.jsonl`. Evaluate Pro predictions with its official Pro harness; the bundled `verified_eval*.py` wrappers are Verified-specific and must not evaluate Pro. The Pro evaluator and exact historical Pro assets are not included.

## Historical Utilities and Missing Components

`scripts/legacy/` preserves the supplied pool builders, record analyzers, diagnostic scripts, and rerun utilities. They operate on historical file naming conventions, often relative to the current working directory. Several require `methods`, `sd_swebench_adapter`, or `sd_v2`, which were absent from the supplied package. Pool builders look for the `methods` adapter under the configured benchmark root's `adapter` directory. They are not advertised as standalone supported commands.

The core now includes configurable hybrid retrieval and a verified, bounded-repair learning workflow. It does not reconstruct the historical experiment-specific best-of-K runner, official Trace2Skill implementation, or missing author adapters. Local approximations must not be reported as official reproductions. Runtime outputs, datasets, prebuilt pools, and result reports must remain local and are not part of this source distribution.
