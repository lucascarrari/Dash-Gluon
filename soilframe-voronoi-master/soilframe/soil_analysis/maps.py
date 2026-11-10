"""Funções auxiliares para o notebook de análise de solos.

Gera o mapa interativo Folium usado no notebook.
"""

import folium
import pandas as pd
import geopandas as gpd
from pathlib import Path
from IPython.display import IFrame

from .config import (
    HORA_LST,
    LST_PERIODO_ROTULO,
    OUTPUT_DIR,
    PALETA_SOLOS,
    SWI_CORES,
    VARIAVEL_LST,
    VARIAVEL_SWI,
)
from .copernicus import COLUNAS_LST_GDF, COLUNAS_SWI_GDF


def gerar_mapa_interativo(
    gdf,
    swi_tiles_brasil=None,
    lst_catalogo_periodo=None,
    lst_processados=None,
    output_path=None,
    iframe_height=650,
):
    for col in COLUNAS_SWI_GDF:
        if col not in gdf.columns:
            gdf[col] = pd.NA
    for col in COLUNAS_LST_GDF:
        if col not in gdf.columns:
            gdf[col] = pd.NA

    map_cols = [
        'COD_LEGEND',
        'COD_SIMBOL',
        'estado_nome',
        'estado_sigla',
        'regiao_nome',
        'municipio_predominante',
        'DSC_COMPON',
        'DSC_TEXTUR',
        'tipo_solo_principal',
        'classe_textura',
        'porosidade_estimada_media',
        'precipitacao_anual_media_mm',
        'precipitacao_classe',
        'swi_010_media',
        'swi_classe',
        'swi_pontos',
        'lst_celsius_tipo_media',
        'lst_periodo',
        'lst_hora_utc',
        'lst_variavel',
        'lst_metodo',
        'geometry',
    ]

    gdf_map = gdf[map_cols].copy().to_crs('EPSG:4326')
    gdf_map['geometry'] = gdf_map.geometry.simplify(0.02, preserve_topology=True)
    gdf_map['swi_010_media'] = pd.to_numeric(gdf_map['swi_010_media'], errors='coerce').round(1)
    gdf_map['swi_pontos'] = pd.to_numeric(gdf_map['swi_pontos'], errors='coerce').fillna(0).round(0).astype('Int64')
    gdf_map['swi_classe'] = gdf_map['swi_classe'].fillna('sem dados')
    gdf_map['lst_celsius_tipo_media'] = pd.to_numeric(gdf_map['lst_celsius_tipo_media'], errors='coerce').round(1)
    gdf_map['lst_hora_utc'] = pd.to_numeric(gdf_map['lst_hora_utc'], errors='coerce').astype('Int64')
    gdf_map['lst_periodo'] = gdf_map['lst_periodo'].fillna(LST_PERIODO_ROTULO)
    gdf_map['lst_variavel'] = gdf_map['lst_variavel'].fillna(VARIAVEL_LST)
    gdf_map['lst_metodo'] = gdf_map['lst_metodo'].fillna('sem dados')
    tem_swi_mapa = gdf_map['swi_010_media'].notna().any()
    tem_lst_mapa = gdf_map['lst_celsius_tipo_media'].notna().any()

    tipos = sorted(gdf_map['tipo_solo_principal'].fillna('(vazio)').astype(str).unique())
    color_by_tipo = {tipo: PALETA_SOLOS[i % len(PALETA_SOLOS)] for i, tipo in enumerate(tipos)}

    m = folium.Map(location=[-14.2, -51.9], zoom_start=4, tiles='cartodbpositron', control_scale=True)


    def style_solo(feature):
        tipo = feature['properties'].get('tipo_solo_principal') or '(vazio)'
        return {
            'fillColor': color_by_tipo.get(str(tipo), '#888888'),
            'color': '#334155',
            'weight': 0.35,
            'fillOpacity': 0.72,
        }


    def style_swi_solo(feature):
        classe = feature['properties'].get('swi_classe') or 'sem dados'
        return {
            'fillColor': SWI_CORES.get(classe, SWI_CORES['sem dados']),
            'color': '#334155',
            'weight': 0.35,
            'fillOpacity': 0.68 if classe != 'sem dados' else 0.3,
        }


    def style_swi_tile(feature):
        return {
            'fillColor': '#FFFFFF',
            'color': '#6D28D9',
            'weight': 1.1,
            'fillOpacity': 0.02,
            'dashArray': '5, 4',
        }


    def style_lst_coverage(feature):
        return {
            'fillColor': '#FFFFFF',
            'color': '#B91C1C',
            'weight': 1.2,
            'fillOpacity': 0.015,
            'dashArray': '7, 4',
        }


    def highlight_function(feature):
        return {'weight': 2, 'color': '#111111', 'fillOpacity': 0.9}


    tooltip_fields = [
        'estado_nome',
        'estado_sigla',
        'regiao_nome',
        'municipio_predominante',
        'tipo_solo_principal',
        'DSC_COMPON',
        'classe_textura',
        'porosidade_estimada_media',
        'precipitacao_anual_media_mm',
        'precipitacao_classe',
    ]
    tooltip_aliases = [
        'Estado:',
        'UF:',
        'Região:',
        'Município predominante:',
        'Tipo:',
        'Descrição:',
        'Textura:',
        'Porosidade média (%):',
        'Precipitação anual (mm):',
        'Classe de precipitação:',
    ]
    if tem_swi_mapa:
        tooltip_fields += ['swi_010_media', 'swi_classe', 'swi_pontos']
        tooltip_aliases += [f'{VARIAVEL_SWI} médio (%):', 'Classe SWI:', 'Pontos SWI:']
    if tem_lst_mapa:
        tooltip_fields += ['lst_celsius_tipo_media', 'lst_periodo', 'lst_hora_utc']
        tooltip_aliases += ['LST média por tipo (°C):', 'Período LST:', 'Hora UTC LST:']
    tooltip_fields += ['COD_SIMBOL']
    tooltip_aliases += ['Símbolo:']

    folium.GeoJson(
        gdf_map.to_json(na='null'),
        name='Tipos de solo',
        style_function=style_solo,
        highlight_function=highlight_function,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, sticky=False),
    ).add_to(m)

    if tem_swi_mapa:
        folium.GeoJson(
            gdf_map.to_json(na='null'),
            name=f'Umidade SWI por solo ({VARIAVEL_SWI})',
            style_function=style_swi_solo,
            highlight_function=highlight_function,
            tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, sticky=False),
            show=False,
        ).add_to(m)

    if swi_tiles_brasil is not None and not swi_tiles_brasil.empty:
        swi_tiles_mapa = swi_tiles_brasil[
            ['name', 'content_date_start', 'content_date_end', 'nominal_date', 'content_length_mb', 'netcdf_local_disponivel', 'cache_path', 'geometry']
        ].copy().to_crs('EPSG:4326')
        for col in ['content_date_start', 'content_date_end', 'nominal_date']:
            swi_tiles_mapa[col] = swi_tiles_mapa[col].dt.strftime('%Y-%m-%d')

        folium.GeoJson(
            swi_tiles_mapa.to_json(na='null'),
            name='Cobertura SWI Copernicus',
            style_function=style_swi_tile,
            tooltip=folium.GeoJsonTooltip(
                fields=['name', 'content_date_start', 'content_date_end', 'nominal_date', 'content_length_mb', 'netcdf_local_disponivel', 'cache_path'],
                aliases=['Tile:', 'Início:', 'Fim:', 'Data nominal:', 'Tamanho (MB):', 'NetCDF local:', 'Caminho local esperado:'],
                sticky=False,
            ),
            show=False,
        ).add_to(m)

    if lst_catalogo_periodo is not None and not lst_catalogo_periodo.empty:
        lst_geom = lst_catalogo_periodo.geometry.iloc[0]
        lst_cobertura = gpd.GeoDataFrame([
            {
                'produto': 'Copernicus LST global 3km horário v3',
                'periodo': LST_PERIODO_ROTULO,
                'hora_utc': HORA_LST,
                'arquivos_selecionados': len(lst_catalogo_periodo),
                'arquivos_netcdf_local': int(lst_catalogo_periodo['netcdf_local_disponivel'].sum()),
                'arquivos_processados': len(lst_processados) if lst_processados is not None else 0,
                'volume_gb': round(lst_catalogo_periodo['content_length'].sum() / 1024**3, 1),
                'data_inicial': lst_catalogo_periodo['nominal_date'].min().strftime('%Y-%m-%d %H:%M'),
                'data_final': lst_catalogo_periodo['nominal_date'].max().strftime('%Y-%m-%d %H:%M'),
                'geometry': lst_geom,
            }
        ], crs='EPSG:4326')

        folium.GeoJson(
            lst_cobertura.to_json(na='null'),
            name='Cobertura LST Copernicus',
            style_function=style_lst_coverage,
            tooltip=folium.GeoJsonTooltip(
                fields=['produto', 'periodo', 'hora_utc', 'arquivos_selecionados', 'arquivos_netcdf_local', 'arquivos_processados', 'volume_gb', 'data_inicial', 'data_final'],
                aliases=['Produto:', 'Período:', 'Hora UTC:', 'Arquivos selecionados:', 'NetCDF locais:', 'Arquivos processados:', 'Volume selecionado (GB):', 'Início:', 'Fim:'],
                sticky=False,
            ),
            show=False,
        ).add_to(m)

    folium.LayerControl().add_to(m)
    map_path = Path(output_path) if output_path is not None else OUTPUT_DIR / 'animations' / 'mapa_solos_interativo.html'
    m.save(map_path)
    return IFrame(src=map_path.as_posix(), width='100%', height=iframe_height)
