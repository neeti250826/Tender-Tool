"""Write SHA-256 evidence and adapter manifest for the SICOP handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    workspace = Path(__file__).resolve().parent.parent
    work = workspace / "outputs" / "sicop_supplier_pull" / "agent_work"
    paths = sorted((work / "raw").glob("*"))
    paths += sorted((work / "screenshots").glob("*"))
    paths += [
        work / "candidate_rows.json",
        work / "candidate_rows.csv",
        work / "candidate_rows_extended.json",
        work / "candidate_rows_extended.csv",
        work / "candidate_summary.json",
        work / "navigation.json",
        work / "coverage_limitations.json",
        work / "tender_agent_handoff.json",
    ]
    paths += sorted((workspace / "sicop_adapter").glob("*.py"))
    paths += [workspace / "sicop_adapter" / "README.md"]
    files = []
    for path in paths:
        if path.is_file():
            files.append({
                "path": path.relative_to(workspace).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            })
    manifest = {
        "source_id": "costa-rica-sicop-go-cr-3274a0dd",
        "adapter_version": "0.1.0",
        "hash_algorithm": "SHA-256",
        "files": files,
    }
    (work / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"hashed {len(files)} files")


if __name__ == "__main__":
    main()
