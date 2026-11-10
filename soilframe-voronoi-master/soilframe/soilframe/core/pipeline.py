from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from .dataset import Dataset

class Pipeline(ABC):
    """Contrato para pipelines parametrizadas e versionadas."""

    name: ClassVar[str]
    version: ClassVar[str] = "1.0.0"

    def __init__(self, fonte=None, estrategia=None, **parameters: Any) -> None:
        self.fonte = fonte
        self.estrategia = estrategia
        self.parametros = dict(parameters)
        self.estado_ajustado: dict[str, Any] = {}

    @classmethod
    @abstractmethod
    def parameters(cls) -> dict[str, Any]:
        ...

    @abstractmethod
    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        ...

    def ajustar(self, dados: Any = None, **parameters: Any) -> "Pipeline":
        """Ajusta a estratégia da pipeline e preserva seu estado."""
        dataset = self._as_dataset(dados)
        if self.estrategia and hasattr(self.estrategia, "limpar"):
            dataset = Dataset(self.estrategia.limpar(dataset.data), dataset.metadata)
        if self.estrategia and hasattr(self.estrategia, "ajustar"):
            self.estado_ajustado = dict(self.estrategia.ajustar(dataset.data) or {})
        self.parametros.update(parameters)
        self.estado_ajustado.setdefault("columns", list(dataset.data.columns) if hasattr(dataset.data, "columns") else None)
        return self

    def transformar(self, dados: Any = None) -> Dataset:
        dataset = self._as_dataset(dados)
        data = dataset.data
        if self.estrategia and hasattr(self.estrategia, "transformar"):
            data = self.estrategia.transformar(data)
        return Dataset(data, {**dataset.metadata, "pipeline": self.name, "version": self.version, "fitted": bool(self.estado_ajustado)})

    def _as_dataset(self, dados: Any = None) -> Dataset:
        if dados is None:
            if self.fonte is None:
                raise ValueError("Forneça dados ou uma FonteDados para a pipeline")
            dados = self.fonte.dataset() if hasattr(self.fonte, "dataset") else self.fonte
        if isinstance(dados, Dataset):
            return dados
        return Dataset(dados)

    def esquema_entrada(self) -> dict[str, Any]:
        return self.parameters()

    def esquema_saida(self) -> dict[str, Any]:
        return {"type": "Dataset"}

    def salvar(self, caminho: str | Path) -> Path:
        destination = Path(caminho)
        destination.mkdir(parents=True, exist_ok=True)
        import pickle
        with (destination / "pipeline.pkl").open("wb") as stream:
            pickle.dump(self, stream)
        return destination

    @classmethod
    def carregar(cls, caminho: str | Path) -> "Pipeline":
        import pickle
        with (Path(caminho) / "pipeline.pkl").open("rb") as stream:
            pipeline = pickle.load(stream)
        if not isinstance(pipeline, cls):
            raise TypeError(f"Artefato incompatível com {cls.__name__}")
        return pipeline

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return {"name": cls.name, "version": cls.version, "parameters": cls.parameters()}

    @classmethod
    def validate_parameters(cls, values: dict[str, Any]) -> dict[str, Any]:
        schema = cls.parameters()
        unknown = set(values) - set(schema)
        if unknown:
            raise ValueError(f"Parâmetros desconhecidos: {sorted(unknown)}")
        result = dict(values)
        for key, definition in schema.items():
            if definition.get("required") and key not in result:
                raise ValueError(f"Parâmetro obrigatório ausente: {key}")
            if key not in result and "default" in definition:
                result[key] = definition["default"]
        return result

    def _mapa(
        self,
        dataset: Dataset,
        valor: str,
        coluna_ano: str = "ano",
        latitude: str = "lat",
        longitude: str = "lon",
        output_dir: str | Path | None = None,
        criar_gif: bool = True,
        fps: int = 2,
        transform=None,
    ) -> Dataset:
        """Gera mapas anuais e, opcionalmente, um GIF com a evolução temporal."""
        if not isinstance(dataset, Dataset):
            raise TypeError("mapa() exige um Dataset")
        if not valor:
            raise ValueError("A coluna 'valor' é obrigatória para gerar o mapa")
        if fps <= 0:
            raise ValueError("fps deve ser maior que zero")

        data = transform(dataset.data) if transform else dataset.data
        if not hasattr(data, "columns"):
            raise TypeError("mapa() exige um Dataset tabular ou geográfico")
        if coluna_ano not in data.columns:
            raise KeyError(f"Coluna de ano não encontrada: {coluna_ano}")
        if valor not in data.columns:
            raise KeyError(f"Coluna de valor não encontrada: {valor}")

        import matplotlib.pyplot as plt
        import numpy as np
        from PIL import Image
        brasil_bbox = (-74.0, -34.0, -33.0, 6.0)

        frame_data = data.copy()
        frame_data[valor] = pd.to_numeric(frame_data[valor], errors="coerce")
        frame_data = frame_data.dropna(subset=[coluna_ano, valor])
        if frame_data.empty:
            raise ValueError("Não há registros válidos para gerar os mapas")

        is_geographic = "geometry" in frame_data.columns and data.__class__.__name__ == "GeoDataFrame"
        if is_geographic:
            from shapely.geometry import box

            if getattr(frame_data, "crs", None) is not None and str(frame_data.crs) != "EPSG:4326":
                frame_data = frame_data.to_crs("EPSG:4326")
            brasil_area = box(*brasil_bbox)
            frame_data = frame_data[frame_data.geometry.intersects(brasil_area)].copy()
            if frame_data.empty:
                raise ValueError("Não há geometrias brasileiras para gerar os mapas")
        elif not {latitude, longitude}.issubset(frame_data.columns):
            raise KeyError(
                "Os dados precisam conter geometry ou as colunas "
                f"'{latitude}' e '{longitude}'"
            )
        else:
            frame_data[latitude] = pd.to_numeric(frame_data[latitude], errors="coerce")
            frame_data[longitude] = pd.to_numeric(frame_data[longitude], errors="coerce")
            frame_data = frame_data.dropna(subset=[latitude, longitude])
            frame_data = frame_data[
                frame_data[longitude].between(brasil_bbox[0], brasil_bbox[2])
                & frame_data[latitude].between(brasil_bbox[1], brasil_bbox[3])
            ]
            if frame_data.empty:
                raise ValueError("Não há coordenadas brasileiras válidas para gerar os mapas")

        raw_years = list(frame_data[coluna_ano].unique())
        try:
            years = sorted(raw_years, key=lambda item: float(item))
        except (TypeError, ValueError):
            years = sorted(raw_years, key=str)
        values = frame_data[valor].to_numpy(dtype=float)
        vmin = float(np.nanmin(values))
        vmax = float(np.nanmax(values))
        if vmin == vmax:
            vmax = vmin + 1.0

        root = Path(output_dir) if output_dir is not None else Path("outputs")
        frames_dir = root / "frames"
        animations_dir = root / "animations"
        frames_dir.mkdir(parents=True, exist_ok=True)
        animations_dir.mkdir(parents=True, exist_ok=True)
        safe_pipeline = self.name.replace("/", "_").replace("\\", "_")
        safe_value = str(valor).replace("/", "_").replace("\\", "_")
        image_paths: list[str] = []

        for year in years:
            subset = frame_data[frame_data[coluna_ano] == year]
            fig, ax = plt.subplots(figsize=(10, 7))
            if is_geographic:
                subset.plot(
                    ax=ax,
                    column=valor,
                    cmap="inferno",
                    vmin=vmin,
                    vmax=vmax,
                    legend=True,
                    missing_kwds={"color": "lightgray"},
                )
                ax.set_axis_off()
            else:
                plot = ax.hexbin(
                    subset[longitude],
                    subset[latitude],
                    C=subset[valor],
                    gridsize=40,
                    reduce_C_function=np.mean,
                    mincnt=1,
                    cmap="inferno",
                    vmin=vmin,
                    vmax=vmax,
                )
                fig.colorbar(plot, ax=ax, label=valor)
                ax.set_xlabel(longitude)
                ax.set_ylabel(latitude)
                ax.set_aspect("auto")
            ax.set_xlim(brasil_bbox[0], brasil_bbox[2])
            ax.set_ylim(brasil_bbox[1], brasil_bbox[3])
            ax.set_title(f"{self.name} — {valor} — {year}")
            fig.tight_layout()
            image_path = frames_dir / f"{safe_pipeline}_{safe_value}_{year}.png"
            fig.savefig(image_path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            image_paths.append(str(image_path))

        gif_path: str | None = None
        if criar_gif:
            gif_file = animations_dir / f"{safe_pipeline}_{safe_value}.gif"
            images = [Image.open(path).convert("RGB") for path in image_paths]
            images[0].save(
                gif_file,
                save_all=True,
                append_images=images[1:],
                duration=max(1, int(1000 / fps)),
                loop=0,
            )
            for image in images:
                image.close()
            gif_path = str(gif_file)

        metadata = {
            **dataset.metadata,
            "operation": "mapa",
            "pipeline": self.name,
            "mapas": image_paths,
            "anos": list(years),
            "valor": valor,
            "coluna_ano": coluna_ano,
            "latitude": None if is_geographic else latitude,
            "longitude": None if is_geographic else longitude,
            "regiao_mapa": "Brasil",
            "registros_mapa": int(len(frame_data)),
            "gif": gif_path,
        }
        return Dataset(data, metadata)

    def mapa(
        self,
        dataset: Dataset,
        valor: str,
        coluna_ano: str = "ano",
        latitude: str = "lat",
        longitude: str = "lon",
        output_dir: str | Path | None = None,
        criar_gif: bool = True,
        fps: int = 2,
        transform=None,
    ) -> Dataset:
        return self._mapa(
            dataset,
            valor=valor,
            coluna_ano=coluna_ano,
            latitude=latitude,
            longitude=longitude,
            output_dir=output_dir,
            criar_gif=criar_gif,
            fps=fps,
            transform=transform,
        )

    def relacionar(self, pipeline: "Pipeline", on: str | list[str] | None = None, how: str = "left") -> "Pipeline":
        return ComposedPipeline(self, pipeline, operation="relacionar", on=on, how=how)

    def combinar(self, pipeline: "Pipeline", on: str | list[str] | None = None, how: str = "outer") -> "Pipeline":
        return ComposedPipeline(self, pipeline, operation="combinar", on=on, how=how)

    def dropar(self, columns: str | list[str]) -> "Pipeline":
        return PipelineView(self, drop_columns=[columns] if isinstance(columns, str) else columns)


class PipelineView(Pipeline):
    """Visão de pipeline com operações aplicadas ao resultado."""

    def __init__(self, base: Pipeline, drop_columns: list[str] | None = None) -> None:
        self.base = base
        self.drop_columns = drop_columns or []
        self.name = base.name
        self.version = base.version

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {}

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        result = self.base.rodar(parameters)
        if self.drop_columns:
            data = result.data.drop(columns=self.drop_columns, errors="ignore")
            return Dataset(data, {**result.metadata, "operation": "dropar", "dropped": self.drop_columns})
        return result


class ComposedPipeline(Pipeline):
    """Pipeline composta por duas pipelines escolhidas pelo usuário."""

    def __init__(self, left: Pipeline, right: Pipeline, operation: str, on=None, how: str = "outer") -> None:
        self.left = left
        self.right = right
        self.operation = operation
        self.on = on
        self.how = how
        self.name = f"{left.name}_{operation}_{right.name}"
        self.version = left.version

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {"left": {"type": "object", "required": True}, "right": {"type": "object", "required": True}}

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        parameters = parameters or {}
        if "left" not in parameters or "right" not in parameters:
            raise ValueError("Pipeline composta exige parâmetros 'left' e 'right'")
        left = self.left.rodar(parameters["left"])
        right = self.right.rodar(parameters["right"])
        if not hasattr(left.data, "merge") or not hasattr(right.data, "merge"):
            raise TypeError("Relacionamento entre pipelines exige dados tabulares")
        if self.on is None:
            data = left.data.join(right.data, lsuffix="_left", rsuffix="_right", how=self.how)
        else:
            data = left.data.merge(right.data, on=self.on, how=self.how)
        return Dataset(data, {"pipeline": self.name, "operation": self.operation, "left": left.metadata, "right": right.metadata})
