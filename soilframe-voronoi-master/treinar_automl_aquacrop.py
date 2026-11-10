#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Criação e treinamento de Modelo de Classificação com AutoML no SoilFrame.

Utiliza os dados meteorológicos ERA5-Land AquaCrop baixados para Minas Gerais (MG)
para prever a classe de déficit hídrico e estresse da cultura para o próximo dia.

Uso:
    python treinar_automl_aquacrop.py
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

# Garante importação do soilframe
sys.path.insert(0, str(Path(__file__).resolve().parent / "soilframe"))

from soilframe import Dataset, Registry, ModeloAutoMLClassificador, Metricas


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 80)
    print(" SOILFRAME: TREINAMENTO DE MODELO DE CLASSIFICAÇÃO COM AUTOML")
    print(" Base de Dados: ERA5-Land AquaCrop (Minas Gerais - Ano 2024)")
    print("=" * 80)

    # 1. Carregamento dos dados baixados
    caminhos_candidatos = [
        Path("soilframe/data/era5land/era5land_aquacrop_mg_2024.parquet"),
        Path("data/era5land/era5land_aquacrop_mg_2024.parquet"),
    ]
    caminho_dados = next((p for p in caminhos_candidatos if p.exists()), None)
    if not caminho_dados:
        sys.exit("Erro: Arquivo Parquet do ERA5-Land não encontrado em data/era5land/.")

    print(f"\n[1] Carregando dataset meteorológico de: {caminho_dados}...")
    df_raw = pd.read_parquet(caminho_dados)
    dataset = Dataset(df_raw, metadata={"fonte": "ERA5-Land", "uf": "MG", "ano": 2024})
    print(f"    - Registros diários carregados: {len(df_raw):,}")
    print(f"    - Municípios / Células de Voronoi: {df_raw['cell_id'].nunique():,}")

    # 2. Descoberta via Registry do SoilFrame
    print("\n[2] Inicializando modelo via SoilFrame Registry...")
    registry = Registry()
    modelo = registry.get_model("modelo_automl_classificador")
    
    # Configura o objetivo agronômico: prever o estresse hídrico do dia seguinte
    modelo.modo_predicao = "proximo_dia"
    modelo.alvo = "classe_deficit_hidrico"

    print(f"    - Modelo instanciado: {modelo.name} (v{modelo.version})")
    print(f"    - Alvo agronômico: '{modelo.alvo}'")
    print(f"    - Modo de operação: '{modelo.modo_predicao}' (Previsão antecipada para manejo)")

    # 3. Execução do AutoML (Competição de 5 Algoritmos)
    print("\n[3] Iniciando competição AutoML com 5-Fold Stratified Cross Validation...")
    modelo.treinar(dataset)

    # 4. Tabela de Leaderboard do AutoML
    print("\n" + "=" * 80)
    print(" LEADERBOARD AUTOML (RANKING DOS MODELOS)")
    print("=" * 80)
    leaderboard = modelo.tabela_leaderboard()
    print(leaderboard.to_string(index=False))

    # 5. Avaliação Formal pelo SoilFrame
    print("\n[5] Avaliação do modelo vencedor sobre o conjunto de teste holdout:")
    metricas = modelo.avaliar(dataset)
    for k, v in metricas.valores.items():
        print(f"    - {k}: {v}")

    # 6. Importância das Variáveis Climáticas
    print("\n[6] Importância das Features na Decisão do Modelo:")
    imp = modelo.importancia_features(top_n=8)
    for _, r in imp.iterrows():
        barra = "#" * int(r["importancia"] * 35)
        print(f"    {r['feature']:<25} | {r['importancia']:.4f} | {barra}")

    # 7. Demonstração de Predições e Confiança
    print("\n[7] Exemplo de predições geradas para novas observações:")
    amostra = Dataset(df_raw.tail(5))
    predicoes = modelo.prever(amostra)
    cols_exibir = [
        "municipio", "data", "tmax_c", "precipitacao_mm", "et0_mm",
        f"previsao_{modelo.alvo}", "confianca_previsao"
    ]
    cols_validas = [c for c in cols_exibir if c in predicoes.data.columns]
    print(predicoes.data[cols_validas].to_string(index=False))

    # 8. Persistência do Modelo no Repositório
    print("\n[8] Salvando artefatos do modelo treinado...")
    pasta_saida = Path("outputs/models/automl_aquacrop_v1")
    modelo.salvar(pasta_saida, metadata={"dataset_treino": str(caminho_dados), "uf": "MG"})
    print(f"    - Modelo serializado com sucesso em: {pasta_saida.resolve()}")
    print(f"    - Artefatos gerados: model.pkl, metadata.json, leaderboard.csv")

    print("\n" + "=" * 80)
    print(" TREINAMENTO E VALIDAÇÃO AUTOML CONCLUÍDOS COM SUCESSO!")
    print("=" * 80)


if __name__ == "__main__":
    main()
