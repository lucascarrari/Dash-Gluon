from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Dataset:
    """Dados produzidos por uma pipeline, acompanhados de metadados."""

    data: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_metadata(self, **values: Any) -> "Dataset":
        return Dataset(self.data, {**self.metadata, **values})

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(self.data, "to_parquet") and destination.suffix == ".parquet":
            self.data.to_parquet(destination, index=False)
        elif hasattr(self.data, "to_csv"):
            self.data.to_csv(destination, index=False)
        elif hasattr(self.data, "to_netcdf"):
            self.data.to_netcdf(destination)
        else:
            raise TypeError("Tipo de dados sem formato de saída suportado")
        return destination
