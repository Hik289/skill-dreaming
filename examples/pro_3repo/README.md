# Three-Repository PR and Skill Example

This example contains two repository-specific skill snapshots and the historical PR records referenced by their skills. Each snapshot has 200 skills for each of `ansible/ansible`, `internetarchive/openlibrary`, and `qutebrowser/qutebrowser`. The 1,127 PR records are deduplicated across snapshots. `manifest.json` lists counts and SHA-256 checksums; sensitive incidental text in the records has been redacted.

Historical diffs originate from the named upstream projects; their original authorship and licensing remain applicable.

The `legacy_available` snapshot is an available historical pool, **not an exact copy of the pool used for the original headline result**. `fresh_v6` is a separately rebuilt snapshot. Keep each repository's skills separate, and apply source-time filtering before retrieving skills for a benchmark task. These records may contain historical issue selection; they are not a ready-made leakage-free evaluation split.

To materialize either snapshot in the directory layout expected by the Pro driver:

```bash
python scripts/install_public_examples.py \
  --source examples/pro_3repo \
  --snapshot fresh_v6 \
  --output ./workspace/pro_skills
```

Set `SD_PRO_SKILL_POOL=./workspace/pro_skills` for the Pro driver. The three subdirectories are created automatically, each with `current/*.json`. A skill's `positive_evidence` commit hashes link to `sha` in the corresponding `historical_prs/*.jsonl` file. The source PR records are examples for inspection and pool construction; do not inject their raw diffs as target answers.

Configure model access locally with [`credentials.example.env`](credentials.example.env) and the repository's [`configs/agent.example.json`](../../configs/agent.example.json). The example uses the environment variable names read by the Bedrock benchmark runner; choose an authorized model/profile in your local configuration. The separate core replay uses `ANTHROPIC_API_KEY` instead. Never commit a filled-in credential file. No real credentials or benchmark predictions are included.
