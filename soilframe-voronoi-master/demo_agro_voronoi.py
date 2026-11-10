#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Demonstração de ponta a ponta da Estratégia de Download Agro-Voronoi integrada ao SoilFrame.

Uso:
    python demo_agro_voronoi.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante importação do soilframe
sys.path.insert(0, str(Path(__file__).resolve().parent / "soilframe"))

from soilframe import (
    EstrategiaDownloadVoronoi,
    EstrategiaDownloadUniforme,
    FonteSentinelVoronoi,
    Registry,
)


def main():
    print("=" * 80)
    print(" SOILFRAME: ESTRATÉGIA DE DOWNLOAD AGRO-VORONOI (SENTINEL-2 L2A)")
    print("=" * 80)

    # 1. Instanciação da Estratégia
    print("\n[1] Inicializando Estratégia Agro-Voronoi com perfil 'ndvi_scl' (FAO-56 Kc)...")
    est_voronoi = EstrategiaDownloadVoronoi(perfil_bandas="ndvi_scl", objetivo="area")
    
    # 2. Planejamento Brasil para 99% da área
    print("[2] Otimizando alocação nacional para meta de 99% da área de talhão visível...")
    plano_nacional = est_voronoi.planejar(meta_cobertura=0.99, datas_por_ano=73)

    print("\n" + plano_nacional.resumo_executivo())

    # 3. Resumo Regional
    print("\n[3] Distribuição da Alocação Ótima por Região:")
    regional = plano_nacional.resumo_regional()
    print(regional.to_string(index=False))

    # 4. Comparação direta com estratégia uniforme
    print("\n[4] Comparando com Estratégia Uniforme (baseline)...")
    pixel_ref = plano_nacional.metricas["pixel_uniforme_comparativo_m"]
    est_uniforme = EstrategiaDownloadUniforme(pixel_m=pixel_ref, perfil_bandas="ndvi_scl")
    plano_uniforme = est_uniforme.planejar()

    gb_vor = plano_nacional.metricas["gb_por_data"]
    gb_uni = plano_uniforme.metricas["gb_por_data"]
    gb_10m = plano_nacional.metricas["gb_tudo_10m"]

    print(f"  - Tudo a 10m (força bruta):       {gb_10m:8.2f} GB/data ({gb_10m * 73:8.1f} GB/ano)")
    print(f"  - Pixel uniforme ({pixel_ref}m):           {gb_uni:8.2f} GB/data ({gb_uni * 73:8.1f} GB/ano)")
    print(f"  - Agro-Voronoi otimizado:         {gb_vor:8.2f} GB/data ({gb_vor * 73:8.1f} GB/ano)")
    print(f"  --> Economia frente ao uniforme:   {plano_nacional.metricas['fator_reducao']:.1f}x menor")
    print(f"  --> Economia frente ao 10m:        {plano_nacional.metricas['fator_reducao_10m']:.1f}x menor")

    # 5. Planejamento com filtro regional (Mato Grosso)
    print("\n[5] Planejamento focado em Mato Grosso (UF='MT')...")
    plano_mt = est_voronoi.planejar(meta_cobertura=0.99, uf="MT")
    print(f"  - Células em MT: {len(plano_mt.tabela)}")
    print(f"  - Volume MT por data: {plano_mt.metricas['gb_por_data']:.2f} GB")
    print(f"  - Cobertura em MT: {plano_mt.metricas['cobertura_area']:.1%}")
    print("  - Amostra das primeiras 5 células em MT:")
    print(plano_mt.tabela[["nome", "area_km2", "pixel_m", "volume_mb", "cobertura_area"]].head(5).to_string(index=False))

    # 6. Uso como FonteDados no SoilFrame
    print("\n[6] Extração através de FonteSentinelVoronoi (FonteDados)...")
    fonte = FonteSentinelVoronoi(meta_cobertura=0.99, uf=["MT", "GO"], perfil_bandas="ndvi_scl")
    dataset_fonte = fonte.dataset()
    print(f"  - Dataset gerado com sucesso!")
    print(f"  - Linhas (células): {len(dataset_fonte.data)}")
    print(f"  - Metadados do Dataset: {list(dataset_fonte.metadata.keys())}")

    # Exemplo de payload STAC
    reqs = fonte.gerar_requisicoes_stac()
    print(f"  - Requisição STAC de exemplo para {reqs[0]['municipio']}-{reqs[0]['uf']}:")
    print(f"    Resolução: {reqs[0]['resolucao_alvo_m']}m | Volume estimado: {reqs[0]['volume_estimado_mb']:.2f} MB")
    print(f"    BBox: {reqs[0]['payload']['bbox']} | Bandas: {reqs[0]['assets_solicitados']}")

    # 7. Execução via Pipeline e Registry do SoilFrame
    print("\n[7] Descoberta e execução via SoilFrame Registry...")
    registry = Registry()
    pipeline = registry.get_pipeline("pipeline_download_sentinel")
    resultado = pipeline.rodar({
        "meta_cobertura": 0.99,
        "perfil_bandas": "ndvi_scl",
        "uf": "BA",
    })
    print(f"  - Pipeline executada: {resultado.metadata['pipeline']}")
    print(f"  - Volume Bahia (BA) por data: {resultado.metadata['gb_por_data']:.2f} GB")
    print(f"  - Cobertura estimada: {resultado.metadata['cobertura_area']:.1%}")

    print("\n" + "=" * 80)
    print(" DEMONSTRAÇÃO CONCLUÍDA COM SUCESSO!")
    print("=" * 80)


if __name__ == "__main__":
    main()
