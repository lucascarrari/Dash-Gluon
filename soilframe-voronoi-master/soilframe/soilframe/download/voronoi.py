from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable
import numpy as np
import pandas as pd

from .base import EstrategiaDownload, PlanoDownload

PIXELS_M = [10, 20, 30, 60, 100, 250, 500, 1000, 2500, 5000]

PERFIS_BANDAS = {
    # 12 bandas espectrais do Sentinel-2 L2A uint16
    "l2a_12": [(10, 4, 2), (20, 6, 2), (60, 2, 2)],
    # FAO-56 com Kc do NDVI: B4 e B8 (uint16) + SCL (uint8, nuvem)
    "ndvi_scl": [(10, 2, 2), (20, 1, 1)],
}

R_KM = 6371.0088
LAT1, LAT2, LAT0, LON0 = -2.0, -22.0, -12.0, -54.0

_p1, _p2, _p0, _l0 = np.radians([LAT1, LAT2, LAT0, LON0])
_n = (np.sin(_p1) + np.sin(_p2)) / 2
_C = np.cos(_p1) ** 2 + 2 * _n * np.sin(_p1)
_r0 = np.sqrt(_C - 2 * _n * np.sin(_p0)) / _n

LIMIAR_PUREZA = 0.5


def albers(lon: Any, lat: Any) -> tuple[np.ndarray, np.ndarray]:
    """Converte lon/lat em graus para coordenadas x/y planas em km (Albers equivalente)."""
    lon_rad = np.radians(np.asarray(lon, float))
    lat_rad = np.radians(np.asarray(lat, float))
    r = R_KM * np.sqrt(np.maximum(0, _C - 2 * _n * np.sin(lat_rad))) / _n
    t = _n * (lon_rad - _l0)
    return r * np.sin(t), R_KM * _r0 - r * np.cos(t)


def albers_inv(x_km: Any, y_km: Any) -> tuple[np.ndarray, np.ndarray]:
    """Converte coordenadas planas Albers (km) de volta para lon/lat em graus."""
    x = np.asarray(x_km, float)
    y = np.asarray(y_km, float)
    yd = y - R_KM * _r0
    theta = np.arctan2(-x, yd)
    r = np.hypot(x, yd)
    q = (_C - (r * _n / R_KM) ** 2) / (2 * _n)
    q = np.clip(q, -1.0, 1.0)
    lat = np.degrees(np.arcsin(q))
    lon = np.degrees(theta / _n) + LON0
    return lon, lat



def bytes_km2(r_m: float, perfil: str = "ndvi_scl", fator_compressao: float = 1.0) -> float:
    """Bytes por km² por data com pixel r; bandas mais finas que r são agregadas para r."""
    bandas = PERFIS_BANDAS.get(perfil, PERFIS_BANDAS["ndvi_scl"])
    b_total = sum(n * b * 1e6 / max(r_m, nat) ** 2 for nat, n, b in bandas)
    return b_total * fator_compressao


def max_overlap_1d(a: np.ndarray, b: np.ndarray, s: float) -> np.ndarray:
    ia, ib = np.floor(a / s), np.floor(b / s)
    first = np.where(ia == ib, b - a, (ia + 1) * s - a)
    last = np.where(ia == ib, 0.0, b - ib * s)
    inner = np.where(ib - ia >= 2, s, 0.0)
    return np.maximum.reduce([first, last, inner])


def _gerar_tabela_visibilidade(limiar: float = LIMIAR_PUREZA, n: int = 20000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    rho = np.logspace(-2, 2.5, 400)
    p = []
    for q in rho:
        ux, uy = rng.uniform(0, 1, n), rng.uniform(0, 1, n)
        ox, oy = max_overlap_1d(ux, ux + q, 1.0), max_overlap_1d(uy, uy + q, 1.0)
        p.append(np.mean(ox * oy >= limiar))
    return rho, np.array(p)


_RHO, _PV = _gerar_tabela_visibilidade()


def p_visivel(l_m: Any, r_m: float) -> np.ndarray:
    """Probabilidade de pureza de pixel >= limiar para talhão de lado l_m e pixel r_m."""
    return np.interp(np.log(np.asarray(l_m) / r_m), np.log(_RHO), _PV, left=0.0, right=1.0)


def perfil_celula(area_ha: Any, pesos: Any = None) -> tuple[list[float], list[float]]:
    """Calcula a fração visível por pixel (contagem e área) dado um array de áreas de talhões em ha."""
    a = np.asarray(area_ha, float)
    w = np.ones_like(a) if pesos is None else np.asarray(pesos, float)
    l_lado = np.sqrt(a) * 100.0  # lado equivalente em m
    vn, va = [], []
    for r in PIXELS_M:
        p = p_visivel(l_lado, r)
        vn.append(float((p * w).sum() / w.sum()))
        va.append(float((p * a * w).sum() / (a * w).sum()))
    return vn, va


class EstrategiaDownloadVoronoi(EstrategiaDownload):
    """Estratégia de download adaptativo baseada em células de Voronoi e otimização Lagrangiana.
    
    Escolhe a resolução ótima de pixel (10m a 5km) para cada célula espacial,
    maximizando a área de talhões agrícolas visíveis para um determinado orçamento de dados (GB)
    ou atingindo uma meta de cobertura (ex: 99%) com o menor volume de download possível.
    """

    def __init__(
        self,
        caminho_voronoi: str | Path | None = None,
        caminho_cenario: str | Path | None = None,
        caminho_mascara: str | Path | None = None,
        perfil_bandas: str = "ndvi_scl",
        objetivo: str = "area",
        fator_compressao: float = 1.0,
    ) -> None:
        self.caminho_voronoi = caminho_voronoi
        self.caminho_cenario = caminho_cenario
        self.caminho_mascara = caminho_mascara
        self.perfil_bandas = perfil_bandas
        self.objetivo = objetivo
        self.fator_compressao = fator_compressao
        self._dados_carregados: dict[str, Any] | None = None

    def _localizar_arquivos(self) -> tuple[Path | None, Path | None]:
        candidatos_voronoi = []
        if self.caminho_voronoi:
            candidatos_voronoi.append(Path(self.caminho_voronoi))
        
        env_dir = os.environ.get("AGRO_VORONOI_DATA")
        if env_dir:
            candidatos_voronoi.append(Path(env_dir) / "voronoi.json")
        
        # Caminhos padrão do repositório
        repo_root = Path(__file__).resolve().parents[3]
        candidatos_voronoi.append(repo_root / "soil-estudo-volume-dados" / "data" / "voronoi.json")
        candidatos_voronoi.append(Path("soil-estudo-volume-dados/data/voronoi.json"))
        candidatos_voronoi.append(Path("data/voronoi.json"))

        voronoi_path = next((p for p in candidatos_voronoi if p.exists()), None)

        candidatos_cenario = []
        if self.caminho_cenario:
            candidatos_cenario.append(Path(self.caminho_cenario))
        if voronoi_path:
            v_dir = voronoi_path.parent
            candidatos_cenario.append(v_dir / "cenario.json")
            candidatos_cenario.append(v_dir / "cenario_ftw_2025.json")
            candidatos_cenario.append(v_dir / "cenario_sintetico.json")

        cenario_path = next((p for p in candidatos_cenario if p.exists()), None)
        return voronoi_path, cenario_path

    def carregar_dados(self) -> dict[str, Any]:
        """Carrega células e distribuições de talhões ou gera representação sintética."""
        if self._dados_carregados is not None:
            return self._dados_carregados

        vor_path, cen_path = self._localizar_arquivos()
        if vor_path and cen_path:
            with open(vor_path, encoding="utf-8") as f:
                v_json = json.load(f)
            with open(cen_path, encoding="utf-8") as f:
                c_json = json.load(f)

            celulas_vor = v_json.get("m", [])
            cenario_map = {c["id"]: c for c in c_json.get("celulas", [])}

            # Filtra apenas células presentes em ambos
            celulas = [c for c in celulas_vor if c["id"] in cenario_map]
            v_info = celulas
            a_km2 = np.array([c["a"] for c in celulas], dtype=float)

            if self.caminho_mascara and Path(self.caminho_mascara).exists():
                with open(self.caminho_mascara, encoding="utf-8") as f:
                    am = json.load(f).get("am", {})
                a_custo = np.array([am.get(str(c["id"]), c["a"]) for c in celulas], dtype=float)
            else:
                a_custo = a_km2.copy()

            fa = np.array([cenario_map[c["id"]]["fa"] for c in celulas], dtype=float)
            nf = np.array([cenario_map[c["id"]]["nf"] for c in celulas], dtype=float)
            va = np.array([cenario_map[c["id"]]["va"] for c in celulas], dtype=float)
            vn = np.array([cenario_map[c["id"]]["vn"] for c in celulas], dtype=float)
        else:
            # Fallback sintético regional para funcionamento autocontido
            v_info, a_km2, a_custo, fa, nf, va, vn = self._gerar_dados_sinteticos()

        c_matriz = a_custo[:, None] * np.array([
            bytes_km2(r, self.perfil_bandas, self.fator_compressao) for r in PIXELS_M
        ])[None, :] / 1e9  # em GB

        ga = va * fa[:, None]
        gn = vn * nf[:, None]

        self._dados_carregados = {
            "v_info": v_info,
            "a_km2": a_km2,
            "a_custo": a_custo,
            "c_matriz": c_matriz,
            "fa": fa,
            "nf": nf,
            "va": va,
            "vn": vn,
            "ga": ga,
            "gn": gn,
        }
        return self._dados_carregados

    def _gerar_dados_sinteticos(self) -> tuple[list[dict], np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Cria uma malha regional sintética ilustrativa para testes sem arquivos externos."""
        regioes = [
            ("Centro-Oeste", "MT", "Sorriso", -54.97, -12.55, 9300.0, 200.0, 0.45),
            ("Centro-Oeste", "GO", "Rio Verde", -50.92, -17.79, 8300.0, 150.0, 0.40),
            ("Sul", "PR", "Cascavel", -53.45, -24.95, 2100.0, 18.0, 0.50),
            ("Sul", "RS", "Passo Fundo", -52.40, -28.26, 1600.0, 15.0, 0.48),
            ("Sudeste", "SP", "Ribeirão Preto", -47.81, -21.17, 1500.0, 35.0, 0.55),
            ("Sudeste", "MG", "Uberlândia", -48.27, -18.91, 4100.0, 50.0, 0.40),
            ("Nordeste", "BA", "Luís Eduardo Magalhães", -45.79, -12.09, 4000.0, 180.0, 0.35),
            ("Nordeste", "PE", "Petrolina", -40.50, -9.39, 4500.0, 3.5, 0.15),
            ("Norte", "TO", "Palmas", -48.33, -10.18, 2200.0, 60.0, 0.20),
            ("Norte", "PA", "Santarém", -54.70, -2.44, 18000.0, 40.0, 0.08),
        ]
        v_info = []
        fa_list, nf_list, va_list, vn_list, a_list = [], [], [], [], []
        for i, (reg, uf, nome, lon, lat, area_km2, med_ha, fr_agri) in enumerate(regioes):
            x, y = albers(lon, lat)
            v_info.append({
                "id": 1000 + i,
                "n": nome,
                "u": uf,
                "r": reg,
                "p": [round(float(x), 1), round(float(y), 1)],
                "a": float(area_km2),
            })
            a_list.append(area_km2)
            fa_val = area_km2 * fr_agri
            fa_list.append(fa_val)
            z = np.linspace(-2, 2, 32)
            a_ha = med_ha * np.exp(0.8 * z)
            vn_i, va_i = perfil_celula(a_ha)
            va_list.append(va_i)
            vn_list.append(vn_i)
            nf_list.append(round(fa_val / (med_ha / 100)))

        a_km2 = np.array(a_list, dtype=float)
        return (
            v_info,
            a_km2,
            a_km2.copy(),
            np.array(fa_list, dtype=float),
            np.array(nf_list, dtype=float),
            np.array(va_list, dtype=float),
            np.array(vn_list, dtype=float),
        )

    def otimizar(
        self,
        meta_cobertura: float | None = 0.99,
        orcamento_gb: float | None = None,
        objetivo: str | None = None,
        lambdas: np.ndarray | None = None,
    ) -> tuple[np.ndarray, float, float, float]:
        """Resolve a alocação ótima por célula via relaxação Lagrangiana.
        
        Retorna:
            (indices_pixels, gb_total, cobertura_area, cobertura_talhoes)
        """
        dados = self.carregar_dados()
        obj = objetivo or self.objetivo
        c_mat = dados["c_matriz"]
        fa = dados["fa"]
        nf = dados["nf"]
        ga = dados["ga"]
        gn = dados["gn"]

        g_alvo = ga if obj == "area" else gn
        total_alvo = fa.sum() if obj == "area" else nf.sum()

        if lambdas is None:
            lambdas = np.logspace(6, -12, 720)

        n_celulas = len(dados["v_info"])
        melhor_ch = np.zeros(n_celulas, dtype=int)
        melhor_gb = float("inf")
        melhor_ca = 0.0
        melhor_cn = 0.0

        if orcamento_gb is not None:
            # Maximiza cobertura dentro do orçamento
            max_cob = -1.0
            for lam in lambdas:
                ch = np.argmax(g_alvo / total_alvo - lam * c_mat, axis=1)
                gb = c_mat[np.arange(n_celulas), ch].sum()
                ca = ga[np.arange(n_celulas), ch].sum() / fa.sum()
                cn = gn[np.arange(n_celulas), ch].sum() / nf.sum()
                cob_atual = ca if obj == "area" else cn

                if gb <= orcamento_gb and cob_atual > max_cob:
                    max_cob = cob_atual
                    melhor_ch = ch
                    melhor_gb = gb
                    melhor_ca = ca
                    melhor_cn = cn
            if max_cob < 0:
                # Se nenhum lambda couber, pega o ponto mais econômico (último pixel, 5 km)
                melhor_ch = np.full(n_celulas, len(PIXELS_M) - 1, dtype=int)
                melhor_gb = c_mat[np.arange(n_celulas), melhor_ch].sum()
                melhor_ca = ga[np.arange(n_celulas), melhor_ch].sum() / fa.sum()
                melhor_cn = gn[np.arange(n_celulas), melhor_ch].sum() / nf.sum()
        else:
            # Minimiza volume para atingir meta_cobertura
            meta = meta_cobertura if meta_cobertura is not None else 0.99
            min_gb = float("inf")
            for lam in lambdas:
                ch = np.argmax(g_alvo / total_alvo - lam * c_mat, axis=1)
                gb = c_mat[np.arange(n_celulas), ch].sum()
                ca = ga[np.arange(n_celulas), ch].sum() / fa.sum()
                cn = gn[np.arange(n_celulas), ch].sum() / nf.sum()
                cob_atual = ca if obj == "area" else cn

                if cob_atual >= meta and gb < min_gb:
                    min_gb = gb
                    melhor_ch = ch
                    melhor_gb = gb
                    melhor_ca = ca
                    melhor_cn = cn

            if min_gb == float("inf"):
                # Pega a máxima cobertura possível (pixel mais fino, 10 m)
                melhor_ch = np.zeros(n_celulas, dtype=int)
                melhor_gb = c_mat[np.arange(n_celulas), melhor_ch].sum()
                melhor_ca = ga[np.arange(n_celulas), melhor_ch].sum() / fa.sum()
                melhor_cn = gn[np.arange(n_celulas), melhor_ch].sum() / nf.sum()

        return melhor_ch, float(melhor_gb), float(melhor_ca), float(melhor_cn)

    def gerar_fronteira(self) -> pd.DataFrame:
        """Gera a curva de fronteira Pareto (Volume GB x Cobertura) comparando estratégias."""
        dados = self.carregar_dados()
        c_mat = dados["c_matriz"]
        fa = dados["fa"]
        nf = dados["nf"]
        ga = dados["ga"]
        gn = dados["gn"]
        a_km2 = dados["a_km2"]
        n_celulas = len(dados["v_info"])
        i_idx = np.arange(n_celulas)

        rows = []

        # 1. Estratégia Uniforme
        for k, r in enumerate(PIXELS_M):
            ch = np.full(n_celulas, k)
            gb = c_mat[i_idx, ch].sum()
            ca = ga[i_idx, ch].sum() / fa.sum()
            cn = gn[i_idx, ch].sum() / nf.sum()
            rows.append(("uniforme", r, float(gb), float(ca), float(cn)))

        # 2. Regra heurística por densidade de fazendas (fino em alta densidade, 1 km no restante)
        ordem = np.argsort(-nf / a_km2)
        idx_1km = PIXELS_M.index(1000)
        for fino_m in (10, 30):
            idx_fino = PIXELS_M.index(fino_m)
            for q in np.linspace(0, 1, 21):
                ch = np.full(n_celulas, idx_1km)
                corte = int(round(q * n_celulas))
                ch[ordem[:corte]] = idx_fino
                gb = c_mat[i_idx, ch].sum()
                ca = ga[i_idx, ch].sum() / fa.sum()
                cn = gn[i_idx, ch].sum() / nf.sum()
                rows.append((f"densidade_{fino_m}m", q, float(gb), float(ca), float(cn)))

        # 3. Otimizado Lagrangiano (Área e Talhões)
        lambdas = np.logspace(6, -12, 180)
        for obj_nome, g_mat, total in [("otimo_area", ga, fa.sum()), ("otimo_talhoes", gn, nf.sum())]:
            for lam in lambdas:
                ch = np.argmax(g_mat / total - lam * c_mat, axis=1)
                gb = c_mat[i_idx, ch].sum()
                ca = ga[i_idx, ch].sum() / fa.sum()
                cn = gn[i_idx, ch].sum() / nf.sum()
                rows.append((obj_nome, float(lam), float(gb), float(ca), float(cn)))

        df = pd.DataFrame(rows, columns=["estrategia", "parametro", "gb", "area_visivel", "talhoes_visiveis"])
        return df

    def planejar(
        self,
        meta_cobertura: float | None = 0.99,
        orcamento_gb: float | None = None,
        objetivo: str | None = None,
        perfil_bandas: str | None = None,
        uf: str | Iterable[str] | None = None,
        regiao: str | Iterable[str] | None = None,
        municipios: list[int | str] | None = None,
        datas_por_ano: int = 73,
        **kwargs: Any,
    ) -> PlanoDownload:
        """Gera o plano executivo de download com resoluções ótimas por célula e métricas."""
        if perfil_bandas and perfil_bandas != self.perfil_bandas:
            self.perfil_bandas = perfil_bandas
            self._dados_carregados = None

        if objetivo:
            self.objetivo = objetivo

        dados = self.carregar_dados()
        v_info = dados["v_info"]
        c_mat = dados["c_matriz"]
        a_km2 = dados["a_km2"]
        ga = dados["ga"]
        gn = dados["gn"]
        fa = dados["fa"]
        nf = dados["nf"]

        # Otimização global (ou no subconjunto)
        ch_global, gb_otimo, ca_otimo, cn_otimo = self.otimizar(
            meta_cobertura=meta_cobertura,
            orcamento_gb=orcamento_gb,
            objetivo=self.objetivo,
        )

        # Filtro geográfico
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

        if not indices_validos:
            raise ValueError("Nenhuma célula encontrada para os critérios geográficos informados.")

        idx_arr = np.array(indices_validos)
        ch_sub = ch_global[idx_arr]

        # Montagem da tabela de células
        linhas = []
        for i_sub, i_glob in enumerate(idx_arr):
            info = v_info[i_glob]
            pixel_idx = ch_sub[i_sub]
            pixel_m = PIXELS_M[pixel_idx]
            vol_mb = c_mat[i_glob, pixel_idx] * 1024.0  # GB para MB
            area_cel = a_km2[i_glob]
            cob_a = ga[i_glob, pixel_idx] / fa[i_glob] if fa[i_glob] > 0 else 1.0
            cob_n = gn[i_glob, pixel_idx] / nf[i_glob] if nf[i_glob] > 0 else 1.0

            # Coordenadas centroid/sede
            x_km, y_km = info.get("p", [0.0, 0.0])
            lon, lat = albers_inv(x_km, y_km)

            # Bounding box aproximado em graus a partir da área da célula
            delta_deg = np.sqrt(area_cel) / 111.0 / 2.0
            bbox = [
                round(float(lon - delta_deg), 4),
                round(float(lat - delta_deg), 4),
                round(float(lon + delta_deg), 4),
                round(float(lat + delta_deg), 4),
            ]

            linhas.append({
                "id": info.get("id"),
                "nome": info.get("n", ""),
                "uf": info.get("u", ""),
                "regiao": info.get("r", ""),
                "lat": round(float(lat), 5),
                "lon": round(float(lon), 5),
                "area_km2": round(float(area_cel), 2),
                "pixel_m": pixel_m,
                "volume_mb": round(float(vol_mb), 2),
                "cobertura_area": round(float(cob_a), 4),
                "cobertura_talhoes": round(float(cob_n), 4),
                "stac_bbox": bbox,
            })

        df_tabela = pd.DataFrame(linhas)

        # Métricas de volume e economia do subconjunto
        gb_por_data = float(c_mat[idx_arr, ch_sub].sum())
        gb_ano = gb_por_data * datas_por_ano
        ca_sub = float(ga[idx_arr, ch_sub].sum() / fa[idx_arr].sum()) if fa[idx_arr].sum() > 0 else 1.0
        cn_sub = float(gn[idx_arr, ch_sub].sum() / nf[idx_arr].sum()) if nf[idx_arr].sum() > 0 else 1.0

        # Baseline: melhor pixel uniforme que atinge a meta no subconjunto
        meta_ref = meta_cobertura if meta_cobertura is not None else 0.99
        gb_baseline_uniforme = float("inf")
        pixel_uniforme_escolhido = 10
        for k, r in enumerate(PIXELS_M):
            ch_u = np.full(len(idx_arr), k)
            cob_u = (ga[idx_arr, ch_u].sum() / fa[idx_arr].sum()) if self.objetivo == "area" else (gn[idx_arr, ch_u].sum() / nf[idx_arr].sum())
            if cob_u >= meta_ref:
                gb_u = float(c_mat[idx_arr, ch_u].sum())
                if gb_u < gb_baseline_uniforme:
                    gb_baseline_uniforme = gb_u
                    pixel_uniforme_escolhido = r

        if gb_baseline_uniforme == float("inf"):
            ch_u = np.zeros(len(idx_arr), dtype=int)
            gb_baseline_uniforme = float(c_mat[idx_arr, ch_u].sum())
            pixel_uniforme_escolhido = 10

        gb_tudo_10m = float(c_mat[idx_arr, 0].sum())

        fator_reducao = round(gb_baseline_uniforme / max(gb_por_data, 1e-6), 2)
        fator_reducao_10m = round(gb_tudo_10m / max(gb_por_data, 1e-6), 2)
        economia_gb = round(gb_baseline_uniforme - gb_por_data, 2)

        metricas = {
            "estrategia": "voronoi_adaptativo",
            "perfil_bandas": self.perfil_bandas,
            "objetivo": self.objetivo,
            "meta_cobertura": meta_cobertura,
            "orcamento_gb": orcamento_gb,
            "gb_por_data": round(gb_por_data, 3),
            "gb_ano": round(gb_ano, 2),
            "cobertura_area": round(ca_sub, 4),
            "cobertura_talhoes": round(cn_sub, 4),
            "gb_baseline_uniforme": round(gb_baseline_uniforme, 3),
            "pixel_uniforme_comparativo_m": pixel_uniforme_escolhido,
            "gb_tudo_10m": round(gb_tudo_10m, 2),
            "economia_gb_data": economia_gb,
            "fator_reducao": fator_reducao,
            "fator_reducao_10m": fator_reducao_10m,
            "num_celulas": len(df_tabela),
        }

        return PlanoDownload(tabela=df_tabela, metricas=metricas)

    def estimar_volume(self, plano: PlanoDownload | Any) -> dict[str, Any]:
        """Calcula métricas detalhadas a partir de um plano gerado."""
        if isinstance(plano, PlanoDownload):
            return dict(plano.metricas)
        if hasattr(plano, "metadata"):
            return dict(plano.metadata)
        raise TypeError("Objeto de plano inválido. Esperado PlanoDownload ou Dataset.")
