from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..core.dataset import Dataset


def read_input(value: Any, parameters: dict[str, Any] | None = None) -> Dataset:
    """Lê a entrada fornecida pelo usuário sem conhecer sua fonte de origem."""
    if isinstance(value, Dataset):
        return value
    if isinstance(value, pd.DataFrame):
        return Dataset(value, {"source_type": "dataframe"})
    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(f"Entrada não encontrada: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        data = pd.read_csv(path)
    elif suffix == ".parquet":
        data = pd.read_parquet(path)
    elif suffix in {".json", ".geojson"}:
        data = pd.read_json(path)
    elif suffix in {".nc", ".netcdf"}:
        import xarray as xr
        data = xr.open_dataset(path)
    else:
        raise ValueError(f"Formato de entrada não suportado: {suffix}")
    return Dataset(data, {"source": str(path), "source_type": suffix.lstrip(".")})
