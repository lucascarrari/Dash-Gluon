from __future__ import annotations

from typing import Any
from ..core.dataset import Dataset
from ..core.pipeline import Pipeline
from ..download.era5land import FonteERA5LandVoronoi


class PipelineAquaCropERA5(Pipeline):
    """Pipeline para download e montagem de variáveis meteorológicas ERA5-Land para o AquaCrop."""

    name = "pipeline_aquacrop_era5"
    version = "1.0.0"

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {
            "uf": {"type": "string", "required": False, "default": "MG"},
            "ano": {"type": "integer", "required": False, "default": 2024},
            "data_inicio": {"type": "string", "required": False, "default": "2024-01-01"},
            "data_fim": {"type": "string", "required": False, "default": "2024-12-31"},
            "limite_celulas": {"type": "integer", "required": False, "default": None},
            "gerar_arquivos_aquacrop": {"type": "boolean", "required": False, "default": True},
        }

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        params = self.validate_parameters(parameters or {})
        fonte = FonteERA5LandVoronoi(
            uf=params["uf"],
            ano=params["ano"],
            data_inicio=params.get("data_inicio"),
            data_fim=params.get("data_fim"),
            limite_celulas=params.get("limite_celulas"),
        )
        dataset = fonte.dataset()

        if params.get("gerar_arquivos_aquacrop"):
            arquivos = fonte.exportar_arquivos_aquacrop()
            dataset = dataset.with_metadata(
                aquacrop_files=[str(p) for p in arquivos],
            )

        return dataset.with_metadata(
            pipeline=self.name,
            version=self.version,
        )
