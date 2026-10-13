from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Protocol

from harness.sources.registry import SourceConfig


@dataclass
class SmokeProbeResult:
    source_key: str
    ok: bool
    mode: str
    detail: str
    sample_rows: List[Dict[str, str]] = field(default_factory=list)


class SourceModule(Protocol):
    CONFIG: SourceConfig

    def smoke_probe(self) -> SmokeProbeResult: ...

