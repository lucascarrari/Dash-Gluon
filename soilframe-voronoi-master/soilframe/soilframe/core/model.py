from __future__ import annotations
import json
import pickle
from pathlib import Path
from .dataset import Dataset
from typing import Any, ClassVar
from abc import ABC, abstractmethod

class Model(ABC):
    """Contrato independente para treino, previsão e persistência."""

    name: ClassVar[str]
    version: ClassVar[str] = "1.0.0"

    def __init__(self, **parameters: Any) -> None:
        self.parameters = dict(parameters)
        self.version = getattr(self.__class__, "version", "1.0.0")
        self.tracker: Any = None
        self.pipeline_treinamento: Any = None

    @abstractmethod
    def treinar(self, pipeline: Any, parameters: dict[str, Any] | None = None) -> "Model":
        ...

    @abstractmethod
    def prever(self, data: Dataset | Any) -> Dataset | Any:
        ...

    def avaliar(self, pipeline_teste: Any) -> "Metricas":
        from .metrics import Metricas
        dataset = pipeline_teste if isinstance(pipeline_teste, Dataset) else pipeline_teste.rodar()
        result = self.prever(dataset)
        actual_name = getattr(self, "target", "")
        values: dict[str, Any] = {"rows": len(dataset.data) if hasattr(dataset.data, "__len__") else 0}
        if actual_name and hasattr(dataset.data, "columns") and actual_name in dataset.data.columns and hasattr(result.data, "columns"):
            prediction_name = f"previsao_{actual_name}"
            if prediction_name in result.data.columns:
                actual = dataset.data[actual_name]
                predicted = result.data[prediction_name]
                if hasattr(actual, "equals") and actual.dtype.kind in "biufc":
                    values["mae"] = float((actual - predicted).abs().mean())
                else:
                    values["accuracy"] = float((actual == predicted).mean())
        return Metricas(values)

    def registrar(self, tracker: Any, pipeline: Any, metricas: Any = None) -> None:
        if pipeline is None:
            raise ValueError("A pipeline usada no treinamento é obrigatória para registrar o modelo")
        if metricas is None:
            from .metrics import Metricas
            metricas = Metricas()
        self.tracker = tracker
        self.pipeline_treinamento = pipeline
        tracker.registrar_modelo(self, pipeline, metricas)

    def metadados(self) -> dict[str, Any]:
        return self.metadata()

    def criar_predicao(self, pipeline: Any, metadata: dict[str, Any] | None = None):
        """Cria uma predição rastreável sem armazenar os dados de entrada."""
        from .prediction import Prediction
        return Prediction(pipeline, self, metadata or {})

    def combinar(self, model: "Model", parameters: dict[str, Any] | None = None) -> "Model":
        return CombinedModel(self, model, parameters or {})

    def dropar(self, modelo: "Model") -> tuple["Model", "Model"]:
        """Separa um modelo combinado nos dois modelos que o formaram."""
        if not isinstance(modelo, CombinedModel):
            raise TypeError("dropar() exige um modelo combinado")
        return modelo.left, modelo.right

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return {"name": cls.name, "version": cls.version}

    def salvar(self, path: str | Path, metadata: dict[str, Any] | None = None) -> Path:
        destination = Path(path)
        destination.mkdir(parents=True, exist_ok=True)
        with (destination / "model.pkl").open("wb") as stream:
            pickle.dump(self, stream)
        payload = {**self.metadata(), **(metadata or {})}
        (destination / "metadata.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return destination

    @classmethod
    def carregar(cls, path: str | Path) -> "Model":
        with (Path(path) / "model.pkl").open("rb") as stream:
            model = pickle.load(stream)
        if not isinstance(model, cls):
            raise TypeError(f"Artefato incompatível com {cls.__name__}")
        return model


class CombinedModel(Model):
    """Composição simples de dois modelos sobre o mesmo Dataset."""

    def __init__(self, left: Model, right: Model, parameters: dict[str, Any]) -> None:
        self.left, self.right, self.parameters_config = left, right, parameters
        self.name = f"{left.name}_combinar_{right.name}"
        self.version = left.version

    def treinar(self, pipeline: Any, parameters: dict[str, Any] | None = None) -> "CombinedModel":
        self.left.treinar(pipeline, parameters)
        self.right.treinar(pipeline, parameters)
        return self

    def metadata(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "operation": "combinar", "models": [self.left.name, self.right.name]}

    def prever(self, data: Dataset | Any) -> Dataset:
        left = self.left.prever(data)
        right = self.right.prever(data)
        if hasattr(left.data, "join") and hasattr(right.data, "columns"):
            columns = [column for column in right.data.columns if column not in left.data.columns]
            return Dataset(left.data.join(right.data[columns]), {"model": self.name, "operation": "combinar"})
        return Dataset({"left": left, "right": right}, {"model": self.name, "operation": "combinar"})
