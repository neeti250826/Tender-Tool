#!/usr/bin/env python3
"""Build deterministic SHA-256 manifests for the immutable tender-agent package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOTS = ("raw", "screenshots", "inputs")
DELIVERABLE_NAMES = {
    "candidate_rows.csv",
    "rejected_quarantine.csv",
    "route_retest_results.json",
    "source_coverage_findings.json",
    "navigation.json",
    "adapter_manifest.json",
    "qc_findings.json",
    "tender_agent_handoff.md",
}
EXCLUDE_NAMES = {"evidence_manifest.json", "deliverables_manifest.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def files_under(relative_roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for relative_root in relative_roots:
        base = ROOT / relative_root
        if base.exists():
            files.extend(path for path in base.rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


evidence_files = files_under(EVIDENCE_ROOTS)
deliverable_files = [ROOT / name for name in sorted(DELIVERABLE_NAMES)]
deliverable_files += sorted((ROOT / "adapters").glob("*.py"))
deliverable_files += sorted((ROOT / "audit").rglob("*"))
deliverable_files = [
    path
    for path in deliverable_files
    if path.is_file() and path.name not in EXCLUDE_NAMES and "__pycache__" not in path.parts and path.suffix != ".pyc"
]

for output_name, paths, manifest_type in (
    ("evidence_manifest.json", evidence_files, "source_evidence"),
    ("deliverables_manifest.json", deliverable_files, "deliverables"),
):
    payload = {
        "manifest_type": manifest_type,
        "country": "Kuwait",
        "run_date": "2026-09-30",
        "algorithm": "sha256",
        "file_count": len(paths),
        "files": [entry(path) for path in paths],
    }
    (ROOT / output_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({"evidence_files": len(evidence_files), "deliverable_files": len(deliverable_files)}))
