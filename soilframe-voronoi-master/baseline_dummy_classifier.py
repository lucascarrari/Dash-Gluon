#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Baseline com DummyClassifier (Estratégia Constante: 'Sim' / Classe Positiva).

Este script demonstra como implementar e avaliar um DummyClassifier do Scikit-Learn
que sempre prevê a classe positiva ('Sim') para qualquer entrada de dados, servindo
como Linha de Base (Baseline) para comparação com modelos preditivos reais.

Uso:
    python baseline_dummy_classifier.py
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split

# Configura encoding de saída para terminais Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def exemplo_didatico():
    """Demonstração básica e didática do DummyClassifier com valor constante 'Sim'."""
    print("=" * 80)
    print(" 1. EXEMPLO BÁSICO: DUMMYCLASSIFIER SEMPRE PREVENDO 'Sim'")
    print("=" * 80)

    # Dados de exemplo: 10 amostras com desbalanceamento (7 'Sim', 3 'Não')
    X_treino = np.array([[25.0], [30.0], [18.0], [22.0], [35.0], [28.0], [20.0]])
    y_treino = np.array(["Sim", "Sim", "Não", "Sim", "Não", "Sim", "Sim"])

    X_teste = np.array([[29.0], [15.0], [33.0]])
    y_teste = np.array(["Sim", "Não", "Sim"])

    # Instancia o DummyClassifier com estratégia constante 'Sim'
    dummy = DummyClassifier(strategy="constant", constant="Sim")
    dummy.fit(X_treino, y_treino)

    # Predição para novas amostras
    predicoes = dummy.predict(X_teste)

    print(f"Entradas de Teste (X_teste):\n{X_teste.ravel().tolist()}")
    print(f"Rótulos Reais (y_teste):     {y_teste.tolist()}")
    print(f"Predições do Modelo Dummy:   {predicoes.tolist()}")
    print(f"Acurácia obtida:             {accuracy_score(y_teste, predicoes):.2%}")
    print()


def avaliar_classificador(nome: str, y_real: np.ndarray, y_pred: np.ndarray, rotulos: list[str]) -> dict[str, float]:
    """Calcula e formata métricas detalhadas de avaliação para comparação."""
    acc = accuracy_score(y_real, y_pred)
    bal_acc = balanced_accuracy_score(y_real, y_pred)
    prec_sim = precision_score(y_real, y_pred, pos_label="Sim", zero_division=0)
    rec_sim = recall_score(y_real, y_pred, pos_label="Sim", zero_division=0)
    rec_nao = recall_score(y_real, y_pred, pos_label="Não", zero_division=0)
    f1_macro = f1_score(y_real, y_pred, average="macro")

    return {
        "Modelo": nome,
        "Acurácia": acc,
        "Acurácia Balanceada": bal_acc,
        "Precisão (Sim)": prec_sim,
        "Recall (Sim)": rec_sim,
        "Recall (Não)": rec_nao,
        "F1 Macro": f1_macro,
    }


def imprimir_matriz_confusao(y_real: np.ndarray, y_pred: np.ndarray, titulo: str):
    """Exibe matriz de confusão formatada no console."""
    cm = confusion_matrix(y_real, y_pred, labels=["Sim", "Não"])
    print(f"\n--- Matriz de Confusão: {titulo} ---")
    print("                     Predito: Sim | Predito: Não")
    print(f"  Real: Sim (Positivo)   {cm[0, 0]:>11,} | {cm[0, 1]:>12,}")
    print(f"  Real: Não (Negativo)   {cm[1, 0]:>11,} | {cm[1, 1]:>12,}")


def benchmark_com_dados_reais():
    """Compara o DummyClassifier ('Sempre Sim') com o Modelo Real na base ERA5-Land AquaCrop."""
    print("=" * 80)
    print(" 2. BENCHMARK REAL: BASELINE 'SEMPRE SIM' VS MODELO REAL (ERA5-LAND)")
    print(" Problema: Prever se haverá Déficit Hídrico amanhã ('Sim' ou 'Não')")
    print("=" * 80)

    caminhos = [
        Path("soilframe/data/era5land/era5land_aquacrop_mg_2024.parquet"),
        Path("data/era5land/era5land_aquacrop_mg_2024.parquet"),
    ]
    caminho = next((p for p in caminhos if p.exists()), None)
    if not caminho:
        print("[Aviso] Dataset ERA5-Land não encontrado. Executando apenas exemplo sintético.")
        return

    # 1. Carrega dados reais de Minas Gerais (73.200 amostras)
    df = pd.read_parquet(caminho)

    # 2. Define o alvo binário agronômico: Balanço Hídrico Diário < 0 -> 'Sim' (tem déficit), >= 0 -> 'Não'
    df["balanco_hidrico"] = df["precipitacao_mm"] - df["et0_mm"]
    df["tem_deficit_hoje"] = np.where(df["balanco_hidrico"] < 0, "Sim", "Não")

    # Alvo do dia seguinte (t+1) por município
    df["alvo_amanha"] = df.groupby("cell_id")["tem_deficit_hoje"].shift(-1)
    df_valido = df.dropna(subset=["alvo_amanha"]).reset_index(drop=True)

    # Features preditivas (tmax, tmin, chuva, et0, radiação, etc.)
    features = [
        "tmax_c", "tmin_c", "precipitacao_mm", "et0_mm",
        "radiacao_solar_mj_m2", "vento_10m_ms", "lat", "lon"
    ]
    X = df_valido[features].to_numpy(dtype=float)
    y = df_valido["alvo_amanha"].to_numpy(dtype=str)

    # Divisão Treino e Teste Holdout (80% treino / 20% teste)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    contagem_teste = pd.Series(y_test).value_counts()
    prop_sim = (y_test == "Sim").mean()
    print(f"Total de amostras no conjunto de teste: {len(y_test):,}")
    print(f"Distribuição real: 'Sim' = {contagem_teste.get('Sim', 0):,} ({prop_sim:.2%}) | 'Não' = {contagem_teste.get('Não', 0):,} ({1 - prop_sim:.2%})\n")

    # =========================================================================
    # MODELO 1: BASELINE DUMMY CLASSIFIER (SEMPRE RESPONDE 'Sim')
    # =========================================================================
    dummy_sempre_sim = DummyClassifier(strategy="constant", constant="Sim")
    dummy_sempre_sim.fit(X_train, y_train)
    y_pred_dummy = dummy_sempre_sim.predict(X_test)

    # =========================================================================
    # MODELO 2: MODELO REAL (HistGradientBoosting / Machine Learning)
    # =========================================================================
    from sklearn.ensemble import HistGradientBoostingClassifier
    modelo_real = HistGradientBoostingClassifier(random_state=42, max_iter=100)
    modelo_real.fit(X_train, y_train)
    y_pred_real = modelo_real.predict(X_test)

    # =========================================================================
    # COMPARAÇÃO E RESULTADOS
    # =========================================================================
    m_dummy = avaliar_classificador("Baseline: Dummy (Sempre 'Sim')", y_test, y_pred_dummy, ["Sim", "Não"])
    m_real = avaliar_classificador("Modelo Real: HistGradientBoosting", y_test, y_pred_real, ["Sim", "Não"])

    df_comparacao = pd.DataFrame([m_dummy, m_real])
    colunas_format = ["Acurácia", "Acurácia Balanceada", "Precisão (Sim)", "Recall (Sim)", "Recall (Não)", "F1 Macro"]
    
    print("=" * 80)
    print(" TABELA COMPARATIVA DE DESEMPENHO: BASELINE VS MODELO REAL")
    print("=" * 80)
    # Formata colunas percentuais
    df_exibir = df_comparacao.copy()
    for col in colunas_format:
        df_exibir[col] = df_exibir[col].apply(lambda v: f"{v * 100:.2f}%")
    print(df_exibir.to_string(index=False))

    # Matrizes de confusão
    imprimir_matriz_confusao(y_test, y_pred_dummy, "Baseline Dummy (Sempre 'Sim')")
    imprimir_matriz_confusao(y_test, y_pred_real, "Modelo Real (HistGradientBoosting)")

    # Explicação didática dos resultados
    print("\n" + "=" * 80)
    print(" INSIGHTS E INTERPRETAÇÃO DA LINHA DE BASE (BASELINE)")
    print("=" * 80)
    print(f"1. Acurácia Ilusória do Dummy: {m_dummy['Acurácia']:.2%}")
    print(f"   -> Como a classe 'Sim' representa {prop_sim:.2%} dos dados, chutar sempre 'Sim'")
    print(f"      resulta em exatamente {m_dummy['Acurácia']:.2%} de acurácia sem aprender nada!")
    print(f"2. Falha Crítica do Dummy no Recall da classe 'Não': {m_dummy['Recall (Não)']:.2%}")
    print(f"   -> O Dummy nunca acerta quando NÃO haverá déficit (0 acertos em {contagem_teste.get('Não', 0):,} dias normais).")
    print(f"3. Ganho do Modelo Real:")
    print(f"   -> O modelo real eleva a Acurácia Balanceada de {m_dummy['Acurácia Balanceada']:.2%} para {m_real['Acurácia Balanceada']:.2%},")
    print(f"      sendo capaz de discriminar tanto os dias com estresse quanto os dias adequados.")
    print("=" * 80)


if __name__ == "__main__":
    exemplo_didatico()
    benchmark_com_dados_reais()
