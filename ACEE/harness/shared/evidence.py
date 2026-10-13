from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class EvidenceItem:
    label: str
    detail: str
    source_url: str = ""


@dataclass
class SourceAssessment:
    source_key: str
    feasible: bool
    access_mode: str
    item_data_mode: str
    medical_scope: str
    blockers: List[str] = field(default_factory=list)
    evidence: List[EvidenceItem] = field(default_factory=list)

