"""Funções auxiliares para o notebook de análise de solos.

Configura caminhos, períodos, métodos e paletas visuais.
"""

import os
import warnings
import pandas as pd
from pathlib import Path
from urllib3.exceptions import InsecureRequestWarning

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = [PROJECT_ROOT / '.env', PROJECT_ROOT / 'dotenv_files' / '.env']

def carregar_env_local(paths=ENV_FILES):
    if isinstance(paths, (str, Path)):
        paths = [Path(paths)]
    for path in paths:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding='utf-8').splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                os.environ[key] = value


carregar_env_local()

RAW_DATA_DIR = PROJECT_ROOT / 'data/raw'
OUTPUT_DIR = PROJECT_ROOT / 'outputs'
OUTPUT_FIGURES_DIR = OUTPUT_DIR / 'figures'
OUTPUT_TABLES_DIR = OUTPUT_DIR / 'tables'
OUTPUT_ANIMATIONS_DIR = OUTPUT_DIR / 'animations'
OUTPUT_FRAMES_DIR = OUTPUT_DIR / 'frames'
for output_dir in (OUTPUT_DIR, OUTPUT_FIGURES_DIR, OUTPUT_TABLES_DIR, OUTPUT_ANIMATIONS_DIR, OUTPUT_FRAMES_DIR):
    output_dir.mkdir(exist_ok=True)

DATA = RAW_DATA_DIR / 'solos_5000_processado.csv'
PLUVIAL_DATA = RAW_DATA_DIR / 'pluviais_20_a_24_novo.csv'
SWI_CATALOG = RAW_DATA_DIR / 'swi-timeseries_global_12.5km_daily_v4_nc.csv'
SWI_CACHE_DIR = PROJECT_ROOT / 'data/swi_nc'
LST_CATALOG = RAW_DATA_DIR / 'lst_global_3km_hourly_v3_nc.csv'
LST_CATALOG_V1 = OUTPUT_TABLES_DIR / 'lst_global_5km_hourly_v1_cog.csv'
LST_CATALOG_V3 = RAW_DATA_DIR / 'lst_global_3km_hourly_v3_nc.csv'
LST_CACHE_DIR = PROJECT_ROOT / 'data/lst_nc'
ET0_CACHE_DIR = PROJECT_ROOT / 'data/et0_nc'
ET0_ARCHIVE_URL = (
    'https://drive.usercontent.google.com/download'
    '?id=1aGdOHRT10W8oBWvE5IvmEAqJCNQOYYid&export=download&confirm=t'
)
ET0_ARCHIVE_MEMBER = 'ETo_20010101_20251231_BR-DWGD_UFES_UTEXAS_v_3.2.4.nc'
ET0_SOURCE_URL = 'https://sites.google.com/site/alexandrecandidoxavierufes/brazilian-daily-weather-gridded-data'
SWI_SOURCE_URL = 'https://land.copernicus.eu/en/products/soil-moisture/soil-water-index-time-series-global-12-5km-v4#general_info'
LST_SOURCE_URL = 'https://land.copernicus.eu/en/products/temperature-and-reflectance/hourly-land-surface-temperature-global-v3-0-3km#general_info'
CDSE_S3_ENDPOINT = 'https://eodata.dataspace.copernicus.eu'

CRS_DADOS = 'EPSG:4674'
CRS_METRICO = 'EPSG:5880'
PERIODO_CHUVA = (2024, 2024)
PERIODO_SWI = (2024, 2024)
PERIODO_LST = (2024, 2024)
PERIODO_ET0 = (2024, 2024)
HORA_LST = 12
VARIAVEL_SWI = 'SWI_010'
VARIAVEL_LST = 'LST'
VARIAVEL_ET0 = 'ET0'
VARIAVEL_FONTE_ET0 = 'ETo'
PRECIPITACAO_PERIODO_ROTULO = (
    str(PERIODO_CHUVA[0])
    if PERIODO_CHUVA[0] == PERIODO_CHUVA[1]
    else f'{PERIODO_CHUVA[0]}-{PERIODO_CHUVA[1]}'
)
SWI_PERIODO_ROTULO = (
    str(PERIODO_SWI[0])
    if PERIODO_SWI[0] == PERIODO_SWI[1]
    else f'{PERIODO_SWI[0]}-{PERIODO_SWI[1]}'
)
LST_PERIODO_ROTULO = (
    str(PERIODO_LST[0])
    if PERIODO_LST[0] == PERIODO_LST[1]
    else f'{PERIODO_LST[0]}-{PERIODO_LST[1]}'
)
DIAS_MINIMOS_ANO_CHUVA = 330
CHUNK_CHUVA = 500_000
METODO_PRECIPITACAO_MUNICIPAL_SOLO = 'media_estacao_anual_por_municipio_area_ponderada'
METODO_SWI_SOLO = 'media_pontos_swi_por_poligono_area_ponderada'
METODO_LST_SOLO = 'media_grade_lst_3km_12h_por_tipo_solo'
METODO_ET0_SOLO = 'soma_diaria_media_grade_0_1grau_ponderada_cos_latitude'

CODIGOS_AGUA_COSTEIRA = {'Magua1', 'Magua2', 'Magua3'}
TIPOS_NAO_PEDOLOGICOS_GRAFICOS = {"Massa d'água"}

CORES = {
    'azul': '#2F4B7C',
    'azul_claro': '#88CCEE',
    'verde': '#44AA99',
    'verde_escuro': '#2D7A6B',
    'amarelo': '#E7A72D',
    'vermelho': '#CC6677',
    'cinza': '#8D8D8D',
    'cinza_claro': '#D9DEE3',
    'fundo': '#FFFFFF',
}

PRECIPITACAO_CORES = {
    'baixa': CORES['amarelo'],
    'moderada': CORES['azul_claro'],
    'alta': CORES['verde'],
    'muito alta': CORES['azul'],
    'sem dados': '#BDBDBD',
}

SWI_CORES = {
    'baixa': '#D95F02',
    'moderada': '#E6AB02',
    'alta': '#1B9E77',
    'muito alta': '#1F78B4',
    'sem dados': '#BDBDBD',
}

TEXTURA_CORES = {
    'arenosa': CORES['amarelo'],
    'média': CORES['azul_claro'],
    'argilosa ou muito argilosa': CORES['vermelho'],
    'indiscriminada': '#999933',
    'sem textura': CORES['cinza'],
}

PALETA_SOLOS = [
    '#2563EB', '#10B981', '#8B5CF6', '#EC4899', '#059669', '#0284C7',
    '#9333EA', '#1E293B', '#4F46E5', '#DC2626', '#4338CA', '#7E22CE',
    '#78350F', '#475569', '#991B1B', '#0369A1',
]

REGIOES_BR = {
    'AC': 'Norte', 'AP': 'Norte', 'AM': 'Norte', 'PA': 'Norte', 'RO': 'Norte', 'RR': 'Norte', 'TO': 'Norte',
    'AL': 'Nordeste', 'BA': 'Nordeste', 'CE': 'Nordeste', 'MA': 'Nordeste', 'PB': 'Nordeste', 'PE': 'Nordeste', 'PI': 'Nordeste', 'RN': 'Nordeste', 'SE': 'Nordeste',
    'DF': 'Centro-Oeste', 'GO': 'Centro-Oeste', 'MT': 'Centro-Oeste', 'MS': 'Centro-Oeste',
    'ES': 'Sudeste', 'MG': 'Sudeste', 'RJ': 'Sudeste', 'SP': 'Sudeste',
    'PR': 'Sul', 'RS': 'Sul', 'SC': 'Sul',
}
REGIAO_ORDEM = ['Norte', 'Nordeste', 'Centro-Oeste', 'Sudeste', 'Sul']

pd.set_option('display.max_columns', 80)
pd.set_option('display.max_colwidth', 120)
warnings.filterwarnings('ignore', category=InsecureRequestWarning)
