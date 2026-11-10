"""Funções auxiliares para o notebook de análise de solos.

Carrega chuva observada e vincula precipitação aos polígonos de solo.
"""

import geobr
import calendar
import pandas as pd
import geopandas as gpd
from .config import (
    CHUNK_CHUVA,
    CRS_METRICO,
    DIAS_MINIMOS_ANO_CHUVA,
    METODO_PRECIPITACAO_MUNICIPAL_SOLO,
    PERIODO_CHUVA,
    PRECIPITACAO_PERIODO_ROTULO,
    REGIOES_BR,
)

METODO_ANUALIZACAO_PRECIPITACAO = 'chuva_total_mm_x_dias_no_ano_div_dias_observados'

def classificar_precipitacao(valor_mm):
    if pd.isna(valor_mm):
        return 'sem dados'
    if valor_mm < 900:
        return 'baixa'
    if valor_mm < 1300:
        return 'moderada'
    if valor_mm < 1800:
        return 'alta'
    return 'muito alta'


def carregar_precipitacao_observada(path):
    if not path.exists():
        raise FileNotFoundError(
            f'{path} não encontrado. Coloque o CSV pluvial em data/raw/ para calcular a precipitação observada.'
        )

    usecols = [
        'codigoestacao',
        'data',
        'chuva_mm',
        'Codigo_Municipio_IBGE',
        'Municipio_IBGE',
        'UF_IBGE',
    ]
    partes = []
    for chunk in pd.read_csv(
        path,
        sep=';',
        encoding='utf-8-sig',
        usecols=usecols,
        chunksize=CHUNK_CHUVA,
    ):
        chunk['data'] = pd.to_datetime(chunk['data'], errors='coerce')
        chunk['ano'] = chunk['data'].dt.year
        chunk['chuva_mm'] = pd.to_numeric(chunk['chuva_mm'], errors='coerce')
        chunk['Codigo_Municipio_IBGE'] = pd.to_numeric(chunk['Codigo_Municipio_IBGE'], errors='coerce')
        chunk['UF_IBGE'] = chunk['UF_IBGE'].astype(str).str.strip().str.upper()
        chunk = chunk.dropna(subset=['codigoestacao', 'ano', 'chuva_mm', 'Codigo_Municipio_IBGE', 'UF_IBGE']).copy()
        chunk = chunk[
            chunk['ano'].between(PERIODO_CHUVA[0], PERIODO_CHUVA[1])
            & (chunk['chuva_mm'] >= 0)
        ].copy()
        chunk['Codigo_Municipio_IBGE'] = chunk['Codigo_Municipio_IBGE'].astype('int64')
        partes.append(
            chunk.groupby(
                ['codigoestacao', 'ano', 'Codigo_Municipio_IBGE', 'Municipio_IBGE', 'UF_IBGE'],
                dropna=False,
            )
            .agg(
                dias_observados=('chuva_mm', 'size'),
                chuva_total_mm=('chuva_mm', 'sum'),
            )
            .reset_index()
        )

    if not partes:
        raise ValueError(f'Nenhum registro pluvial foi lido em {path}.')

    estacao_ano = pd.concat(partes, ignore_index=True)
    estacao_ano = (
        estacao_ano.groupby(
            ['codigoestacao', 'ano', 'Codigo_Municipio_IBGE', 'Municipio_IBGE', 'UF_IBGE'],
            dropna=False,
        )
        .agg(
            dias_observados=('dias_observados', 'sum'),
            chuva_total_mm=('chuva_total_mm', 'sum'),
        )
        .reset_index()
    )
    estacao_ano_valida = estacao_ano[estacao_ano['dias_observados'] >= DIAS_MINIMOS_ANO_CHUVA].copy()
    estacao_ano_valida['dias_no_ano'] = estacao_ano_valida['ano'].map(
        lambda ano: 366 if calendar.isleap(int(ano)) else 365
    )
    estacao_ano_valida['precipitacao_anualizada_mm'] = (
        estacao_ano_valida['chuva_total_mm']
        * estacao_ano_valida['dias_no_ano']
        / estacao_ano_valida['dias_observados']
    )
    estacao_ano_valida['precipitacao_anualizada_metodo'] = METODO_ANUALIZACAO_PRECIPITACAO

    estacao_media = (
        estacao_ano_valida.groupby(
            ['codigoestacao', 'Codigo_Municipio_IBGE', 'Municipio_IBGE', 'UF_IBGE'],
            dropna=False,
        )
        .agg(
            anos_validos=('ano', 'nunique'),
            precipitacao_media_anual_mm=('chuva_total_mm', 'mean'),
            precipitacao_anualizada_media_mm=('precipitacao_anualizada_mm', 'mean'),
            dias_medios_observados=('dias_observados', 'mean'),
        )
        .reset_index()
    )
    estacao_media['precipitacao_anualizada_metodo'] = METODO_ANUALIZACAO_PRECIPITACAO

    municipio = (
        estacao_media.groupby(['Codigo_Municipio_IBGE', 'Municipio_IBGE', 'UF_IBGE'], dropna=False)
        .agg(
            estacoes=('codigoestacao', 'nunique'),
            anos_estacao_validos=('anos_validos', 'sum'),
            precipitacao_anual_media_mm=('precipitacao_media_anual_mm', 'mean'),
            precipitacao_anualizada_media_mm=('precipitacao_anualizada_media_mm', 'mean'),
            dias_medios_observados=('dias_medios_observados', 'mean'),
        )
        .reset_index()
        .sort_values(['UF_IBGE', 'Municipio_IBGE'])
    )

    uf = (
        estacao_media.groupby('UF_IBGE', dropna=False)
        .agg(
            estacoes=('codigoestacao', 'nunique'),
            municipios=('Codigo_Municipio_IBGE', 'nunique'),
            anos_estacao_validos=('anos_validos', 'sum'),
            precipitacao_anual_media_mm=('precipitacao_media_anual_mm', 'mean'),
            precipitacao_anualizada_media_mm=('precipitacao_anualizada_media_mm', 'mean'),
            dias_medios_observados=('dias_medios_observados', 'mean'),
        )
        .reset_index()
        .sort_values('precipitacao_anual_media_mm', ascending=False)
    )

    municipio['precipitacao_metodo'] = 'media_estacao_anual_por_municipio'
    uf['precipitacao_metodo'] = 'media_estacao_anual_por_uf'
    for tabela in [municipio, uf]:
        tabela['precipitacao_anual_media_mm'] = tabela['precipitacao_anual_media_mm'].round(1)
        tabela['precipitacao_anualizada_media_mm'] = tabela['precipitacao_anualizada_media_mm'].round(1)
        tabela['dias_medios_observados'] = tabela['dias_medios_observados'].round(1)
        tabela['precipitacao_periodo'] = PRECIPITACAO_PERIODO_ROTULO
        tabela['dias_minimos_ano'] = DIAS_MINIMOS_ANO_CHUVA
        tabela['precipitacao_anualizada_metodo'] = METODO_ANUALIZACAO_PRECIPITACAO

    return estacao_ano_valida, estacao_media, municipio, uf

COLUNAS_PRECIPITACAO_GDF = [
    'codigo_municipio_predominante',
    'municipio_predominante',
    'municipios_intersectados',
    'area_municipios_intersectados_km2',
    'area_municipal_com_chuva_km2',
    'municipios_com_dados_pluviais',
    'estacoes_pluviais',
    'dias_medios_observados',
    'dias_minimos_ano',
    'precipitacao_anual_media_mm',
    'precipitacao_anualizada_media_mm',
    'precipitacao_anualizada_metodo',
    'precipitacao_classe',
    'precipitacao_periodo',
    'precipitacao_metodo',
    'estacoes',
    'municipios',
    'anos_estacao_validos',
]


def carregar_municipios_geobr():
    municipios = geobr.read_municipality(year=2020, simplified=True, show_progress=False)
    codigo_col = next(c for c in ['code_muni', 'cod_muni', 'CD_MUN', 'CD_GEOCMU'] if c in municipios.columns)
    nome_col = next(c for c in ['name_muni', 'nome_muni', 'NM_MUN', 'NM_MUNICIP'] if c in municipios.columns)
    uf_col = next(c for c in ['abbrev_state', 'sigla_uf', 'SIGLA_UF', 'UF'] if c in municipios.columns)
    estado_col = next(c for c in ['name_state', 'nome_estado', 'NM_UF', 'NM_ESTADO'] if c in municipios.columns)
    regiao_col = next((c for c in ['name_region', 'nome_regiao', 'NM_REGIAO'] if c in municipios.columns), None)

    municipios = municipios.rename(
        columns={
            codigo_col: 'Codigo_Municipio_IBGE',
            nome_col: 'Municipio_IBGE_geobr',
            uf_col: 'UF_IBGE',
            estado_col: 'estado_nome_geobr',
        }
    )
    municipios['Codigo_Municipio_IBGE'] = pd.to_numeric(municipios['Codigo_Municipio_IBGE'], errors='coerce')
    municipios = municipios.dropna(subset=['Codigo_Municipio_IBGE']).copy()
    municipios['Codigo_Municipio_IBGE'] = municipios['Codigo_Municipio_IBGE'].astype('int64')
    municipios['UF_IBGE'] = municipios['UF_IBGE'].astype(str).str.strip().str.upper()
    municipios['regiao_nome_municipio'] = municipios['UF_IBGE'].map(REGIOES_BR)
    if regiao_col:
        municipios['regiao_nome_municipio'] = municipios[regiao_col].fillna(municipios['regiao_nome_municipio'])

    return municipios[
        [
            'Codigo_Municipio_IBGE',
            'Municipio_IBGE_geobr',
            'UF_IBGE',
            'estado_nome_geobr',
            'regiao_nome_municipio',
            'geometry',
        ]
    ]


def vincular_precipitacao_por_municipio(gdf_solos, precipitacao_municipal):
    gdf_base = gdf_solos.drop(columns=COLUNAS_PRECIPITACAO_GDF, errors='ignore').copy()
    gdf_base['solo_id_precip'] = gdf_base.index

    municipios = carregar_municipios_geobr()
    solos_metricos = gdf_base[['solo_id_precip', 'geometry']].to_crs(CRS_METRICO).copy()
    municipios_metricos = municipios.to_crs(CRS_METRICO).copy()
    solos_metricos['geometry'] = solos_metricos.geometry.make_valid()
    municipios_metricos['geometry'] = municipios_metricos.geometry.make_valid()

    intersecoes_municipio = gpd.overlay(
        solos_metricos,
        municipios_metricos,
        how='intersection',
        keep_geom_type=False,
    )
    intersecoes_municipio['area_intersecao_km2'] = intersecoes_municipio.geometry.area / 1_000_000
    intersecoes_municipio = intersecoes_municipio[intersecoes_municipio['area_intersecao_km2'] > 0].copy()

    municipio_predominante = (
        intersecoes_municipio
        .sort_values('area_intersecao_km2', ascending=False)
        .drop_duplicates('solo_id_precip')
        [[
            'solo_id_precip',
            'Codigo_Municipio_IBGE',
            'Municipio_IBGE_geobr',
            'regiao_nome_municipio',
        ]]
        .rename(
            columns={
                'Codigo_Municipio_IBGE': 'codigo_municipio_predominante',
                'Municipio_IBGE_geobr': 'municipio_predominante',
            }
        )
    )
    municipio_contagem = (
        intersecoes_municipio.groupby('solo_id_precip')
        .agg(
            municipios_intersectados=('Codigo_Municipio_IBGE', 'nunique'),
            area_municipios_intersectados_km2=('area_intersecao_km2', 'sum'),
        )
        .reset_index()
    )
    municipio_por_solo = municipio_predominante.merge(municipio_contagem, on='solo_id_precip', how='left')

    precip_municipio = precipitacao_municipal[
        [
            'Codigo_Municipio_IBGE',
            'precipitacao_anual_media_mm',
            'precipitacao_anualizada_media_mm',
            'estacoes',
            'dias_medios_observados',
        ]
    ].copy()
    intersecoes_chuva = intersecoes_municipio.merge(precip_municipio, on='Codigo_Municipio_IBGE', how='left')
    intersecoes_chuva = intersecoes_chuva.dropna(subset=['precipitacao_anual_media_mm']).copy()
    intersecoes_chuva['precipitacao_area_mm_km2'] = (
        intersecoes_chuva['precipitacao_anual_media_mm'] * intersecoes_chuva['area_intersecao_km2']
    )
    intersecoes_chuva['precipitacao_anualizada_area_mm_km2'] = (
        intersecoes_chuva['precipitacao_anualizada_media_mm'] * intersecoes_chuva['area_intersecao_km2']
    )
    intersecoes_chuva['dias_area'] = (
        intersecoes_chuva['dias_medios_observados'] * intersecoes_chuva['area_intersecao_km2']
    )

    precipitacao_por_solo = (
        intersecoes_chuva.groupby('solo_id_precip')
        .agg(
            area_municipal_com_chuva_km2=('area_intersecao_km2', 'sum'),
            precipitacao_area_mm_km2=('precipitacao_area_mm_km2', 'sum'),
            precipitacao_anualizada_area_mm_km2=('precipitacao_anualizada_area_mm_km2', 'sum'),
            municipios_com_dados_pluviais=('Codigo_Municipio_IBGE', 'nunique'),
            estacoes_pluviais=('estacoes', 'sum'),
            dias_area=('dias_area', 'sum'),
        )
        .reset_index()
    )
    precipitacao_por_solo['precipitacao_anual_media_mm'] = (
        precipitacao_por_solo['precipitacao_area_mm_km2'] / precipitacao_por_solo['area_municipal_com_chuva_km2']
    )
    precipitacao_por_solo['precipitacao_anualizada_media_mm'] = (
        precipitacao_por_solo['precipitacao_anualizada_area_mm_km2']
        / precipitacao_por_solo['area_municipal_com_chuva_km2']
    )
    precipitacao_por_solo['dias_medios_observados'] = (
        precipitacao_por_solo['dias_area'] / precipitacao_por_solo['area_municipal_com_chuva_km2']
    )
    precipitacao_por_solo = precipitacao_por_solo.drop(
        columns=['precipitacao_area_mm_km2', 'precipitacao_anualizada_area_mm_km2', 'dias_area']
    )

    gdf_base = gdf_base.merge(municipio_por_solo, on='solo_id_precip', how='left')
    gdf_base = gdf_base.merge(precipitacao_por_solo, on='solo_id_precip', how='left')
    gdf_base['regiao_nome'] = (
        gdf_base['estado_sigla'].map(REGIOES_BR)
        .fillna(gdf_base['regiao_nome_municipio'])
        .fillna('não identificado')
    )
    gdf_base = gdf_base.drop(columns='regiao_nome_municipio', errors='ignore')
    gdf_base['precipitacao_anual_media_mm'] = gdf_base['precipitacao_anual_media_mm'].round(1)
    gdf_base['precipitacao_anualizada_media_mm'] = gdf_base['precipitacao_anualizada_media_mm'].round(1)
    gdf_base['dias_medios_observados'] = gdf_base['dias_medios_observados'].round(1)
    gdf_base['area_municipal_com_chuva_km2'] = gdf_base['area_municipal_com_chuva_km2'].round(2)
    gdf_base['area_municipios_intersectados_km2'] = gdf_base['area_municipios_intersectados_km2'].round(2)
    gdf_base['precipitacao_classe'] = gdf_base['precipitacao_anual_media_mm'].apply(classificar_precipitacao)
    gdf_base['precipitacao_periodo'] = PRECIPITACAO_PERIODO_ROTULO
    gdf_base['dias_minimos_ano'] = DIAS_MINIMOS_ANO_CHUVA
    gdf_base['precipitacao_metodo'] = METODO_PRECIPITACAO_MUNICIPAL_SOLO
    gdf_base.loc[gdf_base['precipitacao_anual_media_mm'].isna(), 'precipitacao_metodo'] = 'sem_dados_pluviais_municipais'
    gdf_base['precipitacao_anualizada_metodo'] = METODO_ANUALIZACAO_PRECIPITACAO
    gdf_base.loc[
        gdf_base['precipitacao_anualizada_media_mm'].isna(),
        'precipitacao_anualizada_metodo',
    ] = 'sem_dados_pluviais_municipais'

    for col in ['municipios_intersectados', 'municipios_com_dados_pluviais', 'estacoes_pluviais']:
        gdf_base[col] = gdf_base[col].fillna(0).round(0).astype('Int64')
    gdf_base['codigo_municipio_predominante'] = gdf_base['codigo_municipio_predominante'].astype('Int64')

    return gdf_base.drop(columns='solo_id_precip')
