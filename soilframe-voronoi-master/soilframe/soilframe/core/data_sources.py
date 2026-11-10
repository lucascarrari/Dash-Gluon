from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd

from .dataset import Dataset


class FonteDados(ABC):
    """Contrato para uma fonte de dados extraível e validável."""

    nome: str

    def __init__(self, nome: str | None = None, schema: dict[str, Any] | None = None) -> None:
        self.nome = nome or self.__class__.__name__
        self.schema = schema or {}

    @abstractmethod
    def extrair(self) -> pd.DataFrame:
        ...

    def validar_schema(self, dados: pd.DataFrame | None = None) -> bool:
        frame = dados if dados is not None else self.extrair()
        missing = set(self.schema) - set(frame.columns)
        if missing:
            raise ValueError(f"Schema inválido para {self.nome}; colunas ausentes: {sorted(missing)}")
        return True

    def dataset(self) -> Dataset:
        dados = self.extrair()
        self.validar_schema(dados)
        return Dataset(dados, {"source": self.nome, "source_type": self.__class__.__name__})


class ArquivoFonte(FonteDados):
    """Fonte local para CSV, Parquet, JSON e GeoJSON."""

    def __init__(self, caminho: str | Path, nome: str | None = None, schema: dict[str, Any] | None = None) -> None:
        super().__init__(nome, schema)
        self.caminho = Path(caminho)

    def extrair(self) -> pd.DataFrame:
        if not self.caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {self.caminho}")
        suffix = self.caminho.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(self.caminho)
        if suffix == ".parquet":
            return pd.read_parquet(self.caminho)
        if suffix in {".json", ".geojson"}:
            return pd.read_json(self.caminho)
        raise ValueError(f"Formato de fonte não suportado: {suffix}")


class INMET(ArquivoFonte):
    def __init__(self, caminho: str | Path, **kwargs: Any) -> None:
        super().__init__(caminho, nome="INMET", **kwargs)


class ERA5(ArquivoFonte):
    def __init__(self, caminho: str | Path, **kwargs: Any) -> None:
        super().__init__(caminho, nome="ERA5", **kwargs)


class Xavier(ArquivoFonte):
    def __init__(self, caminho: str | Path, **kwargs: Any) -> None:
        super().__init__(caminho, nome="Xavier", **kwargs)


class S3Curado(ArquivoFonte):
    """Fonte S3; aceita URI quando o ambiente possui fsspec/s3fs configurado."""

    def __init__(self, caminho: str, **kwargs: Any) -> None:
        super().__init__(caminho, nome="S3 curado", **kwargs)

    def extrair(self) -> pd.DataFrame:
        if str(self.caminho).startswith("s3://"):
            try:
                return pd.read_parquet(self.caminho)
            except ImportError as exc:
                raise ImportError("Instale soilframe[s3] para ler fontes S3") from exc
        return super().extrair()
