from __future__ import annotations

from pathlib import Path
from typing import Any
import pandas as pd

from soilframe import Dataset, Pipeline


class PipelineSolo(Pipeline):
    name = "pipeline_solo"

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {
            "arquivo_solos": {"type": "file", "required": True, "formats": ["csv", "parquet"]},
            "formato_saida": {"type": "choice", "options": ["csv", "parquet"], "default": "parquet"},
        }

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        parameters = parameters or {}
        values = self.validate_parameters(parameters)
        path = Path(values["arquivo_solos"])
        if not path.exists():
            raise FileNotFoundError(f"Arquivo de solos não encontrado: {path}")
        data = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
        return Dataset(data, {"pipeline": self.name, "version": self.version, "source": str(path)})
