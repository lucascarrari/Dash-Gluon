from __future__ import annotations

from typing import Any
import pandas as pd

from .core.dataset import Dataset
from .core.model import Model


class TabularBaselineModel(Model):
    """Modelo inicial determinístico, substituível pelo algoritmo do cliente."""

    target_default = ""

    def __init__(self) -> None:
        super().__init__()
        self.target = self.target_default
        self.value: Any = None
        self.training_metadata: dict[str, Any] = {}

    def treinar(self, pipeline: Any, parameters: dict[str, Any] | None = None) -> "TabularBaselineModel":
        values = parameters or {}
        self.pipeline_treinamento = pipeline
        data = pipeline if isinstance(pipeline, Dataset) else pipeline.rodar(values.get("pipeline_parameters", values))
        frame = data.data if isinstance(data, Dataset) else data
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("O modelo tabular exige um Dataset com pandas.DataFrame")
        self.target = values.get("target", self.target_default)
        if self.target and self.target in frame.columns:
            series = frame[self.target].dropna()
            self.value = series.mean() if pd.api.types.is_numeric_dtype(series) else (series.mode().iloc[0] if not series.empty else None)
        else:
            self.value = None
        self.training_metadata = {"rows": len(frame), "columns": list(frame.columns), "target": self.target}
        if self.tracker is not None:
            for key, value in self.training_metadata.items():
                self.tracker.log_param(f"treino_{key}", value)
        return self

    def prever(self, data: Dataset | Any) -> Dataset:
        frame = data.data.copy() if isinstance(data, Dataset) else data.copy()
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("A previsão exige um Dataset com pandas.DataFrame")
        frame[f"previsao_{self.target or 'valor'}"] = self.value
        metadata = data.metadata if isinstance(data, Dataset) else {}
        return Dataset(frame, {**metadata, "model": self.name, "model_version": self.version})
