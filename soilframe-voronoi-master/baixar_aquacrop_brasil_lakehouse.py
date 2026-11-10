#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Download das variáveis AquaCrop (ERA5-Land) para todos os estados do Brasil no SoilFrame.

Orquestra a arquitetura de Data Lakehouse em 3 camadas:
  - Camada Bronze: Armazenamento bruto dos dados diários por UF (ano 2024).
  - Camada Prata: Dados limpos, deduplicados e com validação de limites físicos.
  - Camada Ouro: Dados enriquecidos com indicadores agronômicos (balanço hídrico,
                classes de estresse, arquivos FAO AquaCrop .CLI, .TMP, .PLU, .ETo)
                e consolidação nacional.

Nota: Minas Gerais (MG) já foi executado e tem seus dados pré-existentes
automaticamente ingeridos e promovidos no Lakehouse, sem necessidade de re-download.

Uso:
    python baixar_aquacrop_brasil_lakehouse.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Garante importação do soilframe
sys.path.insert(0, str(Path(__file__).resolve().parent / "soilframe"))

from soilframe import LakehouseManager, PipelineAquaCropLakehouse, Registry

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    print("=" * 85)
    print(" SOILFRAME: DOWNLOAD NACIONAL ERA5-LAND AQUACROP (LAKEHOUSE: BRONZE, PRATA, OURO)")
    print(" Estratégia Espacial: Células de Voronoi (Malha Municipal Nacional)")
    print(" Estados Alvo: Todos os 26 estados do Brasil (Excluindo MG do re-download)")
    print(" Período: Janela de 1 Ano Completo (2024)")
    print("=" * 85)

    t_inicio = time.time()

    # 1. Obtenção da Pipeline no Registry
    print("\n[1] Inicializando Pipeline Lakehouse via SoilFrame Registry...")
    registry = Registry()
    pipeline = registry.get_pipeline("pipeline_aquacrop_lakehouse")

    # 2. Configuração da Execução
    # Para garantir download robusto e ágil dos 26 estados sem bloqueio de cota da API,
    # selecionamos as principais células municipais agrícolas de Voronoi de cada estado.
    configuracao = {
        "ano": 2024,
        "data_inicio": "2024-01-01",
        "data_fim": "2024-12-31",
        "celulas_por_uf": 5,  # Top células de Voronoi por UF (para os 26 estados)
        "lakehouse_dir": "soilframe/data/lakehouse",
        "ingerir_mg_existente": True,
    }

    print("\n[2] Parâmetros do Lakehouse:")
    print(f"    - Diretório Base: {configuracao['lakehouse_dir']}")
    print(f"    - Janela Temporal: {configuracao['data_inicio']} a {configuracao['data_fim']} (Ano {configuracao['ano']})")
    print(f"    - Células por UF: {configuracao['celulas_por_uf']} municípios representativos de Voronoi")
    print(f"    - Ingestão de MG: Sim (Aproveitando dados já baixados sem consumir API)")

    # 3. Execução da Pipeline
    print("\n[3] Disparando ingestão e processamento das 3 camadas...")
    dataset = pipeline.rodar(configuracao)

    # 4. Auditoria e Resumo das Camadas do Lakehouse
    lakehouse = LakehouseManager(base_dir=configuracao["lakehouse_dir"])
    resumo_df = lakehouse.resumo_lakehouse()

    print("\n" + "=" * 85)
    print(" STATUS AUDITADO DAS CAMADAS DO DATA LAKEHOUSE")
    print("=" * 85)
    print(resumo_df.to_string(index=False))

    tempo_decorrido = time.time() - t_inicio
    print("\n" + "=" * 85)
    print(" EXECUÇÃO DO LAKEHOUSE FINALIZADA COM SUCESSO!")
    print("=" * 85)
    print(f"Tempo total de execução: {tempo_decorrido:.1f} segundos")
    print(f"Total de registros consolidados na Camada Ouro: {len(dataset.data):,}")
    print(f"Estados presentes no Lakehouse: {dataset.data['uf'].nunique()} UFs")

    # Amostra dos dados enriquecidos na Camada Ouro
    print("\n[4] Amostra dos Dados Enriquecidos na Camada Ouro:")
    cols_exibir = [
        "uf", "municipio", "data", "tmax_c", "precipitacao_mm", "et0_mm",
        "balanco_hidrico_diario", "classe_deficit_hidrico"
    ]
    cols_validas = [c for c in cols_exibir if c in dataset.data.columns]
    print(dataset.data[cols_validas].head(8).to_string(index=False))

    # Caminhos físicos
    print("\n[5] Estrutura Física das Camadas Persistidas no Disco:")
    print(f"  - Bronze (Raw): {lakehouse.bronze_dir.resolve()}")
    print(f"  - Prata (Saneado): {lakehouse.prata_dir.resolve()}")
    ano_ref = configuracao["ano"]
    print(f"  - Base Nacional Ouro: {lakehouse.ouro_dir / f'brasil_aquacrop_{ano_ref}.parquet'}")
    print("=" * 85)


if __name__ == "__main__":
    main()
