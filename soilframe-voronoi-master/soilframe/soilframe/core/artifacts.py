from __future__ import annotations

from pathlib import Path
from typing import Any
import json


class ArtifactStore:
    """Armazena resultados e versões treinadas no clone do projeto."""

    def __init__(self, root: str | Path = "outputs") -> None:
        self.root = Path(root)

    def path(self, kind: str, name: str, version: str = "1.0.0") -> Path:
        destination = self.root / kind / name / version
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    def write_metadata(self, path: str | Path, values: dict[str, Any]) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(values, indent=2, default=str), encoding="utf-8")
        return destination
