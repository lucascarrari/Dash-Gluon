from __future__ import annotations
import json
from typing import Any
from pathlib import Path
from .metrics import Metricas
from .prediction import Prediction

class RepositorioModelos:
    """Registro local de modelos com estágios de promoção."""

    def __init__(self, caminho: str | Path = "outputs/models") -> None:
        self.caminho = Path(caminho)
        self.caminho.mkdir(parents=True, exist_ok=True)

    def registrar(self, modelo: Any, pipeline: Any, metricas: Metricas) -> Path:
        if pipeline is None:
            raise ValueError("A pipeline usada no treinamento é obrigatória para registrar o modelo")
        destino = self.caminho / getattr(modelo, "name", modelo.__class__.__name__) / str(getattr(modelo, "version", "1.0.0"))
        model_name = getattr(modelo, "name", modelo.__class__.__name__)
        model_version = str(getattr(modelo, "version", "unknown"))
        pipeline_name = getattr(pipeline, "name", pipeline.__class__.__name__)
        pipeline_version = str(getattr(pipeline, "version", "unknown"))
        modelo.salvar(destino, {
            "model": model_name,
            "model_version": model_version,
            "pipeline": pipeline_name,
            "pipeline_version": pipeline_version,
            "metrics": metricas.para_dict(),
            "stage": "Staging",
        })
        return destino

    def promover(self, nome: str, versao: str, estagio: str) -> Path:
        destino = self.caminho / nome / versao / "metadata.json"
        if not destino.exists():
            raise FileNotFoundError(f"Modelo não encontrado: {nome}/{versao}")
        payload = json.loads(destino.read_text(encoding="utf-8"))
        payload["stage"] = estagio
        destino.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return destino.parent

    def obter(self, nome: str, estagio: str = "Production", pipeline: Any = None) -> Any:
        base = self.caminho / nome
        candidates = []
        for metadata in base.glob("*/metadata.json"):
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            if payload.get("stage", "Staging") == estagio:
                candidates.append((payload.get("version", metadata.parent.name), metadata.parent))
        if not candidates:
            raise LookupError(f"Nenhum modelo {nome!r} no estágio {estagio!r}")
        from .model import Model
        _, path = sorted(candidates)[-1]
        model = Model.carregar(path)
        if pipeline is not None:
            return Prediction(pipeline, model)
        return model
