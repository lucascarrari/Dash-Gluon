"""Funções auxiliares para o notebook de análise de solos.

Processa catálogos, cache e NetCDFs Copernicus de SWI e LST.
"""

import os
import s3fs
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
from shapely import wkt
from pathlib import Path
from rasterio.features import rasterize
from rasterio.transform import from_origin

from .config import (
    CDSE_S3_ENDPOINT,
    CRS_METRICO,
    HORA_LST,
    LST_CACHE_DIR,
    LST_CATALOG_V1,
    LST_CATALOG_V3,
    LST_PERIODO_ROTULO,
    METODO_LST_SOLO,
    METODO_SWI_SOLO,
    PERIODO_LST,
    PERIODO_SWI,
    SWI_CACHE_DIR,
    SWI_PERIODO_ROTULO,
    VARIAVEL_LST,
    VARIAVEL_SWI,
)
from .plotting import classificar_swi, filtrar_tipos_pedologicos, formatar_tamanho_bytes


COLUNAS_SWI_GDF = [
    'swi_010_media',
    'swi_010_min',
    'swi_010_max',
    'swi_classe',
    'swi_pontos',
    'swi_tiles',
    'swi_periodo',
    'swi_variavel',
    'swi_metodo',
]


def normalizar_s3_path_eodata(s3_path):
    if pd.isna(s3_path):
        return s3_path
    path = str(s3_path).strip()
    if not path.startswith('s3://'):
        return path
    partes = path[5:].split('/', 1)
    if len(partes) == 1:
        return 's3://eodata'
    return f's3://eodata/{partes[1].lstrip("/")}'


def credenciais_cdse_configuradas():
    return bool(os.environ.get('CDSE_S3_ACCESS_KEY') and os.environ.get('CDSE_S3_SECRET_KEY'))


def criar_s3_filesystem_cdse():
    if not credenciais_cdse_configuradas():
        return None

    kwargs = {
        'endpoint_url': CDSE_S3_ENDPOINT,
        'key': os.environ['CDSE_S3_ACCESS_KEY'],
        'secret': os.environ['CDSE_S3_SECRET_KEY'],
    }
    token = os.environ.get('CDSE_S3_SESSION_TOKEN')
    if token:
        kwargs['token'] = token
    return s3fs.S3FileSystem(anon=False, **kwargs)


def carregar_catalogo_swi(path, estados_brasil):
    if not path.exists():
        raise FileNotFoundError(
            f'{path} não encontrado. Baixe o catálogo do produto SWI da Copernicus e coloque em data/raw/.'
        )

    catalogo = pd.read_csv(path, sep=';', encoding='utf-8-sig')
    colunas_obrigatorias = {'id', 'name', 'content_length', 'content_date_start', 'content_date_end', 'nominal_date', 's3_path', 'bbox'}
    ausentes = colunas_obrigatorias.difference(catalogo.columns)
    if ausentes:
        raise ValueError(f'Colunas ausentes no catálogo SWI: {sorted(ausentes)}')

    for col in ['ingestion_date', 'content_date_start', 'content_date_end', 'nominal_date', 'modification_date']:
        if col in catalogo.columns:
            catalogo[col] = pd.to_datetime(catalogo[col], errors='coerce')
    catalogo['content_length'] = pd.to_numeric(catalogo['content_length'], errors='coerce')
    catalogo['content_length_mb'] = catalogo['content_length'].apply(formatar_tamanho_bytes)
    catalogo['geometry'] = catalogo['bbox'].apply(wkt.loads)
    catalogo['s3_path_normalizado'] = catalogo['s3_path'].apply(normalizar_s3_path_eodata)
    catalogo['s3_netcdf_path'] = catalogo.apply(caminho_s3_netcdf_swi, axis=1)
    catalogo['tile_id'] = catalogo['name'].astype(str).str.extract(r'_C(\d+)_', expand=False)

    catalogo_gdf = gpd.GeoDataFrame(catalogo, geometry='geometry', crs='EPSG:4326')
    estados_wgs84 = estados_brasil.to_crs('EPSG:4326')
    brasil_geom = estados_wgs84.geometry.union_all() if hasattr(estados_wgs84.geometry, 'union_all') else estados_wgs84.geometry.unary_union

    tiles_brasil = catalogo_gdf[catalogo_gdf.geometry.intersects(brasil_geom)].copy()
    if not tiles_brasil.empty:
        tiles_brasil['area_tile_km2'] = (tiles_brasil.to_crs(CRS_METRICO).geometry.area / 1_000_000).round(2)

    return catalogo_gdf, tiles_brasil


def nome_arquivo_netcdf_swi(nome_tile):
    nome = str(nome_tile).strip()
    if nome.endswith('.nc'):
        return nome
    if nome.endswith('_nc'):
        return f'{nome[:-3]}.nc'
    return f'{nome}.nc'


def caminho_cache_swi(nome_tile):
    nome_seguro = nome_arquivo_netcdf_swi(nome_tile).replace('/', '_').replace('\\', '_')
    return SWI_CACHE_DIR / nome_seguro


def localizar_netcdf_local(nome_tile):
    candidatos = [
        caminho_cache_swi(nome_tile),
        SWI_CACHE_DIR / str(nome_tile).replace('/', '_').replace('\\', '_'),
        SWI_CACHE_DIR / f'{str(nome_tile).replace("/", "_").replace(chr(92), "_")}.nc',
    ]
    for candidato in candidatos:
        if candidato.exists() and candidato.stat().st_size > 0:
            return candidato
    return None


def caminho_s3_netcdf_swi(row):
    s3_base = str(row['s3_path_normalizado']).rstrip('/')
    nome_nc = nome_arquivo_netcdf_swi(row['name'])
    if s3_base.endswith('.nc'):
        return s3_base
    return f'{s3_base}/{nome_nc}'


def adicionar_status_cache_swi(tiles):
    tiles = tiles.copy()
    cache_paths = []
    disponiveis = []
    for _, row in tiles.iterrows():
        local = localizar_netcdf_local(row['name'])
        if local is None:
            local = caminho_cache_swi(row['name'])
            disponivel = False
        else:
            disponivel = True
        cache_paths.append(local.as_posix())
        disponiveis.append(disponivel)
    tiles['cache_path'] = cache_paths
    tiles['netcdf_local_disponivel'] = disponiveis
    return tiles


def baixar_tile_swi(row, fs):
    SWI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = Path(row['cache_path'])
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path, 'cache'
    if fs is None:
        raise PermissionError('NetCDF ausente no cache local e credenciais CDSE não configuradas.')

    fs.get(row['s3_netcdf_path'], local_path.as_posix())
    if not local_path.exists() or local_path.stat().st_size == 0:
        raise FileNotFoundError(f'Download não criou o arquivo local esperado: {local_path}')
    return local_path, 'baixado'


def extrair_media_swi_tile(local_path, row):
    with xr.open_dataset(local_path, mask_and_scale=True, decode_times=True) as ds:
        if VARIAVEL_SWI not in ds.variables:
            variaveis = ', '.join(sorted(ds.data_vars))
            raise KeyError(f'{VARIAVEL_SWI} não existe em {row["name"]}. Variáveis disponíveis: {variaveis}')
        for coord in ['lon', 'lat']:
            if coord not in ds.variables:
                raise ValueError(f'Coordenada {coord} não encontrada em {row["name"]}.')

        da = ds[VARIAVEL_SWI]
        time_dim = next((dim for dim in da.dims if dim.lower() == 'time'), None)
        if time_dim is None:
            raise ValueError(f'Dimensão temporal não encontrada em {row["name"]}. Dimensões: {da.dims}')
        loc_dim = next((dim for dim in da.dims if dim.lower() in ['locations', 'location']), None)
        if loc_dim is None:
            loc_dim = next((dim for dim in da.dims if dim != time_dim), None)
        if loc_dim is None:
            raise ValueError(f'Dimensão espacial não encontrada em {row["name"]}. Dimensões: {da.dims}')

        datas = pd.to_datetime(ds[time_dim].values, errors='coerce')
        indices_periodo = np.where((datas.year >= PERIODO_SWI[0]) & (datas.year <= PERIODO_SWI[1]))[0]
        if len(indices_periodo) == 0:
            return pd.DataFrame(columns=['lon', 'lat', 'swi_010_media', 'location_id', 'name', 's3_path'])

        da_periodo = da.isel({time_dim: indices_periodo})
        da_periodo = da_periodo.where((da_periodo >= 0) & (da_periodo <= 100))
        media = da_periodo.mean(dim=time_dim, skipna=True).load()
        if media.ndim != 1:
            raise ValueError(
                f'Formato espacial não suportado em {row["name"]}. Esperado vetor por localização; obtido {media.dims}.'
            )

        lon = np.asarray(ds['lon'].values).reshape(-1)
        lat = np.asarray(ds['lat'].values).reshape(-1)
        valores = np.asarray(media.values).reshape(-1)
        if not (len(lon) == len(lat) == len(valores)):
            raise ValueError(f'Tamanhos incompatíveis de lon/lat/{VARIAVEL_SWI} em {row["name"]}.')

        pontos = pd.DataFrame({
            'lon': lon,
            'lat': lat,
            'swi_010_media': valores,
        })
        if 'location_id' in ds.variables and ds['location_id'].size == len(pontos):
            pontos['location_id'] = np.asarray(ds['location_id'].values).reshape(-1)
        else:
            pontos['location_id'] = pd.NA

    pontos = pontos.dropna(subset=['lon', 'lat', 'swi_010_media']).copy()
    pontos['name'] = row['name']
    pontos['s3_path'] = row['s3_path_normalizado']
    pontos['swi_periodo'] = SWI_PERIODO_ROTULO
    pontos['swi_variavel'] = VARIAVEL_SWI
    return pontos


def carregar_pontos_swi(tiles_brasil):
    vazio = gpd.GeoDataFrame(columns=['swi_010_media', 'geometry'], geometry='geometry', crs='EPSG:4326')
    if tiles_brasil.empty:
        return vazio, pd.DataFrame()

    fs = criar_s3_filesystem_cdse()
    tem_credenciais = fs is not None
    tem_cache = bool(tiles_brasil['netcdf_local_disponivel'].any())
    if not tem_cache and not tem_credenciais:
        print(
            'Nenhum NetCDF SWI disponível: coloque os .nc em data/swi_nc ou configure CDSE_S3_ACCESS_KEY/CDSE_S3_SECRET_KEY. '
            'Nesta execução serão geradas apenas as saídas de cobertura do catálogo.'
        )
        return vazio, pd.DataFrame()

    if not tem_credenciais:
        faltantes = int((~tiles_brasil['netcdf_local_disponivel']).sum())
        if faltantes:
            print(f'{faltantes} tiles sem NetCDF local serão ignorados.')

    partes = []
    falhas = []
    candidatos = tiles_brasil if tem_credenciais else tiles_brasil[tiles_brasil['netcdf_local_disponivel']]
    for _, row in candidatos.sort_values('name').iterrows():
        try:
            local_path, origem = baixar_tile_swi(row, fs)
            pontos_tile = extrair_media_swi_tile(local_path, row)
            if not pontos_tile.empty:
                pontos_tile['origem_arquivo'] = origem
                partes.append(pontos_tile)
            print(f'{row["name"]}: {len(pontos_tile):,} pontos SWI ({origem}).'.replace(',', '.'))
        except KeyError:
            raise
        except Exception as exc:
            falhas.append({'name': row['name'], 's3_path': row.get('s3_netcdf_path', row['s3_path_normalizado']), 'erro': str(exc)})
            print(f'Falha ao processar {row["name"]}: {exc}')

    falhas_df = pd.DataFrame(falhas)
    if not partes:
        return vazio, falhas_df

    pontos = pd.concat(partes, ignore_index=True)
    pontos_gdf = gpd.GeoDataFrame(
        pontos,
        geometry=gpd.points_from_xy(pontos['lon'], pontos['lat']),
        crs='EPSG:4326',
    )
    return pontos_gdf, falhas_df


def vincular_swi_por_solo(gdf_solos, pontos_swi):
    gdf_base = gdf_solos.drop(columns=COLUNAS_SWI_GDF, errors='ignore').copy()
    gdf_base['solo_id_swi'] = gdf_base.index

    if pontos_swi.empty:
        for col in ['swi_010_media', 'swi_010_min', 'swi_010_max']:
            gdf_base[col] = pd.NA
        gdf_base['swi_classe'] = 'sem dados'
        gdf_base['swi_pontos'] = 0
        gdf_base['swi_tiles'] = 0
        gdf_base['swi_periodo'] = SWI_PERIODO_ROTULO
        gdf_base['swi_variavel'] = VARIAVEL_SWI
        gdf_base['swi_metodo'] = 'sem_netcdf_swi_processado'
        return gdf_base.drop(columns='solo_id_swi')

    solos_metricos = gdf_base[['solo_id_swi', 'geometry']].to_crs(CRS_METRICO).copy()
    pontos_metricos = pontos_swi[['name', 'swi_010_media', 'geometry']].to_crs(CRS_METRICO).copy()
    solos_metricos['geometry'] = solos_metricos.geometry.make_valid()
    pontos_solo = gpd.sjoin(pontos_metricos, solos_metricos, how='inner', predicate='within')

    swi_por_poligono = (
        pontos_solo.groupby('solo_id_swi', dropna=False)
        .agg(
            swi_010_media=('swi_010_media', 'mean'),
            swi_010_min=('swi_010_media', 'min'),
            swi_010_max=('swi_010_media', 'max'),
            swi_pontos=('swi_010_media', 'size'),
            swi_tiles=('name', 'nunique'),
        )
        .reset_index()
    )

    for col in ['swi_010_media', 'swi_010_min', 'swi_010_max']:
        swi_por_poligono[col] = swi_por_poligono[col].round(1)

    gdf_base = gdf_base.merge(swi_por_poligono, on='solo_id_swi', how='left')
    gdf_base['swi_classe'] = gdf_base['swi_010_media'].apply(classificar_swi)
    gdf_base['swi_pontos'] = gdf_base['swi_pontos'].fillna(0).round(0).astype('Int64')
    gdf_base['swi_tiles'] = gdf_base['swi_tiles'].fillna(0).round(0).astype('Int64')
    gdf_base['swi_periodo'] = SWI_PERIODO_ROTULO
    gdf_base['swi_variavel'] = VARIAVEL_SWI
    gdf_base['swi_metodo'] = METODO_SWI_SOLO
    gdf_base.loc[gdf_base['swi_010_media'].isna(), 'swi_metodo'] = 'sem_pontos_swi_no_poligono'
    return gdf_base.drop(columns='solo_id_swi')


def resumir_swi_ponderado(gdf_swi, group_cols):
    base = gdf_swi.dropna(subset=['swi_010_media', 'area_km2']).copy()
    base = base[base['area_km2'] > 0].copy()
    if base.empty:
        return pd.DataFrame()

    base['swi_area'] = base['swi_010_media'] * base['area_km2']
    resumo = (
        base.groupby(group_cols, dropna=False)
        .agg(
            area_km2=('area_km2', 'sum'),
            swi_area=('swi_area', 'sum'),
            poligonos_com_swi=('swi_010_media', 'size'),
            pontos_swi=('swi_pontos', 'sum'),
        )
        .reset_index()
    )
    resumo['swi_010_media_ponderada'] = resumo['swi_area'] / resumo['area_km2']
    resumo = resumo.drop(columns='swi_area')
    resumo['area_km2'] = resumo['area_km2'].round(0).astype('Int64')
    resumo['swi_010_media_ponderada'] = resumo['swi_010_media_ponderada'].round(1)
    resumo['swi_classe'] = resumo['swi_010_media_ponderada'].apply(classificar_swi)
    resumo['pontos_swi'] = resumo['pontos_swi'].fillna(0).round(0).astype('Int64')
    resumo['swi_periodo'] = SWI_PERIODO_ROTULO
    resumo['swi_variavel'] = VARIAVEL_SWI
    resumo['swi_metodo'] = METODO_SWI_SOLO
    return resumo.sort_values('swi_010_media_ponderada', ascending=False)


COLUNAS_LST_GDF = [
    'lst_celsius_tipo_media',
    'lst_periodo',
    'lst_hora_utc',
    'lst_variavel',
    'lst_metodo',
]


def nome_arquivo_netcdf_lst(nome_item):
    nome = str(nome_item).strip()
    if nome.endswith('.nc'):
        return nome
    if nome.endswith('_nc'):
        return f'{nome[:-3]}.nc'
    return f'{nome}.nc'


def caminho_cache_lst(nome_item):
    nome_seguro = nome_arquivo_netcdf_lst(nome_item).replace('/', '_').replace('\\', '_')
    return LST_CACHE_DIR / nome_seguro


def localizar_netcdf_lst_local(nome_item):
    candidatos = [
        caminho_cache_lst(nome_item),
        LST_CACHE_DIR / str(nome_item).replace('/', '_').replace('\\', '_'),
        LST_CACHE_DIR / f'{str(nome_item).replace("/", "_").replace(chr(92), "_")}.nc',
    ]
    for candidato in candidatos:
        if candidato.exists() and candidato.stat().st_size > 0:
            return candidato
    return None


def caminho_s3_netcdf_lst(row):
    s3_base = str(row['s3_path_normalizado']).rstrip('/')
    nome_nc = nome_arquivo_netcdf_lst(row['name'])
    if s3_base.endswith('.nc'):
        return s3_base
    return f'{s3_base}/{nome_nc}'


def carregar_catalogo_lst(path):
    if not path.exists():
        raise FileNotFoundError(
            f'{path} não encontrado. Baixe o catálogo LST da Copernicus e coloque em data/raw/.'
        )

    catalogo = pd.read_csv(path, sep=';', encoding='utf-8-sig')
    colunas_obrigatorias = {'id', 'name', 'content_length', 'content_date_start', 'content_date_end', 'nominal_date', 's3_path', 'bbox'}
    ausentes = colunas_obrigatorias.difference(catalogo.columns)
    if ausentes:
        raise ValueError(f'Colunas ausentes no catálogo LST: {sorted(ausentes)}')

    for col in ['ingestion_date', 'content_date_start', 'content_date_end', 'nominal_date', 'modification_date']:
        if col in catalogo.columns:
            catalogo[col] = pd.to_datetime(catalogo[col], errors='coerce')
    catalogo['content_length'] = pd.to_numeric(catalogo['content_length'], errors='coerce')
    catalogo['content_length_mb'] = catalogo['content_length'].apply(formatar_tamanho_bytes)
    catalogo['geometry'] = catalogo['bbox'].apply(wkt.loads)
    catalogo['s3_path_normalizado'] = catalogo['s3_path'].apply(normalizar_s3_path_eodata)
    catalogo['s3_netcdf_path'] = catalogo.apply(caminho_s3_netcdf_lst, axis=1)
    catalogo_gdf = gpd.GeoDataFrame(catalogo, geometry='geometry', crs='EPSG:4326')

    periodo = catalogo_gdf[
        catalogo_gdf['nominal_date'].dt.year.between(PERIODO_LST[0], PERIODO_LST[1])
        & (catalogo_gdf['nominal_date'].dt.hour == HORA_LST)
    ].copy()
    periodo = periodo.sort_values('nominal_date').reset_index(drop=True)

    cache_paths = []
    disponiveis = []
    for _, row in periodo.iterrows():
        local = localizar_netcdf_lst_local(row['name'])
        if local is None:
            local = caminho_cache_lst(row['name'])
            disponivel = False
        else:
            disponivel = True
        cache_paths.append(local.as_posix())
        disponiveis.append(disponivel)
    periodo['cache_path'] = cache_paths
    periodo['netcdf_local_disponivel'] = disponiveis
    return catalogo_gdf, periodo


def carregar_catalogo_lst_unificado(
    path_v1=LST_CATALOG_V1,
    path_v3=LST_CATALOG_V3,
    anos_v1=(2015, 2018),
    anos_v3=(2019, 2024),
    hora=HORA_LST,
):
    """Carrega o catálogo unificado de LST: 2015-2018 da V1 (5km) e 2019-2024 da V3 (3km)."""
    partes_gdf = []
    partes_periodo = []

    # 1. Carregar 2015-2018 da Versão 1 (5km COG/NC)
    if Path(path_v1).exists():
        cat_v1 = pd.read_csv(path_v1, sep=';', encoding='utf-8-sig')
        for col in ['ingestion_date', 'content_date_start', 'content_date_end', 'nominal_date', 'modification_date']:
            if col in cat_v1.columns:
                cat_v1[col] = pd.to_datetime(cat_v1[col], errors='coerce')
        cat_v1['content_length'] = pd.to_numeric(cat_v1.get('content_length'), errors='coerce')
        cat_v1['geometry'] = cat_v1['bbox'].apply(wkt.loads)
        cat_v1['s3_path_normalizado'] = cat_v1['s3_path'].apply(normalizar_s3_path_eodata)
        cat_v1['s3_netcdf_path'] = cat_v1.apply(caminho_s3_netcdf_lst, axis=1)
        cat_v1['versao_lst'] = 'v1_5km'
        cat_v1_gdf = gpd.GeoDataFrame(cat_v1, geometry='geometry', crs='EPSG:4326')

        sub_v1 = cat_v1_gdf[
            cat_v1_gdf['nominal_date'].dt.year.between(anos_v1[0], anos_v1[1])
            & (cat_v1_gdf['nominal_date'].dt.hour == hora)
        ].copy()
        partes_gdf.append(cat_v1_gdf)
        partes_periodo.append(sub_v1)

    # 2. Carregar 2019-2024 da Versão 3 (3km NC)
    if Path(path_v3).exists():
        cat_v3 = pd.read_csv(path_v3, sep=';', encoding='utf-8-sig')
        for col in ['ingestion_date', 'content_date_start', 'content_date_end', 'nominal_date', 'modification_date']:
            if col in cat_v3.columns:
                cat_v3[col] = pd.to_datetime(cat_v3[col], errors='coerce')
        cat_v3['content_length'] = pd.to_numeric(cat_v3.get('content_length'), errors='coerce')
        cat_v3['geometry'] = cat_v3['bbox'].apply(wkt.loads)
        cat_v3['s3_path_normalizado'] = cat_v3['s3_path'].apply(normalizar_s3_path_eodata)
        cat_v3['s3_netcdf_path'] = cat_v3.apply(caminho_s3_netcdf_lst, axis=1)
        cat_v3['versao_lst'] = 'v3_3km'
        cat_v3_gdf = gpd.GeoDataFrame(cat_v3, geometry='geometry', crs='EPSG:4326')

        sub_v3 = cat_v3_gdf[
            cat_v3_gdf['nominal_date'].dt.year.between(anos_v3[0], anos_v3[1])
            & (cat_v3_gdf['nominal_date'].dt.hour == hora)
        ].copy()
        partes_gdf.append(cat_v3_gdf)
        partes_periodo.append(sub_v3)

    if not partes_periodo:
        raise FileNotFoundError('Nenhum catálogo LST encontrado para os períodos informados.')

    catalogo_unificado_gdf = gpd.GeoDataFrame(pd.concat(partes_gdf, ignore_index=True), crs='EPSG:4326')
    periodo_unificado = gpd.GeoDataFrame(pd.concat(partes_periodo, ignore_index=True), crs='EPSG:4326')
    periodo_unificado = periodo_unificado.sort_values('nominal_date').reset_index(drop=True)

    cache_paths = []
    disponiveis = []
    for _, row in periodo_unificado.iterrows():
        local = localizar_netcdf_lst_local(row['name'])
        if local is None:
            local = caminho_cache_lst(row['name'])
            disponivel = False
        else:
            disponivel = True
        cache_paths.append(local.as_posix())
        disponiveis.append(disponivel)

    periodo_unificado['cache_path'] = cache_paths
    periodo_unificado['netcdf_local_disponivel'] = disponiveis
    return catalogo_unificado_gdf, periodo_unificado


def baixar_arquivo_lst(row, fs):
    LST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = Path(row['cache_path'])
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path, 'cache'
    if fs is None:
        raise PermissionError('NetCDF LST ausente no cache local e credenciais CDSE não configuradas.')

    fs.get(row['s3_netcdf_path'], local_path.as_posix())
    if not local_path.exists() or local_path.stat().st_size == 0:
        raise FileNotFoundError(f'Download não criou o arquivo local esperado: {local_path}')
    return local_path, 'baixado'


def bounds_brasil_wgs84(estados_brasil, padding=0.15):
    minx, miny, maxx, maxy = estados_brasil.to_crs('EPSG:4326').total_bounds
    return (minx - padding, miny - padding, maxx + padding, maxy + padding)


def slice_coord_lste(coord, minimo, maximo):
    valores = np.asarray(coord.values)
    if valores[0] <= valores[-1]:
        return slice(minimo, maximo)
    return slice(maximo, minimo)


def ler_lst_recorte_brasil(local_path, bounds):
    minx, miny, maxx, maxy = bounds
    with xr.open_dataset(local_path, mask_and_scale=True, decode_times=True) as ds:
        if VARIAVEL_LST not in ds.variables:
            variaveis = ', '.join(sorted(ds.data_vars))
            raise KeyError(f'{VARIAVEL_LST} não existe em {local_path.name}. Variáveis disponíveis: {variaveis}')
        for coord in ['lon', 'lat']:
            if coord not in ds.variables:
                raise ValueError(f'Coordenada {coord} não encontrada em {local_path.name}.')

        da = ds[VARIAVEL_LST]
        if 'time' in da.dims:
            da = da.isel(time=0)
        da = da.sel(
            lon=slice_coord_lste(ds['lon'], minx, maxx),
            lat=slice_coord_lste(ds['lat'], miny, maxy),
        )
        if da.sizes.get('lat', 0) == 0 or da.sizes.get('lon', 0) == 0:
            raise ValueError(f'Recorte do Brasil vazio em {local_path.name}.')

        if float(da['lat'].values[0]) < float(da['lat'].values[-1]):
            da = da.sortby('lat', ascending=False)
        if float(da['lon'].values[0]) > float(da['lon'].values[-1]):
            da = da.sortby('lon')

        valores_k = np.asarray(da.load().values, dtype='float32')
        validos = np.isfinite(valores_k) & (valores_k > 150) & (valores_k < 380)
        valores_c = np.where(validos, valores_k - 273.15, np.nan).astype('float32')
        lats = np.asarray(da['lat'].values, dtype='float64')
        lons = np.asarray(da['lon'].values, dtype='float64')
    return valores_c, lats, lons


def processar_lst_media_brasil(catalogo_periodo, estados_brasil):
    if catalogo_periodo.empty:
        return None, None, None, pd.DataFrame(), pd.DataFrame()

    fs = criar_s3_filesystem_cdse()
    tem_credenciais = fs is not None
    tem_cache = bool(catalogo_periodo['netcdf_local_disponivel'].any())
    if not tem_cache and not tem_credenciais:
        print(
            'Nenhum NetCDF LST disponível: coloque os .nc em data/lst_nc ou configure CDSE_S3_ACCESS_KEY/CDSE_S3_SECRET_KEY. '
            'Nesta execução serão geradas apenas as saídas de catálogo LST.'
        )
        return None, None, None, pd.DataFrame(), pd.DataFrame()

    candidatos = catalogo_periodo if tem_credenciais else catalogo_periodo[catalogo_periodo['netcdf_local_disponivel']]
    if not tem_credenciais:
        faltantes = int((~catalogo_periodo['netcdf_local_disponivel']).sum())
        if faltantes:
            print(f'{faltantes} arquivos LST sem NetCDF local serão ignorados.')

    bounds = bounds_brasil_wgs84(estados_brasil)
    soma = None
    contagem = None
    lats_ref = None
    lons_ref = None
    processados = []
    falhas = []
    total = len(candidatos)

    for posicao, (_, row) in enumerate(candidatos.iterrows(), start=1):
        try:
            local_path, origem = baixar_arquivo_lst(row, fs)
            valores_c, lats, lons = ler_lst_recorte_brasil(local_path, bounds)
            if soma is None:
                soma = np.zeros(valores_c.shape, dtype='float64')
                contagem = np.zeros(valores_c.shape, dtype='uint16')
                lats_ref = lats
                lons_ref = lons
            elif valores_c.shape != soma.shape or not np.allclose(lats, lats_ref) or not np.allclose(lons, lons_ref):
                raise ValueError(f'Grade LST diferente da grade acumulada em {row["name"]}.')

            mask = np.isfinite(valores_c)
            soma[mask] += valores_c[mask]
            contagem[mask] += 1
            processados.append({
                'name': row['name'],
                'nominal_date': row['nominal_date'],
                'origem_arquivo': origem,
                'pixels_validos': int(mask.sum()),
            })
            if posicao == 1 or posicao % 25 == 0 or posicao == total:
                print(f'LST {posicao}/{total}: {row["nominal_date"]} ({origem}, {int(mask.sum()):,} pixels válidos)'.replace(',', '.'))
        except Exception as exc:
            falhas.append({'name': row['name'], 'nominal_date': row['nominal_date'], 's3_path': row['s3_netcdf_path'], 'erro': str(exc)})
            print(f'Falha ao processar LST {row["name"]}: {exc}')

    if soma is None:
        return None, None, None, pd.DataFrame(processados), pd.DataFrame(falhas)

    media = np.full(soma.shape, np.nan, dtype='float32')
    validos = contagem > 0
    media[validos] = (soma[validos] / contagem[validos]).astype('float32')
    return media, lats_ref, lons_ref, pd.DataFrame(processados), pd.DataFrame(falhas)


def rasterizar_tipos_solo_lst(gdf_solos, lats, lons):
    solos = filtrar_tipos_pedologicos(gdf_solos).dropna(subset=['tipo_solo_principal']).copy().to_crs('EPSG:4326')
    solos['geometry'] = solos.geometry.make_valid()
    tipos = sorted(solos['tipo_solo_principal'].astype(str).unique())
    tipo_para_id = {tipo: i + 1 for i, tipo in enumerate(tipos)}
    id_para_tipo = {i: tipo for tipo, i in tipo_para_id.items()}
    solos['tipo_solo_id_lst'] = solos['tipo_solo_principal'].astype(str).map(tipo_para_id)

    dx = float(abs(np.nanmedian(np.diff(lons))))
    dy = float(abs(np.nanmedian(np.diff(lats))))
    transform = from_origin(float(lons.min() - dx / 2), float(lats.max() + dy / 2), dx, dy)
    shapes = [
        (geom, int(tipo_id))
        for geom, tipo_id in zip(solos.geometry, solos['tipo_solo_id_lst'])
        if geom is not None and not geom.is_empty and pd.notna(tipo_id)
    ]
    raster_tipos = rasterize(
        shapes,
        out_shape=(len(lats), len(lons)),
        transform=transform,
        fill=0,
        dtype='int32',
        all_touched=True,
    )
    return raster_tipos, id_para_tipo


def agregar_lst_por_tipo_solo(lst_media_c, lats, lons, gdf_solos, arquivos_processados):
    if lst_media_c is None or lats is None or lons is None:
        return pd.DataFrame()

    raster_tipos, id_para_tipo = rasterizar_tipos_solo_lst(gdf_solos, lats, lons)
    pesos_lat = np.cos(np.deg2rad(lats)).astype('float64')[:, None]
    pesos = np.broadcast_to(pesos_lat, lst_media_c.shape)
    validos = np.isfinite(lst_media_c) & (raster_tipos > 0)
    if not validos.any():
        return pd.DataFrame()

    area_tipo = (
        filtrar_tipos_pedologicos(gdf_solos)
        .dropna(subset=['area_km2'])
        .groupby('tipo_solo_principal', dropna=False)['area_km2']
        .sum()
        .rename('area_km2')
        .reset_index()
    )

    linhas = []
    for tipo_id in sorted(np.unique(raster_tipos[validos])):
        mask = validos & (raster_tipos == tipo_id)
        if not mask.any():
            continue
        valores = lst_media_c[mask].astype('float64')
        pesos_tipo = pesos[mask]
        linhas.append({
            'tipo_solo_principal': id_para_tipo[int(tipo_id)],
            'pixels_lst': int(mask.sum()),
            'lst_celsius_media': float(np.average(valores, weights=pesos_tipo)),
            'lst_celsius_min_pixel': float(np.nanmin(valores)),
            'lst_celsius_max_pixel': float(np.nanmax(valores)),
            'arquivos_lst_processados': int(arquivos_processados),
            'lst_periodo': LST_PERIODO_ROTULO,
            'lst_hora_utc': HORA_LST,
            'lst_variavel': VARIAVEL_LST,
            'lst_metodo': METODO_LST_SOLO,
        })

    resumo = pd.DataFrame(linhas)
    resumo = resumo.merge(area_tipo, on='tipo_solo_principal', how='left')
    resumo['area_km2'] = resumo['area_km2'].round(0).astype('Int64')
    for col in ['lst_celsius_media', 'lst_celsius_min_pixel', 'lst_celsius_max_pixel']:
        resumo[col] = resumo[col].round(1)
    return resumo.sort_values('lst_celsius_media', ascending=False)


def vincular_lst_tipo_ao_gdf(gdf_solos, lst_por_tipo):
    gdf_base = gdf_solos.drop(columns=COLUNAS_LST_GDF, errors='ignore').copy()
    if lst_por_tipo.empty:
        gdf_base['lst_celsius_tipo_media'] = pd.NA
        gdf_base['lst_periodo'] = LST_PERIODO_ROTULO
        gdf_base['lst_hora_utc'] = HORA_LST
        gdf_base['lst_variavel'] = VARIAVEL_LST
        gdf_base['lst_metodo'] = 'sem_netcdf_lst_processado'
        return gdf_base

    cols = ['tipo_solo_principal', 'lst_celsius_media']
    gdf_base = gdf_base.merge(lst_por_tipo[cols], on='tipo_solo_principal', how='left')
    gdf_base = gdf_base.rename(columns={'lst_celsius_media': 'lst_celsius_tipo_media'})
    gdf_base['lst_periodo'] = LST_PERIODO_ROTULO
    gdf_base['lst_hora_utc'] = HORA_LST
    gdf_base['lst_variavel'] = VARIAVEL_LST
    gdf_base['lst_metodo'] = METODO_LST_SOLO
    gdf_base.loc[gdf_base['lst_celsius_tipo_media'].isna(), 'lst_metodo'] = 'sem_lst_para_tipo_solo'
    return gdf_base
