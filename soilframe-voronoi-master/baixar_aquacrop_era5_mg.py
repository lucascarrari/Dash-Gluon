#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download das variáveis do modelo AquaCrop usando ERA5-Land para Minas Gerais (MG).

Utiliza a estratégia espacial de Voronoi implementada no SoilFrame para alocação
e amostragem das 853 células municipais em janela de 1 ano completo (2024).

Uso:
    python baixar_aquacrop_era5_mg.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Garante importação do soilframe
sys.path.insert(0, str(Path(__file__).resolve().parent / "soilframe"))

from soilframe import FonteERA5LandVoronoi, PipelineAquaCropERA5, Registry


def main():
    print("=" * 80)
    print(" SOILFRAME: DOWNLOAD ERA5-LAND AQUACROP (MINAS GERAIS - 1 ANO)")
    print(" Estratégia Espacial: Células de Voronoi (853 Municípios de MG)")
    print("=" * 80)

    t0 = time.time()

    # 1. Descoberta via Registry do SoilFrame
    print("\n[1] Obtendo pipeline oficial do SoilFrame Registry...")
    registry = Registry()
    pipeline = registry.get_pipeline("pipeline_aquacrop_era5")

    # 2. Execução da Pipeline para Minas Gerais (Ano 2024 completo)
    print("\n[2] Executando pipeline com a estratégia Agro-Voronoi...")
    print("    - UF: Minas Gerais (MG)")
    print("    - Período: 2024-01-01 a 2024-12-31 (366 dias)")
    print("    - Variáveis AquaCrop:")
    print("        * Tmax (temperatura máxima diária)")
    print("        * Tmin (temperatura mínima diária)")
    print("        * Tmean (temperatura média diária)")
    print("        * Chuva / Precipitação acumulada diária (mm)")
    print("        * ETo (Evapotranspiração de referência FAO-56 Penman-Monteith)")
    print("        * Radiação solar de ondas curtas (MJ/m²)")
    print("        * Vento a 10m (m/s)")

    dataset = pipeline.rodar({
        "uf": "MG",
        "ano": 2024,
        "data_inicio": "2024-01-01",
        "data_fim": "2024-12-31",
        "gerar_arquivos_aquacrop": True,
    })

    df = dataset.data
    tempo_total = time.time() - t0

    # 3. Métricas e Estatísticas
    print("\n" + "=" * 80)
    print(" DOWNLOAD CONCLUÍDO COM SUCESSO!")
    print("=" * 80)
    print(f"Tempo total de execução: {tempo_total:.1f} segundos")
    print(f"Total de células de Voronoi processadas: {df['cell_id'].nunique():,} municípios")
    print(f"Total de registros meteorológicos diários: {len(df):,} linhas")
    print(f"Tamanho em memória: {df.memory_usage(deep=True).sum() / (1024 * 1024):.2f} MB")

    # Resumo estatístico das variáveis climáticas
    print("\n[3] Resumo Estatístico das Variáveis AquaCrop (MG - 2024):")
    resumo_vars = df[[
        "tmax_c", "tmin_c", "precipitacao_mm", "et0_mm", "radiacao_solar_mj_m2", "vento_10m_ms"
    ]].describe().T[["mean", "std", "min", "50%", "max"]]
    resumo_vars.columns = ["Média", "Desvio", "Mínimo", "Mediana", "Máximo"]
    print(resumo_vars.round(2).to_string())

    # Maiores e menores precipitações anuais em MG
    print("\n[4] Destaques Pluviométricos Anuais Acumulados (Top 3 e Bottom 3 em MG):")
    chuva_anual = df.groupby(["cell_id", "municipio"])["precipitacao_mm"].sum().reset_index()
    top_chuva = chuva_anual.sort_values("precipitacao_mm", ascending=False).head(3)
    bottom_chuva = chuva_anual.sort_values("precipitacao_mm", ascending=True).head(3)
    
    print("  + Mais chuvosos:")
    for _, r in top_chuva.iterrows():
        print(f"    - {r['municipio']}: {r['precipitacao_mm']:.1f} mm/ano")
    print("  - Menos chuvosos (Semiárido / Norte de MG):")
    for _, r in bottom_chuva.iterrows():
        print(f"    - {r['municipio']}: {r['precipitacao_mm']:.1f} mm/ano")

    # Arquivos persistidos
    print("\n[5] Arquivos gerados e disponíveis para uso:")
    caminho_base = Path("soilframe/data/era5land")
    print(f"  - Base Parquet (Alta performance): {caminho_base / 'era5land_aquacrop_mg_2024.parquet'}")
    print(f"  - Base CSV:                        {caminho_base / 'era5land_aquacrop_mg_2024.csv'}")
    print(f"  - Arquivos formatados FAO AquaCrop (.CLI, .TMP, .PLU, .ETo):")
    for arq in dataset.metadata.get("aquacrop_files", []):
        print(f"      * {arq}")


if __name__ == "__main__":
    main()
