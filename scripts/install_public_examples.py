import argparse
import hashlib
import json
import re
from pathlib import Path


def install(source, snapshot, output):
    manifest = json.loads((source / "manifest.json").read_text())
    entries = {key: value for key, value in manifest["skill_sets"].items()
               if key.startswith(snapshot + "/")}
    if len(entries) != 3:
        raise ValueError("The selected snapshot must contain exactly three repositories")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty")
    for key, metadata in sorted(entries.items()):
        repo = key.removeprefix(snapshot + "/")
        slug = repo.replace("/", "__")
        archive = source / metadata["path"]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError(f"Checksum mismatch: {archive}")
        rows = [json.loads(line) for line in archive.read_text().splitlines()]
        if len(rows) != metadata["count"]:
            raise ValueError(f"Count mismatch: {archive}")
        destination = output / slug / "current"
        destination.mkdir(parents=True, exist_ok=True)
        for row in rows:
            name = row["name"]
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
                raise ValueError(f"Unsafe skill name: {name}")
            (destination / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
    print(f"Installed {sum(row['count'] for row in entries.values())} skills in {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("examples/pro_3repo"))
    parser.add_argument("--snapshot", choices=("legacy_available", "fresh_v6"), default="fresh_v6")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    install(args.source, args.snapshot, args.output)


if __name__ == "__main__":
    main()
