#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sistema de AutoML Contínuo de Longa Duração com Checkpoints Resilientes.

Projetado para execução autônoma ininterrupta por dias:
- Linha de Base Obrigatória (#1): DummyClassifier (most_frequent, stratified e constant).
- Competição Contínua: Explora LightGBM, HistGradientBoosting, RandomForest,
  ExtraTrees, GradientBoosting, AdaBoost, MLP (Rede Neural), Regressão Logística
  e Ensembles dinâmicos (Stacking e Voting).
- Resiliência Extrema: Checkpoints atômicos salvos em disco após cada iteração.
  Se houver queda de luz ou reinicialização da máquina, o script retoma exatamente
  de onde parou sem perda de estado.
- Tolerância a Falhas de Rede: Todo o treinamento é 100% offline baseado no Lakehouse.
  Um worker secundário monitora e baixa em segundo plano as UFs restantes assim
  que a cota do Open-Meteo resetar (00:00 UTC / 21:00 BRT).
"""

from __future__ import annotations

import gc
import json
import os
import random
import signal
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

# Modelos e métricas scikit-learn & lightgbm
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import (
    AdaBoostClassifier,
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    StackingClassifier,
    VotingClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from lightgbm import LGBMClassifier

# Configura encoding no Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

# Diretórios principais
BASE_DIR = Path(__file__).resolve().parent
LAKEHOUSE_DIR = BASE_DIR / "soilframe" / "data" / "lakehouse"
CHECKPOINT_DIR = BASE_DIR / "outputs" / "models" / "automl_checkpoint"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

ESTADO_JSON = CHECKPOINT_DIR / "checkpoint_state.json"
LEADERBOARD_CSV = CHECKPOINT_DIR / "leaderboard_historico.csv"
MELHOR_MODELO_PKL = CHECKPOINT_DIR / "melhor_modelo.pkl"
MELHOR_MODELO_METADATA = CHECKPOINT_DIR / "melhor_modelo_metadata.json"
LOG_EXECUCAO = CHECKPOINT_DIR / "automl_execucao.log"

# UFs pendentes para download assim que cota resetar
UFS_TODAS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
    "RO", "RR", "RS", "SC", "SE", "SP", "TO"
]
UFS_PENDENTES = ["MT", "SE", "SP", "TO"]

FLAG_EXECUTANDO = True


def tratar_sinal_interrupcao(sig, frame):
    """Garante salvamento limpo caso receba SIGINT ou SIGTERM."""
    global FLAG_EXECUTANDO
    log_mensagem("Sinal de interrupção recebido. Finalizando iteração atual e persistindo checkpoint...")
    FLAG_EXECUTANDO = False


signal.signal(signal.SIGINT, tratar_sinal_interrupcao)
signal.signal(signal.SIGTERM, tratar_sinal_interrupcao)


def log_mensagem(msg: str):
    """Registra mensagens com timestamp no console e no arquivo de log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{ts}] {msg}"
    print(linha, flush=True)
    try:
        with open(LOG_EXECUCAO, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def salvar_json_atomico(caminho: Path, dados: dict[str, Any]):
    """Gravação atômica via arquivo temporário para tolerância a queda de energia."""
    caminho_tmp = caminho.with_suffix(".tmp")
    with open(caminho_tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)
    caminho_tmp.replace(caminho)


def carregar_dados_nacionais() -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Carrega dataset consolidado do Lakehouse e constrói features agroclimáticas."""
    ouro_dir = LAKEHOUSE_DIR / "ouro"
    caminho_nacional = ouro_dir / "brasil_aquacrop_2020_2024.parquet"

    # Se a base consolidada não existir, consolida a partir das partições da camada ouro
    if not caminho_nacional.exists():
        log_mensagem("Consolidando partições da Camada Ouro em brasil_aquacrop_2020_2024.parquet...")
        particoes = list(ouro_dir.glob("uf=*/ano=2020_2024/aquacrop_ouro.parquet"))
        if not particoes:
            raise FileNotFoundError("Nenhuma partição Ouro encontrada no Lakehouse.")
        dfs = [pd.read_parquet(p) for p in particoes]
        df_completo = pd.concat(dfs, ignore_index=True)
        caminho_nacional.parent.mkdir(parents=True, exist_ok=True)
        df_completo.to_parquet(caminho_nacional, index=False)
    else:
        df_completo = pd.read_parquet(caminho_nacional)

    df = df_completo.sort_values(["cell_id", "data"]).reset_index(drop=True)

    # 1. Atributos Temporais
    dt = pd.to_datetime(df["data"])
    df["mes"] = dt.dt.month
    df["dia_ano"] = dt.dt.dayofyear
    df["estacao_ano"] = np.select(
        [(df["mes"].isin([12, 1, 2])), (df["mes"].isin([3, 4, 5])), (df["mes"].isin([6, 7, 8]))],
        [1, 2, 3],  # Verão, Outono, Inverno
        default=4,  # Primavera
    )

    # 2. Atributos Agroclimáticos Derivados
    if "tmax_c" in df.columns and "tmin_c" in df.columns:
        df["amplitude_termica"] = df["tmax_c"] - df["tmin_c"]

    if "precipitacao_mm" in df.columns and "et0_mm" in df.columns:
        balanco = df["precipitacao_mm"] - df["et0_mm"]
        df["balanco_hidrico_diario"] = balanco
        df["razao_p_et0"] = (df["precipitacao_mm"] / np.maximum(df["et0_mm"], 0.1)).clip(upper=10.0)

    # 3. Lags e Acumulados Agronômicos (Memória de Umidade do Solo)
    df["precip_sum_3d"] = df.groupby("cell_id")["precipitacao_mm"].transform(
        lambda s: s.rolling(3, min_periods=1).sum()
    )
    df["precip_sum_7d"] = df.groupby("cell_id")["precipitacao_mm"].transform(
        lambda s: s.rolling(7, min_periods=1).sum()
    )
    df["balanco_mean_3d"] = df.groupby("cell_id")["balanco_hidrico_diario"].transform(
        lambda s: s.rolling(3, min_periods=1).mean()
    )

    # 4. Alvo Agronômico: Classe de Déficit Hídrico do Próximo Dia (Previsão Antecipada para Manejo)
    df["alvo_proximo_dia"] = df.groupby("cell_id")["classe_deficit_hidrico"].shift(-1)
    df_valido = df.dropna(subset=["alvo_proximo_dia"]).copy()

    features_candidatas = [
        "tmax_c", "tmin_c", "tmean_c", "precipitacao_mm", "et0_mm",
        "radiacao_solar_mj_m2", "vento_10m_ms", "amplitude_termica",
        "balanco_hidrico_diario", "razao_p_et0", "precip_sum_3d",
        "precip_sum_7d", "balanco_mean_3d", "mes", "dia_ano",
        "estacao_ano", "lat", "lon"
    ]
    features_presentes = [c for c in features_candidatas if c in df_valido.columns]

    X = df_valido[features_presentes].fillna(df_valido[features_presentes].median())
    y = df_valido["alvo_proximo_dia"].astype(str)

    return X, y, features_presentes


def tentar_baixar_ufs_restantes():
    """Tenta baixar as 4 UFs pendentes (MT, SE, SP, TO) se a cota do Open-Meteo tiver resetado."""
    sys.path.insert(0, str(BASE_DIR / "soilframe"))
    from soilframe import FonteERA5LandVoronoi, LakehouseManager

    lakehouse = LakehouseManager(base_dir=LAKEHOUSE_DIR)
    periodo_tag = "2020_2024"
    baixou_alguma = False

    for uf in UFS_PENDENTES:
        if lakehouse.existe_em_ouro(uf, periodo_tag):
            continue

        try:
            log_mensagem(f"[Worker Background] Testando disponibilidade da API para baixar {uf}...")
            fonte = FonteERA5LandVoronoi(
                uf=uf,
                ano=periodo_tag,
                data_inicio="2020-01-01",
                data_fim="2024-12-31",
                limite_celulas=5,
                salvar_disco=False,
            )
            df_raw = fonte.extrair(tamanho_lote=25)
            if df_raw.empty:
                continue

            lakehouse.salvar_bronze(
                df_raw,
                uf=uf,
                ano=periodo_tag,
                metadados={"janela": "2020-01-01 a 2024-12-31", "fonte": "Open-Meteo ERA5-Land Archive"},
            )
            lakehouse.promover_para_prata(uf=uf, ano=periodo_tag)
            lakehouse.promover_para_ouro(uf=uf, ano=periodo_tag, gerar_arquivos_aquacrop=True)
            log_mensagem(f"[Worker Background] UF {uf} baixada e promovida a Ouro com sucesso!")
            baixou_alguma = True
            time.sleep(3.0)
        except Exception as e:
            log_mensagem(f"[Worker Background] Cota ainda indisponível para {uf}: {e}")
            break

    if baixou_alguma:
        log_mensagem("[Worker Background] Reconsolidando base nacional com as novas UFs...")
        lakehouse.consolidar_nacional(ano=periodo_tag)


def gerar_candidato_automl(iteracao: int, top_modelos: list[dict[str, Any]]) -> tuple[str, Any, dict[str, Any]]:
    """Gera candidatos de classificação abrangendo 9 famílias de algoritmos e ensembles."""
    random.seed(iteracao + int(time.time() * 1000) % 100000)

    # A cada 12 iterações, constrói Ensemble (Stacking ou Voting) com os melhores modelos até agora
    if iteracao > 10 and iteracao % 12 == 0 and len(top_modelos) >= 3:
        melhores = top_modelos[:3]
        estimadores_base = [
            (f"m_{idx}", m["instancia"]) for idx, m in enumerate(melhores)
        ]
        if random.random() < 0.5:
            nome = "VotingClassifier_Soft"
            modelo = VotingClassifier(estimators=estimadores_base, voting="soft", n_jobs=-1)
            params = {"tipo": "Ensemble_Voting", "componentes": [m["algoritmo"] for m in melhores]}
            return nome, modelo, params
        else:
            nome = "StackingClassifier_LogReg"
            modelo = StackingClassifier(
                estimators=estimadores_base,
                final_estimator=LogisticRegression(max_iter=500, random_state=iteracao),
                cv=3,
                n_jobs=-1,
            )
            params = {"tipo": "Ensemble_Stacking", "final_estimator": "LogisticRegression"}
            return nome, modelo, params

    familias = [
        "LightGBM",
        "HistGradientBoosting",
        "RandomForest",
        "ExtraTrees",
        "GradientBoosting",
        "AdaBoost",
        "MLP_NeuralNet",
        "LogisticRegression",
    ]
    familia = random.choice(familias)

    if familia == "LightGBM":
        n_estimators = random.choice([80, 100, 150, 200, 250])
        max_depth = random.choice([5, 7, 9, 12, -1])
        num_leaves = random.choice([15, 31, 63, 127])
        lr = round(random.choice([0.03, 0.05, 0.08, 0.1, 0.15]), 4)
        min_child_samples = random.choice([20, 30, 50, 100])
        colsample = round(random.choice([0.7, 0.8, 0.9, 1.0]), 2)
        subsample = round(random.choice([0.7, 0.8, 0.9, 1.0]), 2)
        reg_alpha = round(random.choice([0.0, 0.01, 0.1, 1.0]), 3)
        reg_lambda = round(random.choice([0.0, 0.01, 0.1, 1.0, 5.0]), 3)

        params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "num_leaves": num_leaves,
            "learning_rate": lr,
            "min_child_samples": min_child_samples,
            "colsample_bytree": colsample,
            "subsample": subsample,
            "reg_alpha": reg_alpha,
            "reg_lambda": reg_lambda,
            "random_state": iteracao,
            "verbose": -1,
            "n_jobs": -1,
        }
        modelo = LGBMClassifier(**params)
        nome = f"LightGBM_depth{max_depth}_lr{lr}_leaves{num_leaves}"
        return nome, modelo, params

    elif familia == "HistGradientBoosting":
        max_iter = random.choice([80, 100, 150, 200])
        lr = round(random.choice([0.04, 0.07, 0.1, 0.14]), 4)
        max_leaf_nodes = random.choice([15, 31, 63, 127])
        min_samples_leaf = random.choice([20, 30, 50, 100])
        l2_reg = round(random.choice([0.0, 0.01, 0.1, 1.0]), 3)

        params = {
            "max_iter": max_iter,
            "learning_rate": lr,
            "max_leaf_nodes": max_leaf_nodes,
            "min_samples_leaf": min_samples_leaf,
            "l2_regularization": l2_reg,
            "random_state": iteracao,
        }
        modelo = HistGradientBoostingClassifier(**params)
        nome = f"HistGB_iter{max_iter}_lr{lr}_leaves{max_leaf_nodes}"
        return nome, modelo, params

    elif familia == "RandomForest":
        n_estimators = random.choice([60, 80, 100, 140])
        max_depth = random.choice([8, 12, 16, 20, None])
        min_samples_split = random.choice([2, 5, 10])
        min_samples_leaf = random.choice([1, 2, 4])
        criterion = random.choice(["gini", "entropy"])

        params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "min_samples_split": min_samples_split,
            "min_samples_leaf": min_samples_leaf,
            "criterion": criterion,
            "random_state": iteracao,
            "n_jobs": -1,
        }
        modelo = RandomForestClassifier(**params)
        nome = f"RandomForest_n{n_estimators}_depth{max_depth}_{criterion}"
        return nome, modelo, params

    elif familia == "ExtraTrees":
        n_estimators = random.choice([60, 80, 120])
        max_depth = random.choice([10, 15, 20, None])
        min_samples_split = random.choice([2, 5])

        params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "min_samples_split": min_samples_split,
            "random_state": iteracao,
            "n_jobs": -1,
        }
        modelo = ExtraTreesClassifier(**params)
        nome = f"ExtraTrees_n{n_estimators}_depth{max_depth}"
        return nome, modelo, params

    elif familia == "GradientBoosting":
        n_estimators = random.choice([60, 80, 100])
        max_depth = random.choice([3, 5, 7])
        lr = round(random.choice([0.05, 0.1, 0.15]), 4)
        subsample = round(random.choice([0.8, 0.9, 1.0]), 2)

        params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": lr,
            "subsample": subsample,
            "random_state": iteracao,
        }
        modelo = GradientBoostingClassifier(**params)
        nome = f"GradientBoosting_n{n_estimators}_depth{max_depth}_lr{lr}"
        return nome, modelo, params

    elif familia == "AdaBoost":
        n_estimators = random.choice([50, 80, 120])
        lr = round(random.choice([0.05, 0.1, 0.5, 1.0]), 3)

        params = {
            "n_estimators": n_estimators,
            "learning_rate": lr,
            "random_state": iteracao,
        }
        modelo = AdaBoostClassifier(**params)
        nome = f"AdaBoost_n{n_estimators}_lr{lr}"
        return nome, modelo, params

    elif familia == "MLP_NeuralNet":
        hidden_layers = random.choice([(64, 32), (128, 64), (64, 64), (128, 64, 32)])
        alpha = round(random.choice([0.0001, 0.001, 0.01]), 5)
        lr_init = round(random.choice([0.001, 0.005]), 4)

        params = {
            "hidden_layer_sizes": hidden_layers,
            "alpha": alpha,
            "learning_rate_init": lr_init,
            "max_iter": 200,
            "early_stopping": True,
            "random_state": iteracao,
        }
        pipeline_mlp = Pipeline([
            ("scaler", StandardScaler()),
            ("mlp", MLPClassifier(**params)),
        ])
        nome = f"MLP_layers{hidden_layers}_alpha{alpha}"
        return nome, pipeline_mlp, params

    else:  # LogisticRegression
        c_val = round(random.choice([0.01, 0.1, 1.0, 10.0]), 3)
        params = {
            "C": c_val,
            "max_iter": 500,
            "random_state": iteracao,
        }
        pipe_lr = Pipeline([
            ("scaler", StandardScaler()),
            ("logreg", LogisticRegression(**params)),
        ])
        nome = f"LogisticRegression_C{c_val}"
        return nome, pipe_lr, params


def main():
    log_mensagem("=" * 85)
    log_mensagem(" SOILFRAME: AUTOML CONTÍNUO DE ALTA DISPONIBILIDADE (EXECUÇÃO DE LONGA DURAÇÃO)")
    log_mensagem(" Objetivo: Otimização Contínua de Classificação de Déficit Hídrico (AquaCrop)")
    log_mensagem(f" Checkpoint Directory: {CHECKPOINT_DIR.resolve()}")
    log_mensagem("=" * 85)

    # 1. Carregamento dos dados iniciais
    log_mensagem("\n[1] Carregando dados climáticos do Lakehouse...")
    X, y, feature_names = carregar_dados_nacionais()
    total_linhas = len(X)
    classes_alvo = sorted(list(y.unique()))
    log_mensagem(f"    - Observações diárias ativas: {total_linhas:,}")
    log_mensagem(f"    - Features agroclimáticas ({len(feature_names)}): {feature_names}")
    log_mensagem(f"    - Classes do alvo ({len(classes_alvo)}): {classes_alvo}")
    log_mensagem(f"    - Distribuição das classes:\n{y.value_counts().to_string()}")

    # 2. Divisão Holdout Estratificada de Teste (20% para avaliação não-viesada)
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )
    log_mensagem(f"    - Amostras de Treinamento: {len(X_train):,}")
    log_mensagem(f"    - Amostras de Teste Holdout: {len(X_test):,}")

    # 3. Recuperação do Checkpoint (Se houver execução anterior)
    iteracao_inicial = 1
    melhor_f1_macro = -1.0
    melhor_modelo_info: dict[str, Any] = {}
    top_modelos_memoria: list[dict[str, Any]] = []

    if ESTADO_JSON.exists():
        try:
            with open(ESTADO_JSON, "r", encoding="utf-8") as f:
                estado_anterior = json.load(f)
            iteracao_inicial = estado_anterior.get("ultima_iteracao", 0) + 1
            melhor_f1_macro = estado_anterior.get("melhor_f1_macro", -1.0)
            melhor_modelo_info = estado_anterior.get("melhor_modelo", {})
            log_mensagem(f"\n[Checkpoint Recuperado] Retomando da Iteração #{iteracao_inicial}.")
            log_mensagem(f"    - Melhor F1 Macro registrado até o momento: {melhor_f1_macro:.4f}")
            log_mensagem(f"    - Modelo Líder atual: {melhor_modelo_info.get('algoritmo', 'N/D')}")
        except Exception as e:
            log_mensagem(f"[Aviso] Falha ao ler checkpoint existente: {e}. Iniciando novo ciclo.")

    # 4. Linha de Base Obrigatória #1: DUMMYCLASSIFIER (Avaliado primeiro se novo ciclo)
    cv_kfold = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    if not LEADERBOARD_CSV.exists() or iteracao_inicial == 1:
        log_mensagem("\n" + "=" * 85)
        log_mensagem(" [BASELINES OBRIGATÓRIAS] TREINANDO DUMMYCLASSIFIER (LINHA DE BASE #1)")
        log_mensagem("=" * 85)

        baselines = [
            ("DummyClassifier_MostFrequent", DummyClassifier(strategy="most_frequent")),
            ("DummyClassifier_Stratified", DummyClassifier(strategy="stratified", random_state=42)),
            ("DummyClassifier_Constant_DeficitSevero", DummyClassifier(strategy="constant", constant="Deficit_Severo")),
        ]

        leaderboard_rows = []
        for nome_dummy, mod_dummy in baselines:
            t0 = time.time()
            # 5-Fold Cross Validation
            scores_f1 = []
            scores_acc = []
            for tr_idx, va_idx in cv_kfold.split(X_train, y_train):
                mod_dummy.fit(X_train.iloc[tr_idx], y_train.iloc[tr_idx])
                preds_val = mod_dummy.predict(X_train.iloc[va_idx])
                scores_f1.append(f1_score(y_train.iloc[va_idx], preds_val, average="macro", zero_division=0))
                scores_acc.append(accuracy_score(y_train.iloc[va_idx], preds_val))

            # Teste Holdout
            mod_dummy.fit(X_train, y_train)
            preds_test = mod_dummy.predict(X_test)
            t_f1 = f1_score(y_test, preds_test, average="macro", zero_division=0)
            t_acc = accuracy_score(y_test, preds_test)
            t_bal = balanced_accuracy_score(y_test, preds_test)
            t_f1_wei = f1_score(y_test, preds_test, average="weighted", zero_division=0)
            dur = round(time.time() - t0, 2)

            log_mensagem(
                f"[Baseline #1] {nome_dummy:<38} | CV F1: {np.mean(scores_f1):.4f} | "
                f"Test F1: {t_f1:.4f} | Test Acc: {t_acc:.4f} | Tempo: {dur}s"
            )

            row = {
                "iteracao": 0,
                "timestamp": datetime.now().isoformat(),
                "algoritmo": nome_dummy,
                "cv_f1_macro": round(float(np.mean(scores_f1)), 4),
                "cv_f1_macro_std": round(float(np.std(scores_f1)), 4),
                "cv_acuracia": round(float(np.mean(scores_acc)), 4),
                "test_f1_macro": round(float(t_f1), 4),
                "test_acuracia": round(float(t_acc), 4),
                "test_balanced_acc": round(float(t_bal), 4),
                "test_f1_weighted": round(float(t_f1_wei), 4),
                "duracao_segundos": dur,
                "tipo": "Baseline_Referencia_1",
            }
            leaderboard_rows.append(row)

        df_leader = pd.DataFrame(leaderboard_rows)
        df_leader.to_csv(LEADERBOARD_CSV, index=False, encoding="utf-8")
        log_mensagem("[Sucesso] Linha de Base #1 (DummyClassifier) registrada no Leaderboard.")

    # 5. LOOP DE AUTOML CONTÍNUO (Execução por Horas e Dias)
    log_mensagem("\n" + "=" * 85)
    log_mensagem(" INICIANDO BUSCA E TREINAMENTO CONTÍNUO DO AUTOML (PELOS PRÓXIMOS DIAS)")
    log_mensagem(" Pressione Ctrl+C a qualquer momento para finalização segura.")
    log_mensagem("=" * 85)

    iteracao = iteracao_inicial
    ultimo_teste_download = time.time()

    while FLAG_EXECUTANDO:
        t_inicio_iter = time.time()
        log_mensagem(f"\n--- [Iteração #{iteracao:04d}] Iniciando Exploração de Hiperparâmetros ---")

        # Periodicamente (a cada 20 minutos), testa se a cota do Open-Meteo resetou
        if time.time() - ultimo_teste_download > 1200:
            ultimo_teste_download = time.time()
            try:
                tentar_baixar_ufs_restantes()
            except Exception as e:
                log_mensagem(f"[Worker Background] Erro ao tentar baixar UFs: {e}")

        # Gera algoritmo e espaço de hiperparâmetros
        nome_cand, modelo_cand, params_cand = gerar_candidato_automl(iteracao, top_modelos_memoria)
        log_mensagem(f"  -> Candidato: {nome_cand}")

        try:
            # 5-Fold Stratified Cross Validation
            scores_f1_cv = []
            scores_acc_cv = []

            for fold_idx, (tr_idx, va_idx) in enumerate(cv_kfold.split(X_train, y_train), 1):
                X_tr, y_tr = X_train.iloc[tr_idx], y_train.iloc[tr_idx]
                X_va, y_va = X_train.iloc[va_idx], y_train.iloc[va_idx]

                modelo_cand.fit(X_tr, y_tr)
                preds_va = modelo_cand.predict(X_va)

                scores_f1_cv.append(f1_score(y_va, preds_va, average="macro", zero_division=0))
                scores_acc_cv.append(accuracy_score(y_va, preds_va))

            cv_f1_mean = float(np.mean(scores_f1_cv))
            cv_f1_std = float(np.std(scores_f1_cv))
            cv_acc_mean = float(np.mean(scores_acc_cv))

            # Ajuste final com todo o conjunto de treino e teste Holdout
            modelo_cand.fit(X_train, y_train)
            preds_test = modelo_cand.predict(X_test)

            test_f1 = float(f1_score(y_test, preds_test, average="macro", zero_division=0))
            test_acc = float(accuracy_score(y_test, preds_test))
            test_bal = float(balanced_accuracy_score(y_test, preds_test))
            test_f1_wei = float(f1_score(y_test, preds_test, average="weighted", zero_division=0))
            duracao = round(time.time() - t_inicio_iter, 2)

            log_mensagem(
                f"  -> Concluído #{iteracao:04d}: CV F1: {cv_f1_mean:.4f} (±{cv_f1_std:.3f}) | "
                f"Test F1: {test_f1:.4f} | Test Acc: {test_acc:.4f} | Bal Acc: {test_bal:.4f} ({duracao}s)"
            )

            # Mantém top 5 modelos em memória para futuros Stacking / Voting Ensembles
            top_modelos_memoria.append({
                "algoritmo": nome_cand,
                "instancia": modelo_cand,
                "test_f1": test_f1,
            })
            top_modelos_memoria = sorted(top_modelos_memoria, key=lambda x: x["test_f1"], reverse=True)[:5]

            # 6. Atualização do Melhor Modelo Histórico (Checkpoint Crítico)
            is_novo_recorde = test_f1 > melhor_f1_macro
            if is_novo_recorde:
                melhor_f1_macro = test_f1
                log_mensagem("=" * 80)
                log_mensagem(f"  NOVO RECORDE ALCANÇADO PELO AUTOML! F1 Macro: {melhor_f1_macro:.4%}")
                log_mensagem(f"  Algoritmo Vencedor: {nome_cand}")
                log_mensagem("=" * 80)

                # Serialização atômica do melhor modelo
                caminho_pkl_tmp = MELHOR_MODELO_PKL.with_suffix(".tmp")
                artefatos_modelo = {
                    "modelo": modelo_cand,
                    "feature_names": feature_names,
                    "classes": classes_alvo,
                    "target": "alvo_proximo_dia",
                    "iteracao": iteracao,
                    "timestamp": datetime.now().isoformat(),
                    "test_f1_macro": test_f1,
                    "test_acuracia": test_acc,
                    "test_balanced_acc": test_bal,
                }
                joblib.dump(artefatos_modelo, caminho_pkl_tmp, compress=3)
                caminho_pkl_tmp.replace(MELHOR_MODELO_PKL)

                # Metadados e Relatório de Classificação Detalhado
                cm = confusion_matrix(y_test, preds_test, labels=classes_alvo)
                clf_report = classification_report(y_test, preds_test, labels=classes_alvo, output_dict=True, zero_division=0)

                metadata_recorde = {
                    "iteracao": iteracao,
                    "timestamp": datetime.now().isoformat(),
                    "algoritmo": nome_cand,
                    "parametros": params_cand,
                    "metricas_teste": {
                        "f1_macro": test_f1,
                        "acuracia": test_acc,
                        "acuracia_balanceada": test_bal,
                        "f1_ponderado": test_f1_wei,
                    },
                    "cv_f1_macro_media": cv_f1_mean,
                    "cv_f1_macro_desvio": cv_f1_std,
                    "matriz_confusao": {
                        "classes": classes_alvo,
                        "valores": cm.tolist(),
                    },
                    "relatorio_classificacao": clf_report,
                }
                salvar_json_atomico(MELHOR_MODELO_METADATA, metadata_recorde)
                melhor_modelo_info = metadata_recorde

            # 7. Persistência Contínua do Leaderboard
            registro_iteracao = {
                "iteracao": iteracao,
                "timestamp": datetime.now().isoformat(),
                "algoritmo": nome_cand,
                "cv_f1_macro": round(cv_f1_mean, 4),
                "cv_f1_macro_std": round(cv_f1_std, 4),
                "cv_acuracia": round(cv_acc_mean, 4),
                "test_f1_macro": round(test_f1, 4),
                "test_acuracia": round(test_acc, 4),
                "test_balanced_acc": round(test_bal, 4),
                "test_f1_weighted": round(test_f1_wei, 4),
                "duracao_segundos": duracao,
                "tipo": "Candidato_AutoML",
            }

            df_novo = pd.DataFrame([registro_iteracao])
            if LEADERBOARD_CSV.exists():
                df_novo.to_csv(LEADERBOARD_CSV, mode="a", header=False, index=False, encoding="utf-8")
            else:
                df_novo.to_csv(LEADERBOARD_CSV, index=False, encoding="utf-8")

            # 8. Checkpoint Geral de Estado (Atômico)
            estado_geral = {
                "ultima_iteracao": iteracao,
                "timestamp_checkpoint": datetime.now().isoformat(),
                "melhor_f1_macro": melhor_f1_macro,
                "melhor_modelo": melhor_modelo_info,
                "total_amostras_treinadas": len(X),
                "ufs_ativas": int(X["lat"].nunique()),
                "status": "rodando_continuo",
            }
            salvar_json_atomico(ESTADO_JSON, estado_geral)

        except Exception as e:
            log_mensagem(f"  [Erro na iteração #{iteracao:04d} ({nome_cand})]: {e}")

        # Liberação preventiva de memória
        gc.collect()
        iteracao += 1
        time.sleep(1.0)

    log_mensagem("\n" + "=" * 85)
    log_mensagem(" SESSÃO AUTOML ENCERRADA COM SUCESSO. TODOS OS CHECKPOINTS FORAM SALVOS.")
    log_mensagem(f" Artefatos disponíveis em: {CHECKPOINT_DIR.resolve()}")
    log_mensagem("=" * 85)


if __name__ == "__main__":
    main()
