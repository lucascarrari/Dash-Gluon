from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Metricas:
    """Métricas de uma avaliação de modelo."""

    valores: dict[str, Any] = field(default_factory=dict)

    def comparar(self, baseline: "Metricas | dict[str, Any]") -> bool:
        base = baseline.valores if isinstance(baseline, Metricas) else baseline
        for key, value in self.valores.items():
            if key in base and isinstance(value, (int, float)) and isinstance(base[key], (int, float)):
                if value < base[key]:
                    return False
        return True

    def para_dict(self) -> dict[str, Any]:
        return dict(self.valores)
