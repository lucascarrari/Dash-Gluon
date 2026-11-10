from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, ClassVar
import numpy as np
import pandas as pd
import joblib

from ..core.dataset import Dataset
from ..core.model import Model
from ..core.metrics import Metricas


class ModeloAutoMLClassificador(Model):
    """Modelo de classificação com AutoML para dados agroclimáticos e AquaCrop."""

    name: ClassVar[str] = "modelo_automl_classificador"
    version: ClassVar[str] = "1.0.0"
    target_default: str = "classe_deficit_hidrico"

    def __init__(
        self,
        alvo: str | None = None,
        modo_predicao: str = "proximo_dia",  # 'proximo_dia' (previsão) ou 'mesmo_dia' (diagnóstico)
        cv_folds: int = 5,
        test_size: float = 0.2,
        random_state: int = 42,
        **parameters: Any,
    ) -> None:
        super().__init__(**parameters)
        self.alvo = alvo or self.target_default
        self.target = self.alvo
        self.modo_predicao = modo_predicao
        self.cv_folds = cv_folds
        self.test_size = test_size
        self.random_state = random_state

        self.melhor_modelo: Any = None
        self.melhor_algoritmo: str = ""
        self.feature_names: list[str] = []
        self.classes_: list[str] = []
        self.leaderboard_df: pd.DataFrame = pd.DataFrame()
        self.importancias_df: pd.DataFrame = pd.DataFrame()
        self.metricas_teste: dict[str, float] = {}

    def _preparar_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Engenharia de features agroclimáticas e enriquecimento do DataFrame."""
        dados = df.copy()

        # 1. Atributos Temporais
        if "data" in dados.columns:
            dt = pd.to_datetime(dados["data"])
            dados["mes"] = dt.dt.month
            dados["dia_ano"] = dt.dt.dayofyear
            # Estação astronômica no hemisfério sul
            dados["estacao_ano"] = np.select(
                [(dados["mes"].isin([12, 1, 2])), (dados["mes"].isin([3, 4, 5])), (dados["mes"].isin([6, 7, 8]))],
                [1, 2, 3],  # Verão, Outono, Inverno
                default=4,  # Primavera
            )

        # 2. Atributos Agroclimáticos Derivados
        if "tmax_c" in dados.columns and "tmin_c" in dados.columns:
            dados["amplitude_termica"] = dados["tmax_c"] - dados["tmin_c"]

        if "precipitacao_mm" in dados.columns and "et0_mm" in dados.columns:
            balanco = dados["precipitacao_mm"] - dados["et0_mm"]
            dados["balanco_hidrico_diario"] = balanco
            dados["razao_p_et0"] = (dados["precipitacao_mm"] / np.maximum(dados["et0_mm"], 0.1)).clip(upper=10.0)

            # Define classes agronômicas padrão do AquaCrop se o alvo não existir na base
            if self.alvo not in dados.columns:
                condicoes = [
                    balanco < -3.0,
                    (balanco >= -3.0) & (balanco < 0.0),
                    balanco >= 0.0,
                ]
                rotulos = ["Deficit_Severo", "Deficit_Moderado", "Adequado"]
                dados[self.alvo] = np.select(condicoes, rotulos, default="Adequado")

        # 3. Seleção de Features Numéricas
        candidatas = [
            "tmax_c", "tmin_c", "tmean_c", "precipitacao_mm", "et0_mm",
            "radiacao_solar_mj_m2", "vento_10m_ms", "amplitude_termica",
            "balanco_hidrico_diario", "razao_p_et0", "mes", "dia_ano",
            "estacao_ano", "lat", "lon", "area_km2",
        ]
        features_validas = [c for c in candidatas if c in dados.columns and c != self.alvo]
        mediana = dados[features_validas].median() if not dados.empty else pd.Series(0.0, index=features_validas)
        X = dados[features_validas].copy().fillna(mediana)

        return dados, X

    def _preparar_features_e_alvo(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        """Prepara X e y para treinamento ou validação."""
        dados, X = self._preparar_features(df)

        if self.modo_predicao == "proximo_dia" and "cell_id" in dados.columns:
            col_alvo_original = self.alvo
            dados["_alvo_proximo_dia"] = dados.groupby("cell_id")[col_alvo_original].shift(-1)
            valid_mask = dados["_alvo_proximo_dia"].notna()
            X_valid = X.loc[valid_mask]
            y_valid = dados.loc[valid_mask, "_alvo_proximo_dia"].astype(str)
            return X_valid, y_valid
        else:
            y = dados[self.alvo].astype(str)
            return X, y

    def treinar(
        self,
        pipeline: Any,
        parameters: dict[str, Any] | None = None,
    ) -> "ModeloAutoMLClassificador":
        """Executa a competição de AutoML entre múltiplos algoritmos de classificação."""
        from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
        from sklearn.tree import DecisionTreeClassifier
        from sklearn.linear_model import LogisticRegression
        from lightgbm import LGBMClassifier

        params = parameters or {}
        if "alvo" in params:
            self.alvo = params["alvo"]
            self.target = self.alvo
        if "modo_predicao" in params:
            self.modo_predicao = params["modo_predicao"]

        self.pipeline_treinamento = pipeline
        dados_input = pipeline if isinstance(pipeline, Dataset) else (
            pipeline.rodar(params.get("pipeline_parameters", params)) if hasattr(pipeline, "rodar") else pipeline
        )
        frame = dados_input.data if isinstance(dados_input, Dataset) else dados_input

        if not isinstance(frame, pd.DataFrame):
            raise TypeError("O modelo AutoML exige um Dataset contendo pandas.DataFrame")

        print(f"=== Iniciando AutoML Classifier SoilFrame (Alvo: '{self.alvo}', Modo: '{self.modo_predicao}') ===")
        X, y = self._preparar_features_e_alvo(frame)
        self.feature_names = list(X.columns)
        self.classes_ = sorted(list(y.unique()))

        print(f"Dataset de treino: {len(X):,} amostras | {len(self.feature_names)} features | {len(self.classes_)} classes ({self.classes_})")

        # Divisão Treino e Teste Holdout
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=self.test_size,
            random_state=self.random_state,
            stratify=y,
        )

        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        # Espaço de Algoritmos Candidatos do AutoML
        candidatos: dict[str, Any] = {
            "LightGBM": LGBMClassifier(
                n_estimators=100,
                learning_rate=0.08,
                random_state=self.random_state,
                verbose=-1,
                n_jobs=-1,
            ),
            "HistGradientBoosting": HistGradientBoostingClassifier(
                max_iter=100,
                learning_rate=0.1,
                random_state=self.random_state,
            ),
            "RandomForest": RandomForestClassifier(
                n_estimators=80,
                max_depth=12,
                random_state=self.random_state,
                n_jobs=-1,
            ),
            "DecisionTree": DecisionTreeClassifier(
                max_depth=10,
                random_state=self.random_state,
            ),
            "LogisticRegression": make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    max_iter=500,
                    random_state=self.random_state,
                ),
            ),
        }

        cv = StratifiedKFold(n_splits=self.cv_folds, shuffle=True, random_state=self.random_state)
        leaderboard_rows = []

        print(f"\n[AutoML] Avaliando {len(candidatos)} algoritmos via {self.cv_folds}-Fold Cross Validation...")

        melhor_score = -1.0
        melhor_nome = ""
        vencedor_instancia = None

        for nome, modelo_cand in candidatos.items():
            t_inicio = time.time()
            scoring = ["accuracy", "f1_macro"]
            scores = cross_validate(
                modelo_cand,
                X_train,
                y_train,
                cv=cv,
                scoring=scoring,
                n_jobs=-1 if nome != "LightGBM" else 1,
            )
            t_decorrido = time.time() - t_inicio

            acc_media = float(scores["test_accuracy"].mean())
            acc_std = float(scores["test_accuracy"].std())
            f1_media = float(scores["test_f1_macro"].mean())

            leaderboard_rows.append({
                "algoritmo": nome,
                "acuracia_cv": round(acc_media, 4),
                "acuracia_desvio": round(acc_std, 4),
                "f1_macro_cv": round(f1_media, 4),
                "tempo_seg": round(t_decorrido, 2),
            })

            print(f"  > {nome:<20} | Acurácia CV: {acc_media:.4f} (±{acc_std:.4f}) | F1 Macro: {f1_media:.4f} | Tempo: {t_decorrido:.2f}s")

            if acc_media > melhor_score:
                melhor_score = acc_media
                melhor_nome = nome
                vencedor_instancia = modelo_cand

        self.leaderboard_df = pd.DataFrame(leaderboard_rows).sort_values("acuracia_cv", ascending=False).reset_index(drop=True)
        self.melhor_algoritmo = melhor_nome
        self.melhor_modelo = vencedor_instancia

        print(f"\n[AutoML Vencedor] {self.melhor_algoritmo} selecionado com {melhor_score:.2%} de acurácia média.")

        # Ajusta o modelo vencedor com todo o conjunto de treino
        self.melhor_modelo.fit(X_train, y_train)

        # Avaliação no conjunto de teste Holdout
        y_pred = self.melhor_modelo.predict(X_test)
        acc_test = float(accuracy_score(y_test, y_pred))
        f1_test = float(f1_score(y_test, y_pred, average="macro"))
        f1_weight = float(f1_score(y_test, y_pred, average="weighted"))

        self.metricas_teste = {
            "accuracy": round(acc_test, 4),
            "f1_macro": round(f1_test, 4),
            "f1_weighted": round(f1_weight, 4),
            "linhas_teste": len(y_test),
        }
        print(f"[Holdout Teste] Acurácia: {acc_test:.4f} | F1-Score Macro: {f1_test:.4f}")

        # Extração de Importância das Features
        self._extrair_importancias(X_test, y_test)

        return self

    def _extrair_importancias(self, X_eval: pd.DataFrame, y_eval: pd.Series | None = None) -> None:
        """Calcula a importância de cada variável meteorológica e espacial."""
        importancias = None
        if hasattr(self.melhor_modelo, "feature_importances_"):
            importancias = self.melhor_modelo.feature_importances_
        elif hasattr(self.melhor_modelo, "coef_"):
            importancias = np.abs(self.melhor_modelo.coef_).mean(axis=0)
        elif y_eval is not None and not X_eval.empty:
            from sklearn.inspection import permutation_importance
            tamanho = min(1500, len(X_eval))
            rng = np.random.RandomState(self.random_state)
            indices = rng.choice(len(X_eval), size=tamanho, replace=False)
            X_sub = X_eval.iloc[indices]
            y_sub = y_eval.iloc[indices]
            perm = permutation_importance(self.melhor_modelo, X_sub, y_sub, n_repeats=3, random_state=self.random_state)
            importancias = np.maximum(perm.importances_mean, 0.0)

        if importancias is not None:
            soma = float(np.sum(importancias))
            if soma > 0:
                importancias = importancias / soma
            df_imp = pd.DataFrame({
                "feature": self.feature_names,
                "importancia": np.round(importancias, 4),
            }).sort_values("importancia", ascending=False).reset_index(drop=True)
            self.importancias_df = df_imp

    def prever(self, data: Dataset | Any) -> Dataset:
        """Gera predições e probabilidades calibradas para novas observações."""
        if self.melhor_modelo is None:
            raise RuntimeError("O modelo ainda não foi treinado. Execute treinar() primeiro.")

        frame = data.data.copy() if isinstance(data, Dataset) else data.copy()
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("A previsão exige um Dataset com pandas.DataFrame")

        dados_prep, X = self._preparar_features(frame)
        if self.alvo not in frame.columns and self.alvo in dados_prep.columns:
            frame[self.alvo] = dados_prep[self.alvo]

        # Garante alinhamento das colunas
        for col in self.feature_names:
            if col not in X.columns:
                X[col] = 0.0
        X = X[self.feature_names]

        # Predição de Classes
        preds = self.melhor_modelo.predict(X)
        col_pred = f"previsao_{self.alvo}"
        frame[col_pred] = preds

        # Predição de Probabilidades
        if hasattr(self.melhor_modelo, "predict_proba"):
            probs = self.melhor_modelo.predict_proba(X)
            classes = getattr(self.melhor_modelo, "classes_", self.classes_)
            for i, cls_name in enumerate(classes):
                frame[f"prob_{cls_name}"] = np.round(probs[:, i], 4)
            frame["confianca_previsao"] = np.round(np.max(probs, axis=1), 4)

        metadata = data.metadata if isinstance(data, Dataset) else {}
        return Dataset(
            frame,
            metadata={
                **metadata,
                "model": self.name,
                "version": self.version,
                "melhor_algoritmo": self.melhor_algoritmo,
                "alvo": self.alvo,
                "acuracia_teste": self.metricas_teste.get("accuracy"),
            },
        )

    def avaliar(self, pipeline_teste: Any) -> Metricas:
        """Calcula métricas padronizadas do SoilFrame sobre dados de teste."""
        dataset = pipeline_teste if isinstance(pipeline_teste, Dataset) else pipeline_teste.rodar()
        resultado = self.prever(dataset)
        df_res = resultado.data

        if self.alvo in df_res.columns:
            from sklearn.metrics import accuracy_score, f1_score
            if self.modo_predicao == "proximo_dia" and "cell_id" in df_res.columns:
                alvo_futuro = df_res.groupby("cell_id")[self.alvo].shift(-1)
                mask = alvo_futuro.notna()
                y_real = alvo_futuro.loc[mask].astype(str)
                y_pred = df_res.loc[mask, f"previsao_{self.alvo}"].astype(str)
            else:
                y_real = df_res[self.alvo].astype(str)
                y_pred = df_res[f"previsao_{self.alvo}"].astype(str)

            acc = float(accuracy_score(y_real, y_pred))
            f1_m = float(f1_score(y_real, y_pred, average="macro"))
            f1_w = float(f1_score(y_real, y_pred, average="weighted"))
        else:
            acc = self.metricas_teste.get("accuracy", 0.0)
            f1_m = self.metricas_teste.get("f1_macro", 0.0)
            f1_w = self.metricas_teste.get("f1_weighted", 0.0)

        valores = {
            "accuracy": round(acc, 4),
            "f1_macro": round(f1_m, 4),
            "f1_weighted": round(f1_w, 4),
            "rows": len(df_res),
            "melhor_algoritmo": self.melhor_algoritmo,
        }
        return Metricas(valores)

    def tabela_leaderboard(self) -> pd.DataFrame:
        """Retorna a tabela de ranking dos modelos avaliados pelo AutoML."""
        return self.leaderboard_df.copy()

    def importancia_features(self, top_n: int = 10) -> pd.DataFrame:
        """Retorna as features mais influentes na decisão do modelo."""
        return self.importancias_df.head(top_n).copy()

    def salvar(self, path: str | Path, metadata: dict[str, Any] | None = None) -> Path:
        """Persiste o modelo e artefatos de AutoML em disco."""
        destination = Path(path)
        destination.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, destination / "model.pkl")

        payload = {
            **self.metadata(),
            "melhor_algoritmo": self.melhor_algoritmo,
            "metricas_teste": self.metricas_teste,
            "features": self.feature_names,
            "classes": self.classes_,
            **(metadata or {}),
        }
        (destination / "metadata.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        if not self.leaderboard_df.empty:
            self.leaderboard_df.to_csv(destination / "leaderboard.csv", index=False)
        return destination

    @classmethod
    def carregar(cls, path: str | Path) -> "ModeloAutoMLClassificador":
        modelo = joblib.load(Path(path) / "model.pkl")
        if not isinstance(modelo, cls):
            raise TypeError(f"Artefato incompatível com {cls.__name__}")
        return modelo
