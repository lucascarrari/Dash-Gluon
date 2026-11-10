from __future__ import annotations

from typing import Any, Iterable
import pandas as pd

from .base import EstrategiaDownload, PlanoDownload
from .voronoi import EstrategiaDownloadVoronoi, PIXELS_M, bytes_km2


class EstrategiaDownloadUniforme(EstrategiaDownload):
    """Estratégia de download com resolução de pixel uniforme em todo o território.
    
    Usada como baseline comparativo para quantificar a economia da estratégia Voronoi.
    """

    def __init__(self, pixel_m: int = 30, perfil_bandas: str = "ndvi_scl") -> None:
        if pixel_m not in PIXELS_M:
            raise ValueError(f"Pixel {pixel_m}m inválido. Opções válidas: {PIXELS_M}")
        self.pixel_m = pixel_m
        self.perfil_bandas = perfil_bandas

    def planejar(
        self,
        uf: str | Iterable[str] | None = None,
        regiao: str | Iterable[str] | None = None,
        municipios: list[int | str] | None = None,
        datas_por_ano: int = 73,
        **kwargs: Any,
    ) -> PlanoDownload:
        # Reutiliza o carregador de células da estratégia Voronoi para consistência espacial
        vor = EstrategiaDownloadVoronoi(perfil_bandas=self.perfil_bandas)
        dados = vor.carregar_dados()
        v_info = dados["v_info"]
        a_km2 = dados["a_km2"]
        ga = dados["ga"]
        gn = dados["gn"]
        fa = dados["fa"]
        nf = dados["nf"]

        pixel_idx = PIXELS_M.index(self.pixel_m)
        b_km2 = bytes_km2(self.pixel_m, self.perfil_bandas)

        indices_validos = list(range(len(v_info)))
        if uf:
            ufs_set = {uf.upper()} if isinstance(uf, str) else {u.upper() for u in uf}
            indices_validos = [i for i in indices_validos if v_info[i].get("u", "").upper() in ufs_set]
        if regiao:
            regs_set = {regiao} if isinstance(regiao, str) else set(regiao)
            indices_validos = [i for i in indices_validos if v_info[i].get("r") in regs_set]
        if municipios:
            muns_set = {int(m) for m in municipios}
            indices_validos = [i for i in indices_validos if int(v_info[i].get("id", 0)) in muns_set]

        linhas = []
        for i in indices_validos:
            info = v_info[i]
            area_cel = a_km2[i]
            vol_mb = (area_cel * b_km2) / 1e6
            cob_a = ga[i, pixel_idx] / fa[i] if fa[i] > 0 else 1.0
            cob_n = gn[i, pixel_idx] / nf[i] if nf[i] > 0 else 1.0

            linhas.append({
                "id": info.get("id"),
                "nome": info.get("n", ""),
                "uf": info.get("u", ""),
                "regiao": info.get("r", ""),
                "area_km2": round(float(area_cel), 2),
                "pixel_m": self.pixel_m,
                "volume_mb": round(float(vol_mb), 2),
                "cobertura_area": round(float(cob_a), 4),
                "cobertura_talhoes": round(float(cob_n), 4),
            })

        df = pd.DataFrame(linhas)
        gb_data = float(df["volume_mb"].sum() / 1024.0)
        idx_arr = list(indices_validos)
        cob_area_total = float(ga[idx_arr, pixel_idx].sum() / fa[idx_arr].sum()) if fa[idx_arr].sum() > 0 else 1.0
        cob_talhoes_total = float(gn[idx_arr, pixel_idx].sum() / nf[idx_arr].sum()) if nf[idx_arr].sum() > 0 else 1.0

        metricas = {
            "estrategia": "uniforme",
            "pixel_m": self.pixel_m,
            "perfil_bandas": self.perfil_bandas,
            "gb_por_data": round(gb_data, 3),
            "gb_ano": round(gb_data * datas_por_ano, 2),
            "cobertura_area": round(cob_area_total, 4),
            "cobertura_talhoes": round(cob_talhoes_total, 4),
            "num_celulas": len(df),
        }
        return PlanoDownload(tabela=df, metricas=metricas)

    def estimar_volume(self, plano: PlanoDownload | Any) -> dict[str, Any]:
        if isinstance(plano, PlanoDownload):
            return dict(plano.metricas)
        if hasattr(plano, "metadata"):
            return dict(plano.metadata)
        raise TypeError("Objeto de plano inválido. Esperado PlanoDownload ou Dataset.")
