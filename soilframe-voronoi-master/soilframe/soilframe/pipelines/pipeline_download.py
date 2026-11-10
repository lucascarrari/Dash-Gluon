from __future__ import annotations

from typing import Any
from ..core.dataset import Dataset
from ..core.pipeline import Pipeline
from ..download.voronoi import EstrategiaDownloadVoronoi


class PipelineDownloadSentinel(Pipeline):
    """Pipeline para planejamento e otimização de download de satélite com Agro-Voronoi."""

    name = "pipeline_download_sentinel"
    version = "1.0.0"

    def __init__(self, fonte=None, estrategia=None, **parameters: Any) -> None:
        estrategia = estrategia or EstrategiaDownloadVoronoi()
        super().__init__(fonte=fonte, estrategia=estrategia, **parameters)

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {
            "meta_cobertura": {"type": "float", "required": False, "default": 0.99},
            "orcamento_gb": {"type": "float", "required": False, "default": None},
            "perfil_bandas": {"type": "choice", "options": ["ndvi_scl", "l2a_12"], "default": "ndvi_scl"},
            "objetivo": {"type": "choice", "options": ["area", "talhoes"], "default": "area"},
            "uf": {"type": "string", "required": False, "default": None},
            "regiao": {"type": "string", "required": False, "default": None},
        }

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        params = self.validate_parameters(parameters or {})
        
        # Se a pipeline tem uma estratégia configurada, usa ela
        est = self.estrategia if isinstance(self.estrategia, EstrategiaDownloadVoronoi) else EstrategiaDownloadVoronoi(
            perfil_bandas=params["perfil_bandas"],
            objetivo=params["objetivo"],
        )

        plano = est.planejar(
            meta_cobertura=params.get("meta_cobertura"),
            orcamento_gb=params.get("orcamento_gb"),
            objetivo=params.get("objetivo"),
            perfil_bandas=params.get("perfil_bandas"),
            uf=params.get("uf"),
            regiao=params.get("regiao"),
        )

        dataset = plano.to_dataset()
        return dataset.with_metadata(
            pipeline=self.name,
            version=self.version,
        )
