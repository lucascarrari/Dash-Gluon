from __future__ import annotations

from typing import Any, Iterable
import pandas as pd

from ..core.data_sources import FonteDados
from ..core.dataset import Dataset
from .voronoi import EstrategiaDownloadVoronoi
from .base import PlanoDownload


class FonteSentinelVoronoi(FonteDados):
    """Fonte de dados para imagens Sentinel-2 guiada pela estratégia Agro-Voronoi."""

    def __init__(
        self,
        estrategia: EstrategiaDownloadVoronoi | None = None,
        meta_cobertura: float = 0.99,
        orcamento_gb: float | None = None,
        perfil_bandas: str = "ndvi_scl",
        uf: str | Iterable[str] | None = None,
        regiao: str | Iterable[str] | None = None,
        municipios: list[int | str] | None = None,
        datas: list[str] | None = None,
        nome: str = "Sentinel2_AgroVoronoi",
        schema: dict[str, Any] | None = None,
    ) -> None:
        default_schema = {
            "id": int,
            "pixel_m": int,
            "volume_mb": float,
        }
        super().__init__(nome=nome, schema=schema or default_schema)
        self.estrategia = estrategia or EstrategiaDownloadVoronoi(perfil_bandas=perfil_bandas)
        self.meta_cobertura = meta_cobertura
        self.orcamento_gb = orcamento_gb
        self.perfil_bandas = perfil_bandas
        self.uf = uf
        self.regiao = regiao
        self.municipios = municipios
        self.datas = datas or ["2025-01-01"]
        self.ultimo_plano: PlanoDownload | None = None

    def extrair(self) -> pd.DataFrame:
        """Gera o plano ótimo de download e retorna o manifesto em DataFrame."""
        plano = self.estrategia.planejar(
            meta_cobertura=self.meta_cobertura,
            orcamento_gb=self.orcamento_gb,
            perfil_bandas=self.perfil_bandas,
            uf=self.uf,
            regiao=self.regiao,
            municipios=self.municipios,
            datas_por_ano=len(self.datas) if self.datas else 73,
        )
        self.ultimo_plano = plano
        return plano.tabela

    def dataset(self) -> Dataset:
        """Extrai os dados e empacota em Dataset com todos os metadados executivos."""
        dados = self.extrair()
        self.validar_schema(dados)
        metadados = {
            "source": self.nome,
            "source_type": self.__class__.__name__,
            "datas": self.datas,
            **(self.ultimo_plano.metricas if self.ultimo_plano else {}),
        }
        return Dataset(dados, metadados)

    def gerar_requisicoes_stac(
        self,
        colecao: str = "sentinel-2-l2a",
        endpoint: str = "https://earth-search.aws.element84.com/v1/search",
    ) -> list[dict[str, Any]]:
        """Monta a lista de payloads de consulta para STAC API / COGs na AWS Open Data."""
        if self.ultimo_plano is None:
            self.extrair()

        requisicoes = []
        bandas_map = {
            "ndvi_scl": ["red", "nir", "scl"],
            "l2a_12": ["blue", "green", "red", "nir", "scl", "swir16", "swir22"],
        }
        bandas_stac = bandas_map.get(self.perfil_bandas, ["red", "nir", "scl"])

        datetime_str = f"{self.datas[0]}/{self.datas[-1]}" if len(self.datas) > 1 else self.datas[0]

        for _, row in self.ultimo_plano.tabela.iterrows():
            bbox = row.get("stac_bbox")
            req = {
                "cell_id": row["id"],
                "municipio": row["nome"],
                "uf": row["uf"],
                "resolucao_alvo_m": row["pixel_m"],
                "endpoint": endpoint,
                "payload": {
                    "collections": [colecao],
                    "bbox": bbox,
                    "datetime": datetime_str,
                    "query": {
                        "eo:cloud_cover": {"lt": 30},
                    },
                },
                "assets_solicitados": bandas_stac,
                "volume_estimado_mb": row["volume_mb"],
            }
            requisicoes.append(req)
        return requisicoes
