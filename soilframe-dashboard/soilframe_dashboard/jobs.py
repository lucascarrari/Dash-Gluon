"""Execução em segundo plano e histórico local de treinos AutoGluon."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import traceback
from contextlib import contextmanager
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import pandas as pd
import numpy as np


def _utc_now() -> str:
    """Retorna timestamp UTC no formato ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    """Orquestra treinos sem bloquear a sessão do dashboard.

    Cada execução guarda estado, configuração, métricas e caminhos de artefatos
    em um SQLite separado do Data Lake.
    """

    def __init__(self, workspace: str | Path) -> None:
        """Inicializa o worker e o banco local de experimentos.

        Args:
            workspace: Diretório de saída pertencente ao dashboard.
        """
        self.workspace = Path(workspace).expanduser().resolve()
        self.runs_dir = self.workspace / "runs"
        self.models_dir = self.workspace / "models"
        self.experiments_dir = self.workspace / "experiments"
        self.database_path = self.workspace / "dashboard_runs.sqlite3"
        for directory in (
            self.runs_dir,
            self.models_dir,
            self.experiments_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="soilframe-training",
        )
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()
        self._initialize_database()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão ao banco de histórico do app."""
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        """Cria o esquema de execuções e marca jobs órfãos como interrompidos."""
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_seconds REAL,
                    options_json TEXT NOT NULL,
                    metrics_json TEXT,
                    leaderboard_path TEXT,
                    predictions_path TEXT,
                    model_path TEXT,
                    error TEXT
                )
                """
            )
            connection.execute(
                """
                UPDATE runs
                SET status = 'interrupted', finished_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (_utc_now(),),
            )

    def submit(self, dataframe: pd.DataFrame, options: dict[str, Any]) -> str:
        """Agenda treino e devolve o identificador da execução.

        Args:
            dataframe: Dados já carregados e filtrados no dashboard.
            options: Configuração validada do modelo.

        Returns:
            Identificador único do job.
        """
        return self._enqueue(dataframe, options)

    def submit_pipeline(self, options: dict[str, Any]) -> str:
        """Agenda a execução de um pipeline SoilFrame sem DataFrame pré-carregado.

        Args:
            options: Nome e parâmetros do pipeline.

        Returns:
            Identificador único da execução.
        """
        return self._enqueue(None, options)

    def _enqueue(
        self,
        dataframe: pd.DataFrame | None,
        options: dict[str, Any],
    ) -> str:
        """Cria um registro e envia job de modelo ou pipeline ao worker."""
        run_id = uuid4().hex[:12]
        created_at = _utc_now()
        serializable_options = dict(options)
        if dataframe is not None:
            row_hashes = pd.util.hash_pandas_object(
                dataframe,
                index=True,
                categorize=True,
            ).to_numpy()
            serializable_options["dataset_snapshot"] = {
                "source_path": options.get("source_path"),
                "source_table": options.get("source_table"),
                "source_label": options.get("source_label"),
                "rows": int(len(dataframe)),
                "columns": [str(column) for column in dataframe.columns],
                "fingerprint_sha256": hashlib.sha256(
                    row_hashes.tobytes()
                ).hexdigest(),
            }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, task_type, target, status, created_at, options_json
                ) VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (
                    run_id,
                    str(options["task_type"]),
                    str(options["target"]),
                    created_at,
                    json.dumps(serializable_options, ensure_ascii=False, default=str),
                ),
            )
        job_dataframe = dataframe.copy(deep=True) if dataframe is not None else None
        with self._lock:
            self._futures[run_id] = self._executor.submit(
                self._run,
                run_id,
                job_dataframe,
                serializable_options,
            )
        return run_id

    def _update(self, run_id: str, **values: Any) -> None:
        """Atualiza campos de status usando nomes de coluna internos."""
        if not values:
            return
        allowed_fields = {
            "status",
            "started_at",
            "finished_at",
            "duration_seconds",
            "metrics_json",
            "leaderboard_path",
            "predictions_path",
            "model_path",
            "error",
        }
        if not set(values).issubset(allowed_fields):
            raise ValueError("Campo inválido na atualização de execução.")
        assignments = ", ".join(f"{field} = ?" for field in values)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?",
                (*values.values(), run_id),
            )

    def _run(
        self,
        run_id: str,
        dataframe: pd.DataFrame | None,
        options: dict[str, Any],
    ) -> None:
        """Executa o tipo de modelo selecionado e salva os artefatos."""
        started_clock = time.perf_counter()
        run_directory = self.runs_dir / run_id
        model_directory = self.models_dir / run_id
        options["run_id"] = run_id
        run_directory.mkdir(parents=True, exist_ok=True)
        self._update(run_id, status="running", started_at=_utc_now())
        try:
            if options["task_type"] == "pipeline":
                metrics, report = self._run_pipeline(options)
                leaderboard = report
                predictions = None
            elif options["task_type"] == "tabular":
                if dataframe is None:
                    raise ValueError("O treinamento tabular requer um DataFrame.")
                metrics, leaderboard, predictions = self._run_tabular(
                    dataframe,
                    options,
                    model_directory,
                )
            else:
                if dataframe is None:
                    raise ValueError("TimeSeries requer um DataFrame histórico.")
                metrics, leaderboard, predictions = self._run_timeseries(
                    dataframe,
                    options,
                    model_directory,
                )

            leaderboard_path = (
                run_directory / "pipeline_report.csv"
                if options["task_type"] == "pipeline"
                else run_directory / "leaderboard.csv"
            )
            leaderboard.to_csv(leaderboard_path, index=False)
            predictions_path = None
            if predictions is not None:
                predictions_path = run_directory / "predictions.csv"
                predictions.to_csv(predictions_path, index=False)
            elapsed = round(time.perf_counter() - started_clock, 2)
            metrics["training_seconds"] = elapsed
            metrics["rows_used"] = (
                int(len(dataframe)) if dataframe is not None else None
            )
            self._update(
                run_id,
                status="completed",
                finished_at=_utc_now(),
                duration_seconds=elapsed,
                metrics_json=json.dumps(metrics, ensure_ascii=False, default=str),
                leaderboard_path=str(leaderboard_path),
                predictions_path=(
                    str(predictions_path) if predictions_path is not None else None
                ),
                model_path=str(model_directory),
            )
        except Exception as exc:
            elapsed = round(time.perf_counter() - started_clock, 2)
            details = "".join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()
            self._update(
                run_id,
                status="failed",
                finished_at=_utc_now(),
                duration_seconds=elapsed,
                error=details[:4000],
            )

    def _run_tabular(
        self,
        dataframe: pd.DataFrame,
        options: dict[str, Any],
        model_directory: Path,
    ) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
        """Treina adaptador Tabular do SoilFrame e salva diagnósticos.

        Args:
            dataframe: Dados filtrados pelo usuário.
            options: Alvo, tipo de tarefa e parâmetros de treino.
            model_directory: Destino dos artefatos nativos do modelo.

        Returns:
            Métricas, leaderboard e previsões do conjunto de teste.
        """
        from soilframe.core.tracking import AutoGluonTracker
        from soilframe.models.modelo_autogluon import ModeloAutoGluonTabular

        date_column = options.get("date_column")
        if date_column and date_column != "data":
            dataframe = dataframe.rename(columns={date_column: "data"})

        tracker = AutoGluonTracker(
            self.experiments_dir / options["run_id"],
            feature_importance_time_limit=30,
            feature_importance_subsample_size=500,
        )
        model = ModeloAutoGluonTabular(
            alvo=options["target"],
            tipo_problema=options["problem_type"],
            estrategia_validacao=options["validation_strategy"],
            limite_tempo=int(options["time_limit"]),
            preset=options["preset"],
            caminho_modelo=model_directory / "autogluon",
            random_state=int(options.get("random_state", 42)),
            tracker=tracker,
        )
        model.treinar(dataframe)
        model.salvar(model_directory)
        metrics = dict(model.metricas_teste)
        metrics["random_state"] = int(options.get("random_state", 42))
        leaderboard = model.tabela_leaderboard()
        predictions = model.predicoes_teste.copy()

        # Recover the deterministic held-out rows so the dashboard can save
        # class probabilities and score each AutoGluon candidate on identical
        # test observations. The adapter uses random_state=42 by default.
        split_frame = dataframe.copy()
        if date_column and date_column != "data":
            split_frame = split_frame.rename(columns={date_column: "data"})
        _, test_frame = model._separar_treino_teste(split_frame)
        test_features = test_frame.drop(columns=[options["target"]])
        predictor = model.estrategia.predictor
        candidate_models = (
            leaderboard["model"].dropna().astype(str).tolist()
            if "model" in leaderboard
            else []
        )
        if candidate_models:
            candidate_scores: list[dict[str, Any]] = []
            for candidate in candidate_models:
                candidate_predictions = predictor.predict(
                    test_features,
                    model=candidate,
                )
                if options["problem_type"] == "regression":
                    actual = pd.to_numeric(test_frame[options["target"]], errors="coerce")
                    predicted = pd.to_numeric(candidate_predictions, errors="coerce")
                    residuals = predicted.to_numpy() - actual.to_numpy()
                    denominator = float(((actual - actual.mean()) ** 2).sum())
                    candidate_scores.append(
                        {
                            "model": candidate,
                            "mae_test": float(np.abs(residuals).mean()),
                            "mse_test": float(np.square(residuals).mean()),
                            "rmse_test": float(np.sqrt(np.square(residuals).mean())),
                            "r2_test": float(1 - np.square(residuals).sum() / denominator)
                            if denominator
                            else None,
                        }
                    )
                else:
                    from sklearn.metrics import (
                        accuracy_score,
                        f1_score,
                        precision_score,
                        recall_score,
                    )

                    actual = test_frame[options["target"]].astype(str)
                    predicted = pd.Series(
                        np.asarray(candidate_predictions),
                        index=actual.index,
                    ).astype(str)
                    candidate_scores.append(
                        {
                            "model": candidate,
                            "accuracy_test": float(accuracy_score(actual, predicted)),
                            "precision_weighted_test": float(
                                precision_score(actual, predicted, average="weighted", zero_division=0)
                            ),
                            "recall_weighted_test": float(
                                recall_score(actual, predicted, average="weighted", zero_division=0)
                            ),
                            "f1_weighted_test": float(
                                f1_score(actual, predicted, average="weighted", zero_division=0)
                            ),
                        }
                    )
            candidate_frame = pd.DataFrame(candidate_scores)
            leaderboard = leaderboard.drop(
                columns=[column for column in candidate_frame if column != "model" and column in leaderboard],
                errors="ignore",
            ).merge(candidate_frame, on="model", how="left")

        if options["problem_type"] != "regression":
            probabilities = predictor.predict_proba(
                test_features,
                as_multiclass=True,
            )
            if isinstance(probabilities, pd.Series):
                probabilities = probabilities.to_frame()
            class_labels = [str(label) for label in probabilities.columns]
            for index, column in enumerate(probabilities.columns):
                predictions[f"probability_{index}"] = probabilities[column].to_numpy()
            metrics["probability_classes"] = class_labels
        return metrics, leaderboard, predictions

    def _run_pipeline(
        self,
        options: dict[str, Any],
    ) -> tuple[dict[str, Any], pd.DataFrame]:
        """Executa pipeline Lakehouse AquaCrop no diretório isolado do dashboard.

        Args:
            options: Parâmetros do pipeline, incluindo ano, UFs e período.

        Returns:
            Métricas resumidas e relatório tabular de linhas por UF.
        """
        from soilframe.pipelines.pipeline_lakehouse import PipelineAquaCropLakehouse

        pipeline = PipelineAquaCropLakehouse()
        pipeline_parameters = {
            key: value
            for key, value in options.items()
            if key not in {"task_type", "target", "run_id"}
        }
        pipeline_parameters["lakehouse_dir"] = str(
            self.workspace / "lakehouse"
        )
        dataset = pipeline.rodar(pipeline_parameters)
        result_dataframe = dataset.data
        if not isinstance(result_dataframe, pd.DataFrame):
            raise TypeError("O pipeline Lakehouse não retornou um DataFrame.")
        if "uf" in result_dataframe.columns:
            report = (
                result_dataframe.groupby("uf", dropna=False)
                .size()
                .rename("registros")
                .reset_index()
                .sort_values("uf")
            )
        else:
            report = pd.DataFrame(
                [{"resumo": "resultado agregado", "registros": len(result_dataframe)}]
            )
        metrics = {
            "rows_output": int(len(result_dataframe)),
            "columns_output": int(len(result_dataframe.columns)),
            "ufs_output": (
                int(result_dataframe["uf"].nunique())
                if "uf" in result_dataframe.columns
                else 0
            ),
            "lakehouse_path": str(self.workspace / "lakehouse"),
        }
        return metrics, report

    def _run_timeseries(
        self,
        dataframe: pd.DataFrame,
        options: dict[str, Any],
        model_directory: Path,
    ) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
        """Treina TimeSeriesPredictor e persiste horizonte e leaderboard."""
        from soilframe.core.strategy import AutoGluonStrategy

        strategy = AutoGluonStrategy(
            task_type="timeseries",
            target=options["target"],
            path=model_directory / "autogluon",
            prediction_length=int(options["prediction_length"]),
            item_id_column=options["item_id_column"],
            timestamp_column=options["timestamp_column"],
            freq=options["frequency"],
            time_limit=int(options["time_limit"]),
            presets=options["preset"],
        )
        strategy.fit(dataframe)
        forecast = strategy.predict(dataframe)
        leaderboard = strategy.leaderboard()
        metrics: dict[str, Any] = {}
        if not leaderboard.empty:
            first_row = leaderboard.iloc[0].to_dict()
            metrics = {
                key: value
                for key, value in first_row.items()
                if isinstance(value, (str, int, float, bool))
            }
        return metrics, leaderboard, forecast

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Carrega uma execução pelo identificador.

        Args:
            run_id: Identificador devolvido por :meth:`submit`.

        Returns:
            Dicionário da execução ou ``None`` se não existir.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Lista execuções recentes para a página de experimentos."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Normaliza campos JSON do banco em valores Python."""
        record = dict(row)
        record["options"] = json.loads(record.pop("options_json"))
        metrics_json = record.pop("metrics_json")
        record["metrics"] = json.loads(metrics_json) if metrics_json else {}
        return record
