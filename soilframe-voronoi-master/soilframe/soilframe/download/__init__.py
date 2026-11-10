from __future__ import annotations

from .base import EstrategiaDownload, PlanoDownload
from .voronoi import (
    EstrategiaDownloadVoronoi,
    PIXELS_M,
    PERFIS_BANDAS,
    albers,
    albers_inv,
    bytes_km2,
    p_visivel,
    perfil_celula,
)
from .uniforme import EstrategiaDownloadUniforme
from .sentinel import FonteSentinelVoronoi
from .era5land import FonteERA5LandVoronoi, VARIAVEIS_AQUACROP

__all__ = [
    "EstrategiaDownload",
    "PlanoDownload",
    "EstrategiaDownloadVoronoi",
    "EstrategiaDownloadUniforme",
    "FonteSentinelVoronoi",
    "FonteERA5LandVoronoi",
    "VARIAVEIS_AQUACROP",
    "PIXELS_M",
    "PERFIS_BANDAS",
    "albers",
    "albers_inv",
    "bytes_km2",
    "p_visivel",
    "perfil_celula",
]
