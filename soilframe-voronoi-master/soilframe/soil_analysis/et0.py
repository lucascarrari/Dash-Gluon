"""Download, validação e agregação da ET0 diária BR-DWGD."""

from __future__ import annotations

import os
import shutil
import tempfile
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
from pathlib import Path
from collections.abc import Sequence
from .config import (
    ET0_ARCHIVE_MEMBER,
    ET0_ARCHIVE_URL,
    ET0_CACHE_DIR,
    ET0_SOURCE_URL,
    METODO_ET0_SOLO,
    VARIAVEL_ET0,
    VARIAVEL_FONTE_ET0,
)


_TIME_ALIASES = ('time', 'date', 'data')
_LAT_ALIASES = ('latitude', 'lat')
_LON_ALIASES = ('longitude', 'lon')
_ATTRS_EMPACOTAMENTO = {
    '_FillValue',
    'FillValue',
    '_ChunkSizes',
    'valid_min',
    'valid_max',
    'scale_factor',
    'add_offset',
}


def _validar_ano(ano: int) -> int:
    if isinstance(ano, bool) or not isinstance(ano, (int, np.integer)):
        raise TypeError('ano deve ser um número inteiro.')
    ano = int(ano)
    if ano < 2001 or ano > 2025:
        raise ValueError('O arquivo BR-DWGD v3.2.4 cobre os anos de 2001 a 2025.')
    return ano


def _caminho_cache(ano: int) -> Path:
    return ET0_CACHE_DIR / f'ET0_{ano}_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc'


def _encontrar_coordenada(da: xr.DataArray, aliases: Sequence[str], rotulo: str) -> str:
    nomes_por_lower = {str(nome).lower(): str(nome) for nome in da.coords}
    for alias in aliases:
        nome = nomes_por_lower.get(alias.lower())
        if nome is not None and da.coords[nome].ndim == 1:
            return nome
    raise ValueError(f'Coordenada unidimensional de {rotulo} não encontrada; esperada uma de {list(aliases)}.')


def _coordenadas_grade(da: xr.DataArray) -> tuple[str, str, str, str, str, str]:
    time_name = _encontrar_coordenada(da, _TIME_ALIASES, 'tempo')
    lat_name = _encontrar_coordenada(da, _LAT_ALIASES, 'latitude')
    lon_name = _encontrar_coordenada(da, _LON_ALIASES, 'longitude')
    time_dim = da.coords[time_name].dims[0]
    lat_dim = da.coords[lat_name].dims[0]
    lon_dim = da.coords[lon_name].dims[0]

    if len({time_dim, lat_dim, lon_dim}) != 3 or set(da.dims) != {time_dim, lat_dim, lon_dim}:
        raise ValueError(
            'A ET0 deve ter exatamente três dimensões independentes: tempo, latitude e longitude.'
        )
    return time_name, lat_name, lon_name, time_dim, lat_dim, lon_dim


def _validar_eixo_espacial(coord: xr.DataArray, minimo: float, maximo: float, rotulo: str) -> None:
    valores = np.asarray(coord.values)
    if valores.ndim != 1 or valores.size < 2 or not np.issubdtype(valores.dtype, np.number):
        raise ValueError(f'A coordenada de {rotulo} deve ser um vetor numérico com pelo menos dois valores.')
    valores = valores.astype('float64', copy=False)
    if not np.isfinite(valores).all() or (valores < minimo).any() or (valores > maximo).any():
        raise ValueError(f'A coordenada de {rotulo} contém valores inválidos.')
    diferencas = np.diff(valores)
    if not ((diferencas > 0).all() or (diferencas < 0).all()):
        raise ValueError(f'A coordenada de {rotulo} deve ser estritamente monotônica.')
    passo = abs(float(np.median(diferencas)))
    # Coordenadas BR-DWGD sao float32; o passo de 0,1 grau acumula
    # pequenas diferencas de representacao ao longo do eixo.
    tolerancia = max(1e-6, passo * 1e-3)
    if np.max(np.abs(np.abs(diferencas) - passo)) > tolerancia:
        raise ValueError(f'A coordenada de {rotulo} não forma uma grade regular.')


def _selecionar_e_validar_ano(da: xr.DataArray, ano: int) -> xr.DataArray:
    ano = _validar_ano(ano)
    time_name, lat_name, lon_name, time_dim, _, _ = _coordenadas_grade(da)
    try:
        mascara_ano = da.coords[time_name].dt.year == ano
    except (AttributeError, TypeError) as exc:
        raise ValueError('A coordenada temporal da ET0 não pôde ser interpretada como datas.') from exc

    recorte = da.where(mascara_ano, drop=True)
    datas = np.asarray(recorte.coords[time_name].dt.strftime('%Y-%m-%d').values, dtype=str)
    esperadas = pd.date_range(f'{ano}-01-01', f'{ano}-12-31', freq='D').strftime('%Y-%m-%d').to_numpy()
    if not np.array_equal(datas, esperadas):
        raise ValueError(
            f'A ET0 de {ano} deve conter exatamente as {len(esperadas)} datas diárias, em ordem e sem duplicatas.'
        )
    if recorte.sizes[time_dim] != len(esperadas):
        raise ValueError(f'Número inesperado de registros temporais para {ano}.')

    _validar_eixo_espacial(recorte.coords[lat_name], -90, 90, 'latitude')
    _validar_eixo_espacial(recorte.coords[lon_name], -180, 180, 'longitude')
    valores = np.asarray(recorte.values)
    if not np.issubdtype(valores.dtype, np.number):
        raise ValueError(f'A variável {VARIAVEL_ET0} deve ser numérica.')
    if np.isinf(valores).any():
        raise ValueError(f'A variável {VARIAVEL_ET0} contém valores infinitos em {ano}.')
    valores_validos = valores[np.isfinite(valores)]
    if valores_validos.size == 0:
        raise ValueError(f'A variável {VARIAVEL_ET0} não contém nenhum valor válido em {ano}.')
    if (valores_validos < 0).any():
        raise ValueError(f'A variável {VARIAVEL_ET0} contém valores negativos em {ano}.')
    return recorte


def carregar_et0_anual(path: str | Path, ano: int = 2024) -> xr.DataArray:
    """Carrega e valida os valores diários de ET0 de um ano civil completo."""

    ano = _validar_ano(ano)
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f'Arquivo ET0 não encontrado ou vazio: {path}')

    with xr.open_dataset(path, decode_times=True, mask_and_scale=True) as ds:
        if VARIAVEL_ET0 not in ds.data_vars:
            disponiveis = ', '.join(sorted(ds.data_vars)) or 'nenhuma'
            raise ValueError(
                f'Variável {VARIAVEL_ET0} não encontrada em {path.name}. Variáveis disponíveis: {disponiveis}.'
            )
        attrs_dataset = dict(ds.attrs)
        et0 = _selecionar_e_validar_ano(ds[VARIAVEL_ET0], ano).load()

    et0.attrs = dict(et0.attrs)
    for chave, valor in attrs_dataset.items():
        et0.attrs.setdefault(f'dataset_{chave}', valor)
    et0.attrs['ano'] = ano
    et0.attrs['dias_no_ano'] = int(et0.sizes[_coordenadas_grade(et0)[3]])
    return et0


def _abrir_zip_remoto():
    try:
        from remotezip import RemoteZip
    except ImportError as exc:
        raise ImportError(
            'A dependência remotezip é necessária para baixar a ET0. Instale as dependências de requirements.txt.'
        ) from exc

    return RemoteZip(
        ET0_ARCHIVE_URL,
        headers={'User-Agent': 'soil-analysis/1.0'},
        timeout=120,
        support_suffix_range=False,
    )


def _extrair_membro_remoto(destino: Path) -> None:
    with _abrir_zip_remoto() as arquivo_zip:
        nomes = arquivo_zip.namelist()
        if ET0_ARCHIVE_MEMBER not in nomes:
            raise FileNotFoundError(
                f'O membro esperado {ET0_ARCHIVE_MEMBER} não existe no arquivo remoto. '
                f'Membros encontrados: {nomes}'
            )
        info = arquivo_zip.getinfo(ET0_ARCHIVE_MEMBER)
        if info.is_dir():
            raise ValueError(f'O membro {ET0_ARCHIVE_MEMBER} é um diretório, não um NetCDF.')
        with arquivo_zip.open(ET0_ARCHIVE_MEMBER, 'r') as origem, destino.open('wb') as saida:
            shutil.copyfileobj(origem, saida, length=8 * 1024 * 1024)

    if not destino.is_file() or destino.stat().st_size != info.file_size:
        tamanho = destino.stat().st_size if destino.exists() else 0
        raise OSError(
            f'Extração incompleta de {ET0_ARCHIVE_MEMBER}: esperado {info.file_size} bytes, obtido {tamanho}.'
        )


def _salvar_recorte_compacto(origem: Path, destino: Path, ano: int) -> None:
    with xr.open_dataset(origem, decode_times=True, mask_and_scale=True) as ds:
        if VARIAVEL_FONTE_ET0 not in ds.data_vars:
            disponiveis = ', '.join(sorted(ds.data_vars)) or 'nenhuma'
            raise ValueError(
                f'Variável oficial {VARIAVEL_FONTE_ET0} ausente; disponíveis: {disponiveis}.'
            )
        et0 = (
            _selecionar_e_validar_ano(ds[VARIAVEL_FONTE_ET0], ano)
            .load()
            .astype('float32')
            .rename(VARIAVEL_ET0)
        )
        et0.attrs = {
            chave: valor
            for chave, valor in et0.attrs.items()
            if chave not in _ATTRS_EMPACOTAMENTO
        }
        et0.attrs['standard_name'] = VARIAVEL_ET0
        et0.encoding = {}
        compacto = et0.to_dataset(name=VARIAVEL_ET0)
        compacto.attrs = dict(ds.attrs)

    compacto.attrs.update({
        'source_archive_url': ET0_ARCHIVE_URL,
        'source_archive_member': ET0_ARCHIVE_MEMBER,
        'source_information_url': ET0_SOURCE_URL,
        'source_variable': VARIAVEL_FONTE_ET0,
        'derived_variable': VARIAVEL_ET0,
        'temporal_subset_year': ano,
    })
    encoding = {
        VARIAVEL_ET0: {
            'dtype': 'float32',
            '_FillValue': np.float32(np.nan),
            'zlib': True,
            'complevel': 4,
            'shuffle': True,
        }
    }
    compacto.to_netcdf(destino, engine='netcdf4', encoding=encoding)
    carregar_et0_anual(destino, ano)


def garantir_et0_brdwgd(ano: int = 2024, force: bool = False) -> Path:
    """Garante um NetCDF anual compacto de ET0 a partir do membro oficial."""

    ano = _validar_ano(ano)
    destino = _caminho_cache(ano)
    if destino.is_file() and destino.stat().st_size > 0 and not force:
        try:
            carregar_et0_anual(destino, ano)
        except PermissionError:
            raise
        except (OSError, ValueError):
            pass
        else:
            return destino

    ET0_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    descritor, nome_cache_temporario = tempfile.mkstemp(
        prefix=f'.{destino.stem}_',
        suffix='.tmp',
        dir=ET0_CACHE_DIR,
    )
    os.close(descritor)
    cache_temporario = Path(nome_cache_temporario)
    try:
        with tempfile.TemporaryDirectory(prefix=f'.et0_{ano}_', dir=ET0_CACHE_DIR) as temp_dir:
            membro_temporario = Path(temp_dir) / ET0_ARCHIVE_MEMBER
            _extrair_membro_remoto(membro_temporario)
            _salvar_recorte_compacto(membro_temporario, cache_temporario, ano)
        os.replace(cache_temporario, destino)
    finally:
        cache_temporario.unlink(missing_ok=True)

    return destino


def _colunas_resumo(categorias: Sequence[str]) -> list[str]:
    return [
        *categorias,
        'et0_anual_media_mm',
        'pixels_et0',
        'pixels_grade_et0',
        'cobertura_et0_pct',
        'et0_periodo',
        'et0_variavel',
        'et0_metodo',
    ]


def resumir_et0_por_solo(
    et0_anual: xr.DataArray,
    gdf: gpd.GeoDataFrame,
    categorias: str | Sequence[str],
) -> pd.DataFrame:
    """Resume o total anual de ET0 por classes espaciais de solo."""

    if isinstance(categorias, str):
        categorias = [categorias]
    else:
        categorias = list(categorias)
    if not categorias or any(not isinstance(col, str) or not col for col in categorias):
        raise ValueError('categorias deve conter ao menos um nome de coluna válido.')
    if len(categorias) != len(set(categorias)):
        raise ValueError('categorias não pode conter nomes duplicados.')
    if not isinstance(et0_anual, xr.DataArray) or et0_anual.name != VARIAVEL_ET0:
        raise ValueError(f'et0_anual deve ser um xarray.DataArray chamado {VARIAVEL_ET0}.')
    if not isinstance(gdf, gpd.GeoDataFrame) or gdf.crs is None:
        raise ValueError('gdf deve ser um GeoDataFrame com CRS definido.')
    ausentes = set(categorias).difference(gdf.columns)
    if ausentes:
        raise ValueError(f'Categorias ausentes no GeoDataFrame: {sorted(ausentes)}')

    time_name, lat_name, lon_name, time_dim, lat_dim, lon_dim = _coordenadas_grade(et0_anual)
    anos = np.unique(np.asarray(et0_anual.coords[time_name].dt.year.values))
    if len(anos) != 1:
        raise ValueError('et0_anual deve conter dados de exatamente um ano.')
    ano = _validar_ano(int(anos[0]))
    et0_validada = _selecionar_e_validar_ano(et0_anual, ano)
    et0_total = et0_validada.sum(dim=time_dim, skipna=False).transpose(lat_dim, lon_dim)

    geometry_name = gdf.geometry.name
    solos = gdf[[*categorias, geometry_name]].dropna(subset=categorias).copy()
    if solos.empty:
        return pd.DataFrame(columns=_colunas_resumo(categorias))
    solos = gpd.GeoDataFrame(solos, geometry=geometry_name, crs=gdf.crs).to_crs('EPSG:4326')
    solos.geometry = solos.geometry.make_valid()
    solos = solos[solos.geometry.notna() & ~solos.geometry.is_empty].copy()
    if solos.empty:
        return pd.DataFrame(columns=_colunas_resumo(categorias))
    dissolvidos = solos.dissolve(by=categorias, as_index=False)[[*categorias, geometry_name]]

    lats = np.asarray(et0_total.coords[lat_name].values, dtype='float64')
    lons = np.asarray(et0_total.coords[lon_name].values, dtype='float64')
    lon_grade, lat_grade = np.meshgrid(lons, lats)
    pontos = gpd.GeoDataFrame(
        {
            '_pixel_id': np.arange(et0_total.size, dtype='int64'),
            '_et0_anual': np.asarray(et0_total.values, dtype='float64').reshape(-1),
            '_latitude': lat_grade.reshape(-1),
        },
        geometry=gpd.points_from_xy(lon_grade.reshape(-1), lat_grade.reshape(-1)),
        crs='EPSG:4326',
    )
    associados = gpd.sjoin(pontos, dissolvidos, how='left', predicate='within')
    associados = associados.dropna(subset=['index_right']).copy()
    if associados.empty:
        return pd.DataFrame(columns=_colunas_resumo(categorias))

    contagens = associados.groupby('_pixel_id', sort=False).size()
    ids_univocos = contagens[contagens == 1].index
    associados = associados[associados['_pixel_id'].isin(ids_univocos)].copy()
    if associados.empty:
        return pd.DataFrame(columns=_colunas_resumo(categorias))

    grade = (
        associados.groupby(categorias, dropna=False, sort=True)['_pixel_id']
        .nunique()
        .rename('pixels_grade_et0')
        .reset_index()
    )
    associados_validos = associados[np.isfinite(associados['_et0_anual'])].copy()
    associados_validos['_peso_latitude'] = np.cos(np.deg2rad(associados_validos['_latitude']))
    associados_validos['_et0_ponderada'] = (
        associados_validos['_et0_anual'] * associados_validos['_peso_latitude']
    )
    metricas = (
        associados_validos.groupby(categorias, dropna=False, sort=True)
        .agg(
            _et0_ponderada=('_et0_ponderada', 'sum'),
            _peso_latitude=('_peso_latitude', 'sum'),
            pixels_et0=('_pixel_id', 'nunique'),
        )
        .reset_index()
    )
    resumo = grade.merge(metricas, on=categorias, how='left')
    resumo['et0_anual_media_mm'] = resumo['_et0_ponderada'] / resumo['_peso_latitude']
    resumo['pixels_et0'] = resumo['pixels_et0'].fillna(0).astype('Int64')
    resumo['pixels_grade_et0'] = resumo['pixels_grade_et0'].astype('Int64')
    resumo['cobertura_et0_pct'] = (
        resumo['pixels_et0'].astype('float64') / resumo['pixels_grade_et0'].astype('float64') * 100
    )
    resumo['et0_periodo'] = str(ano)
    resumo['et0_variavel'] = VARIAVEL_ET0
    resumo['et0_metodo'] = METODO_ET0_SOLO
    return resumo[_colunas_resumo(categorias)]
