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
| `SD_EMBEDDING_MODEL` | Embedding model; default `text-embedding-3-small` |
| `SD_BENCH_ROOT` | Benchmark assets and output root; default `workspace/benchmark` |
| `SD_AGENT_CONFIG` | Mini-agent JSON configuration; default `configs/agent.json` |

Environment variables are read by the process. `.env.example` is an empty template, not an automatic dotenv loader. The embedding client expects an endpoint that accepts `input` and `model` and returns indexed `data[].embedding`; it sends bearer and `api-key` headers. No private service endpoint is bundled.

The core defaults retain a historical Sonnet model ID. Set `SD_MODEL` explicitly to reproduce a specific backbone configuration. The mini-agent uses the model name in its own JSON configuration, so set both deliberately; changing only one does not align distiller and agent.

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

The basic replay generates from the base tree and prior skills, evaluates the patch in a separate Git worktree, and distills the observed target PR for later rounds. Its candidate selector is a plan/surface heuristic, its operation chooser emits ADD/UPDATE, and its task-success flag is a regression-oriented proxy. It is not the complete hybrid best-of-K experiment runner.

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
  verified_pool_opus55/
    owner__repository/current/*.json
  verified_pool_sonnet/
    owner__repository/current/*.json
  miniagent/
    pro_related_nogold_opus55/owner__repository/current/*.json
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

The A2 driver uses dense top-8 retrieval with cosine threshold 0.20. Evidence admissibility uses stored dates. Validate source availability, target exclusion, and overlap separately; a source issue creation date alone does not prove its accepted diff was available at target time.

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

The click hybrid retrieval module, complete best-of-K runner, official Trace2Skill integration, and the experiment-specific relation/evidence-source runners are not bundled. No replacement implementation is silently substituted for these components. Runtime outputs, datasets, prebuilt pools, and result reports must remain local and are not part of this source distribution.
