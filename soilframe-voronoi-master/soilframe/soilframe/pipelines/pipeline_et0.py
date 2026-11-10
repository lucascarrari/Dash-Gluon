from __future__ import annotations

from pathlib import Path
from typing import Any

from soilframe import Dataset, Pipeline


class PipelineET0(Pipeline):
    name = "pipeline_et0"

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {
            "arquivo_et0": {"type": "file", "required": True, "formats": ["nc", "netcdf"]},
            "ano": {"type": "integer", "required": True},
        }

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        parameters = parameters or {}
        values = self.validate_parameters(parameters)
        path = Path(values["arquivo_et0"])
        if not path.exists():
            raise FileNotFoundError(f"Arquivo ET0 não encontrado: {path}")
        from soil_analysis.et0 import carregar_et0_anual
        data = carregar_et0_anual(path, int(values["ano"]))
        return Dataset(data, {"pipeline": self.name, "version": self.version, "source": str(path), "ano": values["ano"]})
