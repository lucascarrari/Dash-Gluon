from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import pandas as pd

from ..core.dataset import Dataset
from ..core.strategy import EstrategiaDownload


@dataclass
class PlanoDownload:
    """Representa o resultado de um planejamento de download."""

    tabela: pd.DataFrame
    metricas: dict[str, Any] = field(default_factory=dict)

    def to_dataset(self) -> Dataset:
        """Converte o plano em um Dataset padrão do SoilFrame."""
        metadata = {
            "source_type": "download_plan",
            **self.metricas,
        }
        return Dataset(self.tabela.copy(), metadata=metadata)

    def resumo_regional(self) -> pd.DataFrame:
        """Agrega métricas por região geográfica."""
        if "regiao" not in self.tabela.columns:
            return pd.DataFrame()
        
        agg_dict = {
            "id": "count",
            "area_km2": "sum",
            "volume_mb": "sum",
            "pixel_m": "median",
        }
        if "cobertura_area" in self.tabela.columns:
            agg_dict["cobertura_area"] = "mean"

        resumo = self.tabela.groupby("regiao").agg(agg_dict).reset_index()
        resumo = resumo.rename(
            columns={
                "id": "num_celulas",
                "pixel_m": "pixel_mediano_m",
                "volume_mb": "volume_total_mb",
                "area_km2": "area_total_km2",
            }
        )
        resumo["gb_total"] = (resumo["volume_total_mb"] / 1024.0).round(2)
        return resumo

    def resumo_executivo(self) -> str:
        """Gera um resumo textual executivo dos ganhos e alocação do plano."""
        m = self.metricas
        estrategia = m.get("estrategia", "voronoi")
        perfil = m.get("perfil_bandas", "ndvi_scl")
        gb_data = m.get("gb_por_data", 0.0)
        gb_ano = m.get("gb_ano", 0.0)
        cobertura = m.get("cobertura_area", 0.0)
        baseline = m.get("gb_baseline_uniforme", 0.0)
        fator = m.get("fator_reducao", 1.0)
        n_celulas = len(self.tabela)

        linhas = [
            f"=== Resumo Executivo: Estratégia de Download ({estrategia.upper()}) ===",
            f"- Células planejadas: {n_celulas:,}",
            f"- Perfil espectral: {perfil} (FAO-56/NDVI)",
            f"- Cobertura de área agrícola estimada: {cobertura:.1%}",
            f"- Volume por data de imagem: {gb_data:.2f} GB",
            f"- Volume anual estimado (73 datas): {gb_ano:.1f} GB",
            f"- Linha de base (pixel uniforme): {baseline:.2f} GB por data",
            f"- Fator de economia: {fator:.1f}x menos dados baixados",
        ]
        return "\n".join(linhas)
