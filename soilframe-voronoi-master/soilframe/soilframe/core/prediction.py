from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dataset import Dataset

@dataclass
class Prediction:
    """Execução rastreável de um modelo sobre uma entrada de uma pipeline."""

    pipeline: Any
    model: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def rodar(self, entrada: Dataset | Any) -> Dataset:
        if not self.validar(entrada):
            raise ValueError("Dados de entrada inválidos para a predição")
        dataset = entrada if isinstance(entrada, Dataset) else Dataset(entrada)
        result = self.model.prever(dataset)
        if not isinstance(result, Dataset):
            result = Dataset(result)
        result = result.with_metadata(
            **{
                **self.metadata,
                "pipeline": getattr(self.pipeline, "name", None),
                "model": getattr(self.model, "name", None),
                "pipeline_version": self.versao_pipeline(),
                "model_version": self.versao_modelo(),
                "prediction": True,
            }
        )
        tracker = getattr(self.model, "tracker", None)
        if tracker is not None:
            tracker.log_param("pipeline_version", self.versao_pipeline())
            tracker.log_param("model_version", self.versao_modelo())
        return result

    def validar(self, entrada: Dataset | Any) -> bool:
        if entrada is None:
            return False
        dataset = entrada if isinstance(entrada, Dataset) else Dataset(entrada)
        if dataset.data is None:
            return False
        fonte = getattr(self.pipeline, "fonte", None)
        schema = getattr(fonte, "schema", {}) or {}
        return not schema or (
            hasattr(dataset.data, "columns")
            and set(schema).issubset(set(dataset.data.columns))
        )

    def versao_modelo(self) -> str:
        return str(getattr(self.model, "version", "unknown"))

    def versao_pipeline(self) -> str:
        return str(getattr(self.pipeline, "version", "unknown"))

    def salvar(self, path: str | Path, entrada: Dataset | Any) -> Path:
        return self.rodar(entrada).save(path)
