from __future__ import annotations

from pathlib import Path
from typing import Any
import pandas as pd

from .core.dataset import Dataset
from .core.pipeline import Pipeline
from .inputs import read_input


class FilePipeline(Pipeline):
    """Pipeline base para fontes tabulares parametrizadas."""

    input_name = "arquivo_dados"
    extra_parameters: dict[str, Any] = {}

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {cls.input_name: {"type": "file", "required": True, "formats": ["csv", "parquet", "netcdf"]}, **cls.extra_parameters}

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        parameters = parameters or {}
        values = self.validate_parameters(parameters)
        path = Path(values[self.input_name])
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")
        dataset = read_input(path)
        return dataset.with_metadata(pipeline=self.name, version=self.version)


class PipelinePrecipitacao(FilePipeline):
    name = "pipeline_precipitacao"


class PipelineSWI(FilePipeline):
    name = "pipeline_swi"
    input_name = "arquivo_swi"
    extra_parameters = {"variavel": {"type": "string", "required": False, "default": "SWI_010"}}


class PipelineLST(FilePipeline):
    name = "pipeline_lst"
    input_name = "arquivo_lst"
    extra_parameters = {"horario": {"type": "integer", "required": False, "default": 12}}


class PipelineSoloET0(FilePipeline):
    name = "pipeline_solo_et0"
    input_name = "dados_solo"

    @classmethod
    def parameters(cls) -> dict[str, Any]:
        return {
            "dados_solo": {"type": "file", "required": True, "formats": ["csv", "parquet", "gpkg"]},
            "dados_et0": {"type": "file", "required": True, "formats": ["csv", "parquet", "netcdf"]},
            "chave_relacionamento": {"type": "string", "required": False, "default": None},
        }

    def rodar(self, parameters: dict[str, Any] | None = None) -> Dataset:
        parameters = parameters or {}
        values = self.validate_parameters(parameters)
        solo = read_input(values["dados_solo"])
        et0 = read_input(values["dados_et0"])
        if hasattr(solo.data, "merge") and hasattr(et0.data, "columns") and values["chave_relacionamento"]:
            data = solo.data.merge(et0.data, on=values["chave_relacionamento"], how="outer")
        elif hasattr(solo.data, "reset_index") and hasattr(et0.data, "reset_index"):
            data = pd.concat([solo.data.reset_index(drop=True), et0.data.reset_index(drop=True)], axis=1)
        else:
            data = {"solo": solo.data, "et0": et0.data}
        return Dataset(data, {"pipeline": self.name, "version": self.version, "sources": [solo.metadata, et0.metadata]})


class PipelineMensal(FilePipeline):
    name = "pipeline_mensal"
    input_name = "dados_entrada"


class PipelineSazonal(FilePipeline):
    name = "pipeline_sazonal"
    input_name = "dados_entrada"


class PipelineDecenal(FilePipeline):
    name = "pipeline_decenal"
    input_name = "dados_entrada"
