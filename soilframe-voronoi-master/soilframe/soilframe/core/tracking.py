from __future__ import annotations

import json
import math
import shutil
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .metrics import Metricas


class RastreadorExperimento(ABC):
    """Define a interface de registro de experimentos do SoilFrame."""

    @abstractmethod
    def log_param(self, chave: str, valor: Any) -> None:
        """Registra um parâmetro de execução.

        Args:
            chave: Nome do parâmetro.
            valor: Valor serializável do parâmetro.
        """

    @abstractmethod
    def log_metrica(self, chave: str, valor: Any) -> None:
        """Registra uma métrica numérica do experimento.

        Args:
            chave: Nome da métrica.
            valor: Valor numérico calculado.
        """

    @abstractmethod
    def log_artefato(self, caminho: str | Path) -> None:
        """Registra um arquivo produzido pelo treinamento.

        Args:
            caminho: Caminho do artefato local.
        """

    @abstractmethod
    def registrar_modelo(self, modelo: Any, pipeline: Any, metricas: Metricas) -> None:
        """Registra modelo, pipeline e métricas de uma execução.

        Args:
            modelo: Modelo SoilFrame treinado.
            pipeline: Pipeline ou fonte usada no experimento.
            metricas: Métricas de avaliação do modelo.
        """


class MLflowTracker(RastreadorExperimento):
    """Rastreador opcional para enviar execuções ao MLflow."""

    def __init__(
        self,
        experimento: str = "soilframe",
        tracking_uri: str | None = None,
    ) -> None:
        """Configura o experimento MLflow e inicia ou reutiliza uma execução.

        Args:
            experimento: Nome do experimento MLflow.
            tracking_uri: URI do servidor ou armazenamento MLflow.

        Raises:
            ImportError: Se a dependência opcional MLflow não estiver instalada.
        """
        try:
            import mlflow
        except ImportError as exc:
            raise ImportError(
                "Instale soilframe[mlflow] para usar MLflowTracker."
            ) from exc
        self.mlflow = mlflow
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experimento)
        self.run = mlflow.active_run() or mlflow.start_run()

    def log_param(self, chave: str, valor: Any) -> None:
        """Envia um parâmetro ao MLflow."""
        self.mlflow.log_param(chave, valor)

    def log_metrica(self, chave: str, valor: Any) -> None:
        """Envia valores numéricos finitos ao MLflow."""
        if isinstance(valor, (int, float)) and math.isfinite(float(valor)):
            self.mlflow.log_metric(chave, valor)

    def log_artefato(self, caminho: str | Path) -> None:
        """Envia um arquivo local como artefato da execução MLflow."""
        self.mlflow.log_artifact(str(caminho))

    def registrar_modelo(self, modelo: Any, pipeline: Any, metricas: Metricas) -> None:
        """Registra métricas e tags de modelo e pipeline no MLflow."""
        for chave, valor in metricas.valores.items():
            self.log_metrica(chave, valor)
        model_name = getattr(modelo, "name", modelo.__class__.__name__)
        model_version = str(getattr(modelo, "version", "unknown"))
        pipeline_name = getattr(pipeline, "name", pipeline.__class__.__name__)
        pipeline_version = str(getattr(pipeline, "version", "unknown"))
        self.mlflow.set_tag("model", model_name)
        self.mlflow.set_tag("model_version", model_version)
        self.mlflow.set_tag("pipeline", pipeline_name)
        self.mlflow.set_tag("pipeline_version", pipeline_version)


class AutoGluonTracker(RastreadorExperimento):
    """Persiste métricas, diagnósticos AutoGluon e metadados em disco."""

    def __init__(
        self,
        artifact_dir: str | Path = "artifacts/experiments",
        *,
        feature_importance_time_limit: int = 60,
        feature_importance_subsample_size: int = 500,
        feature_importance_iterations: int = 1,
    ) -> None:
        """Configura onde salvar os artefatos dos experimentos.

        Args:
            artifact_dir: Pasta raiz para execuções de experimentos.
            feature_importance_time_limit: Limite em segundos para importância Tabular.
            feature_importance_subsample_size: Amostra máxima para importância Tabular.
            feature_importance_iterations: Número de permutações para importância.

        Raises:
            ValueError: Se limites ou tamanhos forem menores que um.
        """
        if feature_importance_time_limit < 1:
            raise ValueError("feature_importance_time_limit deve ser positivo.")
        if feature_importance_subsample_size < 1 or feature_importance_iterations < 1:
            raise ValueError("A amostra e o número de iterações devem ser positivos.")
        self.artifact_dir = Path(artifact_dir).expanduser().resolve()
        self.feature_importance_time_limit = feature_importance_time_limit
        self.feature_importance_subsample_size = feature_importance_subsample_size
        self.feature_importance_iterations = feature_importance_iterations
        self.run_dir: Path | None = None
        self.params: dict[str, Any] = {}
        self.metrics: dict[str, float] = {}

    @staticmethod
    def _json_value(value: Any) -> Any:
        """Converte valores comuns do Python para tipos compatíveis com JSON."""
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return value
        if isinstance(value, dict):
            return {
                str(key): AutoGluonTracker._json_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [AutoGluonTracker._json_value(item) for item in value]
        return str(value)

    def _ensure_run_dir(self) -> Path:
        """Cria uma pasta única para a execução corrente."""
        if self.run_dir is None:
            run_id = (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + uuid4().hex[:8]
            )
            self.run_dir = self.artifact_dir / run_id
            self.run_dir.mkdir(parents=True, exist_ok=False)
        return self.run_dir

    def log_param(self, chave: str, valor: Any) -> None:
        """Armazena um parâmetro para o arquivo de metadados."""
        self.params[chave] = self._json_value(valor)

    def log_metrica(self, chave: str, valor: Any) -> None:
        """Armazena uma métrica finita para o arquivo de metadados."""
        if isinstance(valor, (int, float)) and math.isfinite(float(valor)):
            self.metrics[chave] = float(valor)

    def log_artefato(self, caminho: str | Path) -> None:
        """Copia um arquivo para a pasta da execução atual.

        Args:
            caminho: Arquivo local produzido pelo pipeline ou pelo modelo.

        Raises:
            FileNotFoundError: Se o arquivo de origem não existir.
            OSError: Se a cópia do artefato falhar.
        """
        source_path = Path(caminho).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Artefato não encontrado: {source_path}")
        destination_path = self._ensure_run_dir() / source_path.name
        shutil.copy2(source_path, destination_path)

    def registrar_modelo(self, modelo: Any, pipeline: Any, metricas: Metricas) -> None:
        """Salva leaderboard, importância e metadados do modelo treinado.

        Falhas em diagnósticos são registradas no JSON e não descartam as métricas
        principais já calculadas pelo treinamento.

        Args:
            modelo: Modelo SoilFrame treinado.
            pipeline: Pipeline ou fonte usada no treinamento.
            metricas: Métricas de validação do modelo.

        Raises:
            OSError: Se a pasta ou o arquivo de metadados não puder ser gravado.
        """
        run_dir = self._ensure_run_dir()
        for metric_name, metric_value in metricas.valores.items():
            self.log_metrica(str(metric_name), metric_value)

        strategy = getattr(modelo, "estrategia", None)
        diagnostic_errors: dict[str, str] = {}
        if strategy is not None and getattr(strategy, "predictor", None) is not None:
            try:
                strategy.leaderboard().to_csv(run_dir / "leaderboard.csv", index=False)
            except Exception as exc:
                diagnostic_errors["leaderboard"] = f"{type(exc).__name__}: {exc}"
            try:
                importance = strategy.feature_importance(
                    time_limit=self.feature_importance_time_limit,
                    subsample_size=self.feature_importance_subsample_size,
                    num_iterations=self.feature_importance_iterations,
                )
                importance.to_csv(run_dir / "feature_importance.csv", index=True)
            except Exception as exc:
                diagnostic_errors["feature_importance"] = (
                    f"{type(exc).__name__}: {exc}"
                )

        metadata_method = getattr(modelo, "metadata", None)
        if callable(metadata_method):
            model_metadata = metadata_method()
        else:
            model_metadata = {
                "name": getattr(modelo, "name", modelo.__class__.__name__),
                "version": str(getattr(modelo, "version", "unknown")),
            }
        pipeline_metadata = {
            "name": getattr(pipeline, "name", pipeline.__class__.__name__),
            "version": str(getattr(pipeline, "version", "unknown")),
        }
        payload = {
            "run_id": run_dir.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": self._json_value(model_metadata),
            "pipeline": self._json_value(pipeline_metadata),
            "parameters": self.params,
            "metrics": self.metrics,
            "artifacts": sorted(path.name for path in run_dir.iterdir()),
            "diagnostic_errors": diagnostic_errors,
        }
        (run_dir / "experiment.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=self._json_value),
            encoding="utf-8",
        )
