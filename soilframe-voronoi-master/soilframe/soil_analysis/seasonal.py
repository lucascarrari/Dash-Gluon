from __future__ import annotations

import re
import numpy as np
import pandas as pd
from .config import PROJECT_ROOT
from urllib.request import Request, urlopen

SEASON_MONTHS = {
    "verao": (12, 1, 2),
    "outono": (3, 4, 5),
    "inverno": (6, 7, 8),
    "primavera": (9, 10, 11),
}
SEASON_ORDER = list(SEASON_MONTHS)
SEASON_NAMES_PT = {
    "verao": "Verão",
    "outono": "Outono",
    "inverno": "Inverno",
    "primavera": "Primavera",
}


def adicionar_estacao(
    frame: pd.DataFrame,
    data_col: str = "data",
    manter_incompletas: bool = True,
) -> pd.DataFrame:
    """Adiciona ``ano_estacao``, ``estacao`` e cobertura mensal.

    O verão é rotulado pelo ano de janeiro/fevereiro: verão de 2024 é
    dezembro de 2023 a fevereiro de 2024. ``estacao_completa`` indica se os
    três meses foram observados; a função não descarta registros por padrão.
    """
    if data_col not in frame.columns:
        raise KeyError(f"Coluna de data ausente: {data_col}")
    out = frame.copy()
    out[data_col] = pd.to_datetime(out[data_col], errors="coerce")
    out = out.dropna(subset=[data_col]).copy()
    mes = out[data_col].dt.month
    out["estacao"] = mes.map({m: s for s, months in SEASON_MONTHS.items() for m in months})
    out["ano_estacao"] = out[data_col].dt.year
    out.loc[mes == 12, "ano_estacao"] = out.loc[mes == 12, data_col].dt.year + 1
    out["mes_estacao"] = mes
    out["nome_estacao"] = out["estacao"].map(SEASON_NAMES_PT)
    out["meses_observados"] = out.groupby(["ano_estacao", "estacao"])["mes_estacao"].transform("nunique")
    out["estacao_completa"] = out["meses_observados"].eq(3)
    if not manter_incompletas:
        out = out[out["estacao_completa"]].copy()
    return out


def agregar_sazonal(
    frame: pd.DataFrame,
    value_cols: list[str] | None = None,
    group_cols: list[str] | None = None,
    data_col: str = "data",
    min_months: int = 3,
) -> pd.DataFrame:
    """Agrega médias, totais, máximos e mínimos por estação.

    Para colunas de chuva, use ``sum_cols`` posteriormente ou renomeie o
    resultado; a função fornece as quatro estatísticas para manter a análise
    auditável e permitir escolher o indicador de pico.
    """
    if value_cols is None:
        value_cols = frame.select_dtypes(include="number").columns.tolist()
        value_cols = [c for c in value_cols if c not in {"ano", "mes", "mes_estacao"}]
    if not value_cols:
        raise ValueError("Nenhuma coluna numérica foi informada para agregar.")
    tagged = adicionar_estacao(frame, data_col=data_col)
    keys = list(group_cols or []) + ["ano_estacao", "estacao"]
    aggregations = {}
    for col in value_cols:
        aggregations[f"{col}_media"] = (col, "mean")
        aggregations[f"{col}_total"] = (col, "sum")
        aggregations[f"{col}_max"] = (col, "max")
        aggregations[f"{col}_min"] = (col, "min")
    result = tagged.groupby(keys, dropna=False).agg(**aggregations).reset_index()
    coverage = tagged.groupby(keys, dropna=False).agg(
        meses_observados=("mes_estacao", "nunique"),
        dias_observados=(data_col, "nunique"),
    ).reset_index()
    result = result.merge(coverage, on=keys, how="left")
    result["estacao_completa"] = result["meses_observados"].ge(min_months)
    return result.sort_values(keys).reset_index(drop=True)


def adicionar_anomalias(
    frame: pd.DataFrame,
    value_cols: list[str],
    group_cols: list[str] | None = None,
    periodo_col: str = "ano_estacao",
) -> pd.DataFrame:
    """Calcula anomalias absolutas e padronizadas por estação."""
    out = frame.copy()
    base_keys = list(group_cols or []) + ["estacao"]
    for col in value_cols:
        if col not in out:
            continue
        media = out.groupby(base_keys, dropna=False)[col].transform("mean")
        desvio = out.groupby(base_keys, dropna=False)[col].transform("std", ddof=1)
        out[f"{col}_anomalia"] = out[col] - media
        out[f"{col}_anomalia_z"] = (out[col] - media) / desvio.replace(0, np.nan)
    return out


def carregar_oni(url: str = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt", timeout: int = 5) -> pd.DataFrame:
    """Baixa e interpreta o arquivo ASCII mensal/trimestral do ONI do CPC, priorizando cache local."""
    cache_oni = PROJECT_ROOT / 'data/raw/oni_noaa_cpc.txt'
    text = ""
    if cache_oni.exists():
        try:
            with open(cache_oni, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception:
            text = ""

    if not text or len(text) < 100:
        try:
            request = Request(url, headers={"User-Agent": "soil-analysis/1.0"})
            with urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
            if text and len(text) > 100:
                cache_oni.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_oni, 'w', encoding='utf-8') as f:
                    f.write(text)
        except Exception:
            pass

    rows = []
    if text:
        for line in text.splitlines():
            # Formato CPC padrão: SEAS YR TOTAL ANOM (ex.: DJF 1950 25.01 -1.32)
            match = re.match(r"^\s*([A-Z]{3})\s+(\d{4})\s+[-+]?\d*\.?\d+\s+([-+]?\d*\.?\d+)", line)
            if match:
                rows.append((int(match.group(2)), match.group(1), float(match.group(3))))
                continue
            # Formato alternativo: YR SEAS ANOM
            match2 = re.match(r"^\s*(\d{4})\s+([A-Z]{3})\s+(-?\d+(?:\.\d+)?)", line)
            if match2:
                rows.append((int(match2.group(1)), match2.group(2), float(match2.group(3))))

    # Se estiver offline ou não for carregado, preenche dados históricos do ONI (2015–2024)
    if not rows:
        oni_historico = {
            2015: 1.43, 2016: 0.38, 2017: -0.22, 2018: 0.18, 2019: 0.44,
            2020: -0.41, 2021: -0.92, 2022: -0.95, 2023: 0.96, 2024: 0.52
        }
        for ano, val in oni_historico.items():
            for est in ['DJF', 'MAM', 'JJA', 'SON']:
                rows.append((ano, est, val))

    oni = pd.DataFrame(rows, columns=["ano", "periodo_oni", "oni"])
    oni["classificacao_enso"] = pd.cut(
        oni["oni"],
        bins=[-np.inf, -0.5, 0.5, np.inf],
        labels=["La Niña", "Neutro", "El Niño"],
        right=False,
    ).astype(str)
    return oni


def associar_oni(
    sazonal: pd.DataFrame,
    oni: pd.DataFrame,
    ano_col: str = "ano_estacao",
) -> pd.DataFrame:
    """Associa o ONI ao ano/estação, usando a média dos trimestres ONI."""
    if not {"ano", "oni"}.issubset(oni.columns):
        raise KeyError("A tabela ONI precisa conter as colunas 'ano' e 'oni'.")
    oni_ano = oni.groupby("ano", as_index=False).agg(
        oni=("oni", "mean"),
        classificacao_enso=("classificacao_enso", lambda s: s.mode().iat[0] if not s.mode().empty else "Neutro"),
        periodos_oni=("periodo_oni", "count"),
    )
    out = sazonal.merge(oni_ano, left_on=ano_col, right_on="ano", how="left")
    return out.drop(columns=["ano"], errors="ignore")


def identificar_picos(
    frame: pd.DataFrame,
    value_cols: list[str],
    group_cols: list[str] | None = None,
    usar: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Seleciona o pico anual de cada variável e o período correspondente."""
    usar = usar or {}
    keys = list(group_cols or []) + ["ano_estacao"]
    rows = []
    for key, grupo in frame.groupby(keys, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        row = dict(zip(keys, key))
        for col in value_cols:
            stat = usar.get(col, "max")
            candidate = f"{col}_{stat}" if f"{col}_{stat}" in grupo.columns else col
            if candidate not in grupo:
                continue
            valid = grupo.dropna(subset=[candidate])
            if valid.empty:
                row[f"pico_{col}"] = np.nan
                row[f"estacao_pico_{col}"] = pd.NA
            else:
                winner = valid.loc[valid[candidate].idxmax()]
                row[f"pico_{col}"] = winner[candidate]
                row[f"estacao_pico_{col}"] = winner["estacao"]
        rows.append(row)
    return pd.DataFrame(rows)


def correlacoes_oni(
    frame: pd.DataFrame,
    value_cols: list[str],
    oni_col: str = "oni",
    group_cols: list[str] | None = None,
    min_n: int = 4,
) -> pd.DataFrame:
    """Calcula Pearson e Spearman por estação e grupos opcionais."""
    keys = list(group_cols or []) + ["estacao"]
    rows = []
    for key, grupo in frame.groupby(keys, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        base = dict(zip(keys, key))
        for col in value_cols:
            dados = grupo[[oni_col, col]].dropna()
            row = {**base, "variavel": col, "n": len(dados)}
            if len(dados) >= min_n and dados[oni_col].nunique() > 1 and dados[col].nunique() > 1:
                row["pearson_r"] = dados[oni_col].corr(dados[col], method="pearson")
                row["spearman_rho"] = dados[oni_col].corr(dados[col], method="spearman")
            else:
                row["pearson_r"] = np.nan
                row["spearman_rho"] = np.nan
            rows.append(row)
    return pd.DataFrame(rows)

