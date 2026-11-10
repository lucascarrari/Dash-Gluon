"""Funções auxiliares para o notebook de análise de solos.

Padroniza tema, figuras e pequenos helpers de visualização.
"""

import warnings
import pandas as pd
import geopandas as gpd
from shapely import wkt
import matplotlib.pyplot as plt
from .config import (
    CORES, DATA, OUTPUT_FIGURES_DIR, PALETA_SOLOS, REGIAO_ORDEM,
    TIPOS_NAO_PEDOLOGICOS_GRAFICOS,
)

def aplicar_tema_visual():
    plt.rcParams.update({
        'figure.facecolor': CORES['fundo'],
        'axes.facecolor': CORES['fundo'],
        'axes.edgecolor': '#334155',
        'axes.titleweight': 'bold',
        'axes.titlesize': 15,
        'axes.labelsize': 11,
        'axes.labelcolor': '#1F2937',
        'xtick.color': '#1F2937',
        'ytick.color': '#1F2937',
        'font.size': 10.5,
        'legend.frameon': True,
        'legend.framealpha': 0.96,
        'legend.edgecolor': '#CBD5E1',
        'savefig.dpi': 180,
    })


def salvar_figura(fig, nome_arquivo):
    caminho = OUTPUT_FIGURES_DIR / nome_arquivo
    fig.tight_layout(pad=1.2)
    fig.savefig(caminho, dpi=180, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.show()


def estilizar_eixo(ax, eixo_grade='x'):
    ax.grid(axis=eixo_grade, alpha=0.20, color='#94A3B8', linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#334155')
    ax.spines['bottom'].set_color('#334155')
    ax.tick_params(axis='both', labelsize=10)


def filtrar_tipos_pedologicos(df, coluna='tipo_solo_principal'):
    return df[~df[coluna].isin(TIPOS_NAO_PEDOLOGICOS_GRAFICOS)].copy()


def adicionar_rotulos_barras(ax, valores, sufixo='', casas=0, padding=4):
    labels = [f'{float(valor):.{casas}f}{sufixo}' for valor in valores]
    ax.bar_label(ax.containers[0], labels=labels, padding=padding, fontsize=9, color='#111827')


def ordenar_regioes(valores):
    presentes = [regiao for regiao in REGIAO_ORDEM if regiao in set(valores)]
    return presentes + [regiao for regiao in valores if regiao not in presentes]


def carregar_malha_solos_mapa(data_path=DATA):
    """Carrega a malha pedológica dissolvida por tipo para mapas."""
    tabela = pd.read_csv(data_path, encoding='utf-8-sig').dropna(
        subset=['WKT', 'tipo_solo_principal']
    )
    tabela = tabela[
        ~tabela['tipo_solo_principal'].isin(TIPOS_NAO_PEDOLOGICOS_GRAFICOS)
    ]
    solos = gpd.GeoDataFrame(
        tabela[['tipo_solo_principal']],
        geometry=tabela['WKT'].map(wkt.loads),
        crs='EPSG:4674',
    ).to_crs('EPSG:4326')
    solos['geometry'] = solos.geometry.make_valid()
    solos = solos[solos.geometry.notna() & ~solos.geometry.is_empty]
    return solos.dissolve(
        by='tipo_solo_principal', as_index=False
    ).sort_values('tipo_solo_principal').reset_index(drop=True)


PALETA_SOLOS_ET0 = [
    '#10B981', '#E7298A', '#E6AB02', '#0077BB', '#66A61E', '#7E22CE',
    '#1E293B', '#0284C7', '#9333EA', '#34D399', '#65A30D', '#0D9488',
    '#DB2777', '#475569', '#4F46E5', '#059669'
]

PALETA_SOLOS_PERDA = [
    '#0284C7', '#10B981', '#E6AB02', '#2563EB', '#059669', '#1E293B',
    '#0D9488', '#8B5CF6', '#0077BB', '#65A30D', '#34D399', '#4F46E5',
    '#475569', '#3182BD', '#065F46', '#1D4ED8'
]

PALETA_SOLOS_PRECIP = [
    '#E7298A', '#7E22CE', '#E6AB02', '#1E293B', '#9333EA', '#DC2626',
    '#6A3D9A', '#78350F', '#451A03', '#DB2777', '#E11D48', '#475569',
    '#881337', '#BE185D', '#581C87', '#991B1B'
]

PALETA_SOLOS_BALANCO = [
    '#7E22CE', '#E7298A', '#E6AB02', '#1E293B', '#9333EA', '#DC2626',
    '#333333', '#DB2777', '#475569', '#78350F', '#6A3D9A', '#BE185D'
]

def adicionar_contornos_solos(ax, solos_mapa, linewidth=0.7, ncol=2, incluir_legenda_regiao=False, tipo_metrica='et0', desenhar=False):
    """Desenha contornos coloridos por tipo de solo apenas se desenhar=True."""
    if not desenhar or solos_mapa is None:
        return
        paleta = PALETA_SOLOS_PRECIP
    elif tipo_metrica in ('perda', 'deficit'):
        paleta = PALETA_SOLOS_PERDA
    elif tipo_metrica == 'balanco':
        paleta = PALETA_SOLOS_BALANCO
    else:
        paleta = PALETA_SOLOS_ET0

    tipos = sorted(solos_mapa['tipo_solo_principal'].astype(str).unique())
    cores = {tipo: paleta[i % len(paleta)] for i, tipo in enumerate(tipos)}

    # 1. Contornos coloridos de alto contraste por tipo de solo
    for _, solo in solos_mapa.iterrows():
        tipo = str(solo['tipo_solo_principal'])
        gpd.GeoSeries([solo.geometry], crs=solos_mapa.crs).boundary.plot(
            ax=ax, color=cores[tipo], linewidth=linewidth, alpha=0.95, zorder=5
        )

    # 2. Legenda de tipos de solo no canto inferior esquerdo
    legenda_handles = [plt.Line2D([], [], color=cores[tipo], linewidth=2.2, label=tipo) for tipo in tipos]
    ax.legend(
        handles=legenda_handles, title='Tipos de solo', loc='lower left',
        bbox_to_anchor=(0.01, 0.01), ncol=ncol, fontsize=6.5,
        title_fontsize=7.5, framealpha=0.94,
    )

    # 3. Card de Solos Predominantes por Região no canto inferior direito
    # Título centralizado e lista de regiões alinhada à esquerda
    if incluir_legenda_regiao:
        texto_legenda = (
            "    SOLOS PREDOMINANTES POR REGIÃO    \n"
            "──────────────────────────────────────\n"
            "• Norte:        Argissolo (29.4%) / Latossolo (27.5%)\n"
            "• Nordeste:     Latossolo (29.6%) / Neossolo (23.8%)\n"
            "• Centro-Oeste: Latossolo (39.2%) / Argissolo (18.7%)\n"
            "• Sudeste:      Latossolo (45.7%) / Argissolo (28.8%)\n"
            "• Sul:          Latossolo (19.5%) / Neossolo (18.8%)"
        )
        ax.text(
            0.98, 0.03, texto_legenda, transform=ax.transAxes,
            fontsize=7.2, fontweight='bold', color='#0F172A', family='sans-serif',
            va='bottom', ha='right', zorder=10,
            bbox=dict(
                boxstyle='round,pad=0.5,rounding_size=0.25',
                facecolor='#F8FAFC',
                edgecolor='#CBD5E1',
                alpha=0.95,
                linewidth=0.9
            )
        )

def classificar_swi(valor):
    if pd.isna(valor):
        return 'sem dados'
    if valor < 30:
        return 'baixa'
    if valor < 50:
        return 'moderada'
    if valor < 70:
        return 'alta'
    return 'muito alta'


def formatar_tamanho_bytes(valor):
    if pd.isna(valor):
        return None
    return round(float(valor) / (1024 ** 2), 2)
