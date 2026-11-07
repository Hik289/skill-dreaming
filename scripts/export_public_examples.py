import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


REPOS = ("ansible__ansible", "internetarchive__openlibrary", "qutebrowser__qutebrowser")
REDACTIONS = {
    "credential": re.compile(r"\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|ABSK[A-Za-z0-9+/=_-]{30,})\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "private_endpoint": re.compile(r"https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|[^/\s]+\.services\.ai\.azure\.com)(?::\d+)?"),
    "url_credentials": re.compile(r"https?://[^/@\s\x22\\]+:[^/@\s\x22\\]+@"),
    "personal_path": re.compile(r"/(?:Users|home)/[^\s/\x22\x27]+"),
    "email": re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scrub(value, counts):
    if isinstance(value, dict):
        return {key: scrub(item, counts) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, counts) for item in value]
    if not isinstance(value, str):
        return value
    for name, pattern in REDACTIONS.items():
        value, count = pattern.subn("[REDACTED_" + name.upper() + "]", value)
        counts[name] += count
    return value


def git_record(cache, repo, commit):
    result = subprocess.run(
        ["git", "-C", str(cache), "show", "-s", "--format=%cI%x01%s%x01%b%x01%ct", commit],
        capture_output=True, text=True, check=True)
    date, subject, body, timestamp = result.stdout.rstrip("\n").split("\x01", 3)
    diff = subprocess.run(
        ["git", "-C", str(cache), "show", "--format=", "--no-ext-diff", "--unified=3", commit],
        capture_output=True, text=True, check=True).stdout
    return {"sha": commit, "date": date, "subject": subject, "body": body,
            "diff": diff, "source_selection": "Reconstructed from the public Git commit; original source record unavailable.",
            "committer_unix": int(timestamp), "repo": repo}


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def export(legacy, fresh, sources, git_cache, output):
    if output.exists():
        raise RuntimeError("Output directory already exists; do not mix releases")
    counts = {name: 0 for name in REDACTIONS}
    manifest = {"skill_sets": {}, "historical_prs": {}, "redactions": counts,
                "scope": "public example from existing repository snapshots; not a bit-for-bit reconstruction of the original headline run"}
    for slug in REPOS:
        repo = slug.replace("__", "/")
        pool_records = {}
        referenced = set()
        for label, root in (("legacy_available", legacy), ("fresh_v6", fresh)):
            files = sorted((root / slug / "current").glob("*.json"))
            if len(files) != 200:
                raise RuntimeError(f"Expected 200 skills: {label}/{repo}")
            records = [json.loads(path.read_text()) for path in files]
            if len({record["name"] for record in records}) != 200:
                raise RuntimeError(f"Duplicate skill names: {label}/{repo}")
            if any(not record.get("positive_evidence") for record in records):
                raise RuntimeError(f"Missing positive source: {label}/{repo}")
            referenced.update(commit for record in records for commit in record["positive_evidence"])
            pool_records[label] = records

        source_file = sources / f"{slug}.json"
        source_by_sha = {record["sha"]: record for record in json.loads(source_file.read_text())}
        missing = referenced - source_by_sha.keys()
        for commit in sorted(missing):
            source_by_sha[commit] = git_record(git_cache / f"{slug}.git", repo, commit)
        if referenced - source_by_sha.keys():
            raise RuntimeError(f"Unresolved source commits: {repo}")

        for label, records in pool_records.items():
            if label == "fresh_v6":
                for record in records:
                    scope = record.get("version_scope", {})
                    if scope.get("repo") != repo or scope.get("source_id") not in record["positive_evidence"]:
                        raise RuntimeError(f"Invalid fresh-pool provenance: {repo}")
            target = output / "skill_sets" / label / f"{slug}.jsonl"
            write_jsonl(target, [scrub(record, counts) for record in sorted(records, key=lambda row: row["name"])])
            manifest["skill_sets"][f"{label}/{repo}"] = {"count": len(records),
                "sha256": digest(target), "path": str(target.relative_to(output))}

        historical = [source_by_sha[commit] for commit in sorted(referenced)]
        target = output / "historical_prs" / f"{slug}.jsonl"
        write_jsonl(target, [scrub(record, counts) for record in historical])
        manifest["historical_prs"][repo] = {"count": len(historical),
            "reconstructed_commits": len(missing), "sha256": digest(target),
            "path": str(target.relative_to(output))}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-pool", type=Path, required=True)
    parser.add_argument("--fresh-pool", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--git-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.legacy_pool, args.fresh_pool, args.sources, args.git_cache, args.output)
    print(json.dumps({"skills": sum(row["count"] for row in result["skill_sets"].values()),
                      "historical_prs": sum(row["count"] for row in result["historical_prs"].values()),
                      "redactions": result["redactions"]}, sort_keys=True))


if __name__ == "__main__":
    main()
