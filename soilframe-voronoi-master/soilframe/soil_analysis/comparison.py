"""Reusable data preparation and comparison helpers for the notebooks."""

import geobr
import calendar
import numpy as np
import pandas as pd
from shapely import wkt
import geopandas as gpd
from pathlib import Path
from .config import (
    CODIGOS_AGUA_COSTEIRA,
    CRS_DADOS,
    CRS_METRICO,
    DATA,
    LST_CATALOG,
    PERIODO_CHUVA,
    PLUVIAL_DATA,
    REGIOES_BR,
    SWI_CATALOG,
    TIPOS_NAO_PEDOLOGICOS_GRAFICOS,
)
from .copernicus import (
    adicionar_status_cache_swi,
    agregar_lst_por_tipo_solo,
    carregar_catalogo_lst,
    carregar_catalogo_swi,
    carregar_pontos_swi,
    processar_lst_media_brasil,
    vincular_lst_tipo_ao_gdf,
    vincular_swi_por_solo,
)
from .precipitation import (
    carregar_precipitacao_observada,
    vincular_precipitacao_por_municipio,
)


COLUNA_TIPO_SOLO = "tipo_solo_principal"


def _exigir_colunas(df, colunas, contexto):
    ausentes = set(colunas).difference(df.columns)
    if ausentes:
        raise ValueError(f"Colunas ausentes em {contexto}: {sorted(ausentes)}")


def _carregar_estados():
    estados = geobr.read_state(year=2020, simplified=False, show_progress=False)
    nome = next(
        (col for col in ["name_state", "nome", "NM_UF", "NM_ESTADO"] if col in estados.columns),
        None,
    )
    sigla = next(
        (col for col in ["abbrev_state", "sigla_uf", "SIGLA_UF", "UF"] if col in estados.columns),
        None,
    )
    if nome is None or sigla is None:
        raise ValueError(
            "A malha estadual do geobr nao contem colunas reconhecidas de nome e sigla."
        )

    estados = estados.rename(columns={nome: "estado_nome", sigla: "estado_sigla"})
    return estados[["estado_nome", "estado_sigla", "geometry"]].copy()


def carregar_solos_com_geografia(data_path=DATA):
    """Load soils and assign each polygon to its dominant state intersection.

    Returns
    -------
    tuple[geopandas.GeoDataFrame, geopandas.GeoDataFrame]
        The prepared soil polygons and the normalized state boundaries.
    """

    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(
            f"{data_path} nao encontrado. Coloque a base de solos em data/raw/."
        )

    df = pd.read_csv(data_path, encoding="utf-8-sig")
    _exigir_colunas(df, ["WKT", "COD_SIMBOL", COLUNA_TIPO_SOLO], str(data_path))
    try:
        geometrias = df["WKT"].map(wkt.loads)
    except Exception as exc:
        raise ValueError(f"Geometria WKT invalida em {data_path}: {exc}") from exc

    gdf_original = gpd.GeoDataFrame(
        df.drop(columns="WKT"),
        geometry=geometrias,
        crs=CRS_DADOS,
    )
    gdf = gdf_original[
        ~gdf_original["COD_SIMBOL"].isin(CODIGOS_AGUA_COSTEIRA)
    ].copy()
    gdf = gdf.reset_index(drop=True)
    estados = _carregar_estados()

    gdf["solo_id_geografia"] = np.arange(len(gdf), dtype="int64")
    solos_metricos = gdf[["solo_id_geografia", "geometry"]].to_crs(CRS_METRICO)
    estados_metricos = estados.to_crs(CRS_METRICO)
    solos_metricos = solos_metricos.copy()
    estados_metricos = estados_metricos.copy()
    solos_metricos["geometry"] = solos_metricos.geometry.make_valid()
    estados_metricos["geometry"] = estados_metricos.geometry.make_valid()

    intersecoes = gpd.overlay(
        solos_metricos,
        estados_metricos,
        how="intersection",
        keep_geom_type=False,
    )
    intersecoes["area_intersecao_km2"] = intersecoes.geometry.area / 1_000_000
    intersecoes = intersecoes[intersecoes["area_intersecao_km2"] > 0].copy()
    estado_por_solo = (
        intersecoes.sort_values(
            ["solo_id_geografia", "area_intersecao_km2", "estado_sigla"],
            ascending=[True, False, True],
        )
        .drop_duplicates("solo_id_geografia")
        [["solo_id_geografia", "estado_nome", "estado_sigla"]]
    )

    gdf = gdf.merge(estado_por_solo, on="solo_id_geografia", how="left")
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=CRS_DADOS)
    gdf["estado_nome"] = gdf["estado_nome"].fillna("nao identificado")
    gdf["estado_sigla"] = gdf["estado_sigla"].fillna("nao identificado")
    gdf["regiao_nome"] = (
        gdf["estado_sigla"].map(REGIOES_BR).fillna("nao identificado")
    )

    geometrias_metricas = gdf[["geometry"]].to_crs(CRS_METRICO).copy()
    geometrias_metricas["geometry"] = geometrias_metricas.geometry.make_valid()
    gdf["area_km2"] = geometrias_metricas.geometry.area.to_numpy() / 1_000_000
    gdf = gdf.drop(columns="solo_id_geografia")
    return gdf, estados


def preparar_indicadores_ambientais(gdf, estados):
    """Run the real precipitation, SWI and LST pipelines without simulation."""

    _exigir_colunas(
        gdf,
        [COLUNA_TIPO_SOLO, "estado_sigla", "regiao_nome", "area_km2", "geometry"],
        "gdf de solos",
    )
    if not isinstance(gdf, gpd.GeoDataFrame) or gdf.crs is None:
        raise ValueError("gdf deve ser um GeoDataFrame com CRS definido.")
    if not isinstance(estados, gpd.GeoDataFrame) or estados.crs is None:
        raise ValueError("estados deve ser um GeoDataFrame com CRS definido.")

    (
        estacao_ano_chuva,
        estacao_media_chuva,
        precipitacao_por_municipio,
        precipitacao_por_estado,
    ) = carregar_precipitacao_observada(PLUVIAL_DATA)
    gdf_indicadores = vincular_precipitacao_por_municipio(
        gdf.copy(), precipitacao_por_municipio
    )

    swi_catalogo, swi_tiles_brasil = carregar_catalogo_swi(SWI_CATALOG, estados)
    swi_tiles_brasil = adicionar_status_cache_swi(swi_tiles_brasil)
    pontos_swi, swi_falhas = carregar_pontos_swi(swi_tiles_brasil)
    gdf_indicadores = vincular_swi_por_solo(gdf_indicadores, pontos_swi)

    lst_catalogo, lst_catalogo_periodo = carregar_catalogo_lst(LST_CATALOG)
    (
        lst_media_brasil_c,
        lst_lats,
        lst_lons,
        lst_processados,
        lst_falhas,
    ) = processar_lst_media_brasil(lst_catalogo_periodo, estados)
    lst_por_tipo = agregar_lst_por_tipo_solo(
        lst_media_brasil_c,
        lst_lats,
        lst_lons,
        gdf_indicadores,
        arquivos_processados=len(lst_processados),
    )
    gdf_indicadores = vincular_lst_tipo_ao_gdf(gdf_indicadores, lst_por_tipo)

    return {
        "gdf": gdf_indicadores,
        "estacao_ano_chuva": estacao_ano_chuva,
        "estacao_media_chuva": estacao_media_chuva,
        "precipitacao_por_municipio": precipitacao_por_municipio,
        "precipitacao_por_estado": precipitacao_por_estado,
        "swi_catalogo": swi_catalogo,
        "swi_tiles_brasil": swi_tiles_brasil,
        "pontos_swi": pontos_swi,
        "swi_falhas": swi_falhas,
        "swi_status": "processado" if not pontos_swi.empty else "sem_netcdf_swi_processado",
        "lst_catalogo": lst_catalogo,
        "lst_catalogo_periodo": lst_catalogo_periodo,
        "lst_processados": lst_processados,
        "lst_falhas": lst_falhas,
        "lst_por_tipo": lst_por_tipo,
        "lst_status": "processado" if not lst_por_tipo.empty else "sem_netcdf_lst_processado",
    }


def _agregar_indicador(
    resumo,
    base,
    coluna_valor,
    prefixo,
    coluna_saida,
    ponderado_por_area,
):
    valores = pd.to_numeric(base[coluna_valor], errors="coerce")
    validos = np.isfinite(valores)
    dados = base.loc[validos, [COLUNA_TIPO_SOLO, "area_km2"]].copy()
    dados["valor"] = valores.loc[validos].astype("float64")

    area_col = f"area_com_{prefixo}_km2"
    contagem_col = f"poligonos_com_{prefixo}"
    cobertura_col = f"cobertura_{prefixo}_pct"
    if dados.empty:
        resumo[area_col] = 0.0
        resumo[contagem_col] = 0
        resumo[cobertura_col] = 0.0
        resumo[coluna_saida] = np.nan
        return resumo

    grupo = dados.groupby(COLUNA_TIPO_SOLO, sort=False, observed=True)
    cobertura = grupo.agg(
        **{
            area_col: ("area_km2", "sum"),
            contagem_col: ("valor", "size"),
        }
    )
    if ponderado_por_area:
        dados["valor_area"] = dados["valor"] * dados["area_km2"]
        numerador = dados.groupby(
            COLUNA_TIPO_SOLO, sort=False, observed=True
        )["valor_area"].sum()
        cobertura[coluna_saida] = numerador / cobertura[area_col]
    else:
        cobertura[coluna_saida] = grupo["valor"].mean()

    resumo = resumo.join(cobertura, how="left")
    resumo[area_col] = resumo[area_col].fillna(0.0)
    resumo[contagem_col] = resumo[contagem_col].fillna(0).astype("int64")
    resumo[cobertura_col] = np.where(
        resumo["area_km2"] > 0,
        100 * resumo[area_col] / resumo["area_km2"],
        np.nan,
    )
    return resumo


def resumir_indicadores_por_tipo(gdf):
    """Aggregate environmental indicators once per pedological soil type."""

    colunas = [
        COLUNA_TIPO_SOLO,
        "area_km2",
        "estado_sigla",
        "regiao_nome",
        "precipitacao_anual_media_mm",
        "precipitacao_anualizada_media_mm",
        "dias_medios_observados",
        "swi_010_media",
        "lst_celsius_tipo_media",
        "porosidade_estimada_media",
    ]
    _exigir_colunas(gdf, colunas, "gdf com indicadores ambientais")

    base = gdf[colunas].copy()
    base[COLUNA_TIPO_SOLO] = (
        base[COLUNA_TIPO_SOLO].astype("string").str.strip().replace("", pd.NA)
    )
    nao_pedologicos = {str(tipo).strip() for tipo in TIPOS_NAO_PEDOLOGICOS_GRAFICOS}
    base = base[
        base[COLUNA_TIPO_SOLO].notna()
        & ~base[COLUNA_TIPO_SOLO].isin(nao_pedologicos)
    ].copy()
    base["area_km2"] = pd.to_numeric(base["area_km2"], errors="coerce")
    base = base[np.isfinite(base["area_km2"]) & (base["area_km2"] > 0)].copy()
    if base.empty:
        raise ValueError("Nenhum poligono pedologico com area positiva para resumir.")

    resumo = base.groupby(
        COLUNA_TIPO_SOLO, sort=False, observed=True
    ).agg(
        area_km2=("area_km2", "sum"),
        poligonos_total=(COLUNA_TIPO_SOLO, "size"),
        ufs_total=("estado_sigla", "nunique"),
        regioes_total=("regiao_nome", "nunique"),
    )

    especificacoes = [
        (
            "precipitacao_anual_media_mm",
            "precipitacao",
            "precipitacao_media_ponderada_mm",
            True,
        ),
        (
            "precipitacao_anualizada_media_mm",
            "precipitacao_anualizada",
            "precipitacao_anualizada_media_ponderada_mm",
            True,
        ),
        (
            "dias_medios_observados",
            "dias_precipitacao",
            "dias_precipitacao_media_ponderada",
            True,
        ),
        ("swi_010_media", "swi", "swi_010_media_ponderada", True),
        ("lst_celsius_tipo_media", "lst", "lst_celsius_media", False),
        (
            "porosidade_estimada_media",
            "porosidade",
            "porosidade_estimada_media",
            False,
        ),
    ]
    for coluna, prefixo, saida, ponderado in especificacoes:
        resumo = _agregar_indicador(
            resumo,
            base,
            coluna_valor=coluna,
            prefixo=prefixo,
            coluna_saida=saida,
            ponderado_por_area=ponderado,
        )

    anos = range(PERIODO_CHUVA[0], PERIODO_CHUVA[1] + 1)
    dias_calendario = np.mean([366 if calendar.isleap(ano) else 365 for ano in anos])
    resumo["dias_calendario_precipitacao"] = dias_calendario
    resumo["cobertura_temporal_precipitacao_pct"] = (
        100 * resumo["dias_precipitacao_media_ponderada"] / dias_calendario
    ).clip(upper=100)

    return (
        resumo.reset_index()
        .sort_values("area_km2", ascending=False, kind="stable")
        .reset_index(drop=True)
    )


def calcular_balanco_climatico(resumo, et0_resumo):
    """Merge type-level indicators with ET0 and calculate the simple balance."""

    _exigir_colunas(
        resumo,
        [COLUNA_TIPO_SOLO, "precipitacao_anualizada_media_ponderada_mm"],
        "resumo de indicadores",
    )
    _exigir_colunas(
        et0_resumo,
        [COLUNA_TIPO_SOLO, "et0_anual_media_mm"],
        "resumo de ET0",
    )
    if resumo[COLUNA_TIPO_SOLO].duplicated().any():
        raise ValueError("resumo contem tipos de solo duplicados.")
    if et0_resumo[COLUNA_TIPO_SOLO].duplicated().any():
        raise ValueError("et0_resumo contem tipos de solo duplicados.")

    colisoes = (
        set(resumo.columns)
        .intersection(et0_resumo.columns)
        .difference({COLUNA_TIPO_SOLO})
    )
    if colisoes:
        raise ValueError(
            f"Colunas duplicadas entre os resumos: {sorted(colisoes)}"
        )

    resultado = resumo.merge(
        et0_resumo,
        on=COLUNA_TIPO_SOLO,
        how="left",
        validate="one_to_one",
        sort=False,
    )
    precipitacao = pd.to_numeric(
        resultado["precipitacao_anualizada_media_ponderada_mm"], errors="coerce"
    )
    et0 = pd.to_numeric(resultado["et0_anual_media_mm"], errors="coerce")
    resultado["balanco_climatico_mm"] = precipitacao - et0
    resultado["razao_p_et0"] = precipitacao.div(et0.where(et0 > 0))
    resultado["razao_p_et0"] = resultado["razao_p_et0"].replace(
        [np.inf, -np.inf], np.nan
    )
    resultado["precipitacao_usada_balanco"] = (
        "precipitacao_anualizada_media_ponderada_mm"
    )
    return resultado
