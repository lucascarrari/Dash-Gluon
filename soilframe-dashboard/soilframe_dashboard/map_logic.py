"""Agregação, projeções, seleção e geometria reutilizáveis pelo mapa Gold."""

from __future__ import annotations

import math
import sys
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st


MAP_RAMPS = {
    "água": [[255, 246, 190], [191, 226, 195], [71, 177, 175], [32, 119, 169], [25, 63, 126]],
    "temperatura": [[38, 84, 160], [70, 150, 196], [184, 219, 222], [255, 246, 190], [242, 145, 77], [176, 37, 48]],
    "balanço": [[165, 40, 55], [237, 143, 86], [247, 222, 128], [165, 206, 115], [29, 124, 85]],
    "evapotranspiração": [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]],
}

MAP_METRIC_LABELS = {
    "tmax_c": ("Temperatura máxima", "°C"),
    "tmin_c": ("Temperatura mínima", "°C"),
    "tmean_c": ("Temperatura média", "°C"),
    "temperature_2m_max": ("Temperatura máxima do ar", "°C"),
    "temperature_2m_min": ("Temperatura mínima do ar", "°C"),
    "eto_mm": ("Evapotranspiração de referência (ETo)", "mm/dia"),
    "raw_eto_mm": ("ETo bruta", "mm/dia"),
    "precipitation_mm": ("Precipitação", "mm"),
    "precipitation_sum": ("Precipitação acumulada", "mm"),
    "soil_temp_shallow_c": ("Temperatura superficial do solo", "°C"),
    "gdd_c": ("Graus-dia de crescimento", "°C·dia"),
    "gda": ("Graus-dia acumulados", "°C·dia"),
    "thermal_amplitude_c": ("Amplitude térmica", "°C"),
    "elevation": ("Elevação", "m"),
    "altitude_m": ("Altitude", "m"),
    "temp_min_c": ("Temperatura mínima", "°C"),
    "temp_max_c": ("Temperatura máxima", "°C"),
    "temp_mean_c": ("Temperatura média", "°C"),
    "climatic_balance_mm": ("Balanço climático simplificado (P − ETo)", "mm"),
}


def format_number(value: Any, decimals: int = 2) -> str:
    """Formata valores em português brasileiro sem casas decimais redundantes."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    rendered = f"{number:,.{decimals}f}"
    if decimals:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered.replace(",", "\0").replace(".", ",").replace("\0", ".")


def metric_label(column: str) -> str:
    """Devolve nome legível e unidade da variável armazenada na camada Gold."""
    name, unit = MAP_METRIC_LABELS.get(
        column,
        (column.replace("_", " ").capitalize(), ""),
    )
    return f"{name} ({unit})" if unit else name


def metric_unit(column: str) -> str:
    """Devolve a unidade da variável Gold, quando conhecida."""
    return MAP_METRIC_LABELS.get(column, (column, ""))[1]


def metric_ramp(metric: str) -> list[list[int]]:
    """Seleciona uma paleta consistente com a família da variável climática."""
    name = metric.casefold()
    if "balance" in name or "ratio" in name:
        return MAP_RAMPS["balanço"]
    if any(token in name for token in ("temperature", "soil_temp", "tmax", "tmin", "temp_")):
        return MAP_RAMPS["temperatura"]
    if any(token in name for token in ("precipitation", "moisture", "humidity")):
        return MAP_RAMPS["água"]
    return MAP_RAMPS["evapotranspiração"]


def color_for_value(
    value: float,
    low: float,
    high: float,
    ramp: list[list[int]],
    alpha: int = 225,
) -> list[int]:
    """Interpola a cor entre os percentis de referência do mapa."""
    if pd.isna(value):
        return [160, 170, 176, alpha]
    ratio = 0.5 if high <= low else max(0.0, min(1.0, (float(value) - low) / (high - low)))
    scaled = ratio * (len(ramp) - 1)
    index = min(int(scaled), len(ramp) - 2)
    fraction = scaled - index
    return [
        round(ramp[index][channel] * (1 - fraction) + ramp[index + 1][channel] * fraction)
        for channel in range(3)
    ] + [alpha]


def fit_map_view(points: pd.DataFrame) -> tuple[float, float, float]:
    """Calcula centro e zoom para enquadrar o recorte de pontos no território."""
    latitudes = points["latitude"].astype(float).clip(-85, 85)
    longitudes = points["longitude"].astype(float)
    latitude_radians = np.radians(latitudes)
    mercator_y = np.arcsinh(np.tan(latitude_radians))
    center_y = (float(mercator_y.min()) + float(mercator_y.max())) / 2
    center_latitude = math.degrees(math.atan(math.sinh(center_y)))
    center_longitude = (float(longitudes.min()) + float(longitudes.max())) / 2
    longitude_span = max(float(longitudes.max() - longitudes.min()), 0.15)
    y_span = max(float(mercator_y.max() - mercator_y.min()), 0.15 * math.pi / 180)
    zoom_x = math.log2(1100 / (512 * longitude_span / 360))
    zoom_y = math.log2(500 / (512 * y_span / (2 * math.pi)))
    zoom = max(2.5, min(11.0, min(zoom_x, zoom_y) - 0.08))
    return center_latitude, center_longitude, zoom


def make_geographic_cells(
    points: pd.DataFrame,
    cell_km: int,
    aggregation: str,
    ramp: list[list[int]],
) -> tuple[pd.DataFrame, float, float]:
    """Agrupa pontos em células quadradas métricas na projeção Web Mercator."""
    earth_radius_m = 6_378_137.0
    cell_m = cell_km * 1000.0
    latitude = points["latitude"].astype(float).clip(-85, 85)
    longitude = points["longitude"].astype(float)
    work = points.copy()
    work["_gx"] = np.floor(earth_radius_m * np.radians(longitude) / cell_m).astype("int64")
    work["_gy"] = np.floor(
        earth_radius_m * np.arcsinh(np.tan(np.radians(latitude))) / cell_m
    ).astype("int64")
    cells = work.groupby(["_gx", "_gy"], as_index=False).agg(
        valor=("valor", aggregation),
        pontos=("_point_key", "nunique"),
    )
    cells["_west_x"] = cells["_gx"] * cell_m
    cells["_east_x"] = cells["_west_x"] + cell_m
    cells["_south_y"] = cells["_gy"] * cell_m
    cells["_north_y"] = cells["_south_y"] + cell_m

    def inverse_x(value: float) -> float:
        return math.degrees(value / earth_radius_m)

    def inverse_y(value: float) -> float:
        return math.degrees(math.atan(math.sinh(value / earth_radius_m)))

    cells["longitude"] = cells.apply(
        lambda row: inverse_x((row["_west_x"] + row["_east_x"]) / 2), axis=1
    )
    cells["latitude"] = cells.apply(
        lambda row: inverse_y((row["_south_y"] + row["_north_y"]) / 2), axis=1
    )
    cells["polygon"] = cells.apply(
        lambda row: [[
            [inverse_x(row["_west_x"]), inverse_y(row["_south_y"])],
            [inverse_x(row["_east_x"]), inverse_y(row["_south_y"])],
            [inverse_x(row["_east_x"]), inverse_y(row["_north_y"])],
            [inverse_x(row["_west_x"]), inverse_y(row["_north_y"])],
            [inverse_x(row["_west_x"]), inverse_y(row["_south_y"])],
        ]],
        axis=1,
    )
    low, high = _color_bounds(cells["valor"])
    cells["color"] = cells["valor"].map(
        lambda value: color_for_value(value, low, high, ramp)
    )
    return cells, low, high


def make_voronoi_cells(
    points: pd.DataFrame,
    ramp: list[list[int]],
) -> tuple[pd.DataFrame, float, float]:
    """Constrói células Voronoi do ponto mais próximo, recortadas ao grid."""
    try:
        from pyproj import Transformer
        from scipy.spatial import QhullError, Voronoi
        from shapely.geometry import MultiPoint, Polygon
    except ImportError as exc:
        raise RuntimeError(
            "As dependências de Voronoi não estão instaladas. "
            "Execute `python -m pip install -e .` na pasta soilframe-dashboard."
        ) from exc

    sites = points.groupby(["longitude", "latitude"], as_index=False, sort=False).agg(
        valor=("valor", "mean"),
        pontos=("_point_key", "nunique"),
        _point_key=("_point_key", "first"),
        _point_label=("_point_label", "first"),
        state=("state", "first"),
        macro_region=("macro_region", "first"),
    )
    if len(sites) < 4:
        raise ValueError("Voronoi requer pelo menos quatro coordenadas distintas.")

    to_projected = Transformer.from_crs("EPSG:4326", "EPSG:5880", always_xy=True)
    to_geographic = Transformer.from_crs("EPSG:5880", "EPSG:4326", always_xy=True)
    x, y = to_projected.transform(
        sites["longitude"].to_numpy(dtype=float),
        sites["latitude"].to_numpy(dtype=float),
    )
    coordinates = np.column_stack([x, y])
    if len(np.unique(coordinates, axis=0)) < 4:
        raise ValueError("Há menos de quatro coordenadas projetadas distintas.")
    try:
        diagram = Voronoi(coordinates)
    except QhullError as exc:
        raise ValueError("A distribuição dos pontos não permite gerar as células Voronoi.") from exc

    ridge_map: dict[int, list[tuple[int, int, int]]] = {}
    for (first, second), (vertex_a, vertex_b) in zip(
        diagram.ridge_points,
        diagram.ridge_vertices,
        strict=True,
    ):
        ridge_map.setdefault(first, []).append((second, vertex_a, vertex_b))
        ridge_map.setdefault(second, []).append((first, vertex_a, vertex_b))

    center = coordinates.mean(axis=0)
    radius = float(np.ptp(coordinates, axis=0).max()) * 2
    vertices = diagram.vertices.tolist()
    footprint = MultiPoint(coordinates).convex_hull
    if footprint.geom_type != "Polygon":
        raise ValueError("As coordenadas não formam uma área bidimensional.")

    polygons = []
    for point_index, region_index in enumerate(diagram.point_region):
        region = diagram.regions[region_index]
        if all(vertex >= 0 for vertex in region):
            finite_region = region
        else:
            finite_region = [vertex for vertex in region if vertex >= 0]
            for neighbor, vertex_a, vertex_b in ridge_map[point_index]:
                if vertex_a >= 0 and vertex_b >= 0:
                    continue
                finite_vertex = vertex_a if vertex_a >= 0 else vertex_b
                tangent = coordinates[neighbor] - coordinates[point_index]
                tangent /= np.linalg.norm(tangent)
                normal = np.array([-tangent[1], tangent[0]])
                midpoint = (coordinates[point_index] + coordinates[neighbor]) / 2
                direction = np.sign(np.dot(midpoint - center, normal)) * normal
                vertices.append((diagram.vertices[finite_vertex] + direction * radius).tolist())
                finite_region.append(len(vertices) - 1)
            region_coordinates = np.asarray([vertices[index] for index in finite_region])
            region_center = region_coordinates.mean(axis=0)
            angles = np.arctan2(
                region_coordinates[:, 1] - region_center[1],
                region_coordinates[:, 0] - region_center[0],
            )
            finite_region = [finite_region[index] for index in np.argsort(angles)]
        polygon = Polygon([vertices[index] for index in finite_region]).intersection(footprint)
        if polygon.is_empty or polygon.geom_type != "Polygon":
            raise ValueError("Uma célula Voronoi ficou vazia ou inválida.")
        polygons.append(polygon)

    def to_map_polygon(polygon: Any) -> list[list[list[float]]]:
        ring = np.asarray(polygon.exterior.coords)
        longitude, latitude = to_geographic.transform(ring[:, 0], ring[:, 1])
        return [[list(pair) for pair in zip(longitude, latitude, strict=True)]]

    sites["polygon"] = [to_map_polygon(polygon) for polygon in polygons]
    low, high = _color_bounds(sites["valor"])
    sites["color"] = sites["valor"].map(
        lambda value: color_for_value(value, low, high, ramp)
    )
    return sites, low, high


def clip_polygons_to_brazil(
    polygon_frame: pd.DataFrame,
    state_features: dict[str, Any],
) -> pd.DataFrame:
    """Recorta células/Voronoi pelos limites estaduais unidos do território brasileiro."""
    try:
        from shapely.geometry import Polygon, mapping, shape
        from shapely.ops import unary_union
    except ImportError as exc:
        raise RuntimeError(
            "O modo de células precisa do pacote Shapely, ausente no Python "
            f"que está executando o dashboard ({sys.executable}). Instale-o "
            f"nesse mesmo ambiente com: \"{sys.executable}\" -m pip "
            "install \"shapely>=2.0\" e reinicie o Streamlit."
        ) from exc

    brazil_geometry = unary_union(
        [shape(feature["geometry"]) for feature in state_features["features"]]
    )
    clipped_rows: list[dict[str, Any]] = []
    for row in polygon_frame.to_dict(orient="records"):
        rings = row.get("polygon") or []
        if not rings or not rings[0]:
            continue
        clipped = Polygon(rings[0], holes=rings[1:]).intersection(brazil_geometry)
        if clipped.is_empty:
            continue
        geometries = list(clipped.geoms) if clipped.geom_type == "MultiPolygon" else [clipped]
        for geometry in geometries:
            if geometry.geom_type != "Polygon" or geometry.area <= 0:
                continue
            mapped = mapping(geometry)
            clipped_row = row.copy()
            clipped_row["polygon"] = mapped["coordinates"]
            clipped_rows.append(clipped_row)
    return pd.DataFrame(clipped_rows)


def summarize_selected_point(
    point_rows: pd.DataFrame,
    metric_columns: list[str],
) -> pd.DataFrame:
    """Resume variáveis climáticas para o ponto dentro do período selecionado."""
    rows: list[dict[str, str]] = []
    for column in metric_columns:
        values = pd.to_numeric(point_rows[column], errors="coerce").dropna()
        if values.empty:
            continue
        name = column.casefold()
        if any(token in name for token in ("precipitation", "eto_mm", "evapotranspiration", "balance")):
            operation, summary_label = "sum", "Acumulado"
        elif any(token in name for token in ("tmax", "temp_max", "temperature_2m_max")):
            operation, summary_label = "max", "Máximo"
        elif any(token in name for token in ("tmin", "temp_min", "temperature_2m_min")):
            operation, summary_label = "min", "Mínimo"
        else:
            operation, summary_label = "mean", "Média"
        value = float(getattr(values, operation)())
        unit = metric_unit(column)
        if summary_label == "Acumulado" and unit.endswith("/dia"):
            unit = "mm no período"
        formatted = format_number(value)
        if unit:
            formatted = f"{formatted} {unit}"
        rows.append(
            {
                "Variável": metric_label(column),
                "Resumo no período": f"{formatted} · {summary_label.lower()} ({len(values):,} leituras)",
            }
        )
    return pd.DataFrame(rows)


def selected_map_object(widget_state: Any, layer_id: str) -> dict[str, Any] | None:
    """Extrai o objeto ou índice selecionado pelo clique no mapa Deck.gl."""
    if widget_state is None:
        return None
    selection = (
        widget_state.get("selection", {})
        if hasattr(widget_state, "get")
        else getattr(widget_state, "selection", {})
    )
    if not selection:
        selection = widget_state
    objects = selection.get("objects", {}) if hasattr(selection, "get") else {}
    selected = objects.get(layer_id, []) if hasattr(objects, "get") else []
    if selected:
        return dict(selected[0])
    indices = selection.get("indices", {}) if hasattr(selection, "get") else {}
    selected_indices = indices.get(layer_id, []) if hasattr(indices, "get") else []
    return {"_selected_index": selected_indices[0]} if selected_indices else None


def remember_map_selection(
    widget_key: str,
    selected_object: dict[str, Any] | None,
    points: pd.DataFrame,
) -> bool:
    """Persiste o ponto selecionado e informa quando a seleção mudou."""
    signatures = st.session_state.setdefault("_map_selection_signatures", {})
    previous = signatures.get(widget_key)
    selected = selected_object or {}
    point_key = str(selected.get("point_key") or selected.get("_point_key") or "")
    selected_index = selected.get("_selected_index")
    if not point_key and selected_index is not None:
        try:
            index = int(selected_index)
            if 0 <= index < len(points):
                point_key = str(points.iloc[index]["point_key"])
        except (TypeError, ValueError):
            pass
    signature = f"point:{point_key}" if point_key else ""
    dismissed = st.session_state.get("_dismissed_map_selection") or {}
    if signature and dismissed.get("widget_key") == widget_key and dismissed.get("point_key") == point_key:
        active = st.session_state.get("_active_map_point") or {}
        if active.get("widget_key") == widget_key:
            st.session_state["_active_map_point"] = None
        return False
    if dismissed.get("widget_key") == widget_key and (not signature or dismissed.get("point_key") != point_key):
        st.session_state.pop("_dismissed_map_selection", None)
    signatures[widget_key] = signature
    if signature:
        st.session_state["_active_map_point"] = {
            "widget_key": widget_key,
            "point_key": point_key,
            "index": selected_index,
        }
    elif previous:
        active = st.session_state.get("_active_map_point") or {}
        if active.get("widget_key") == widget_key:
            st.session_state["_active_map_point"] = None
    return signature != previous


def close_map_selection(widget_key: str, point_key: str) -> None:
    """Fecha o cartão de detalhes e suspende a reabertura pela seleção atual."""
    st.session_state["_dismissed_map_selection"] = {
        "widget_key": widget_key,
        "point_key": str(point_key),
    }
    st.session_state["_active_map_point"] = None


def _color_bounds(values: pd.Series) -> tuple[float, float]:
    """Calcula percentis robustos e trata séries constantes."""
    valid = pd.to_numeric(values, errors="coerce").dropna()
    low = float(valid.quantile(0.02))
    high = float(valid.quantile(0.98))
    if high <= low:
        low, high = float(valid.min()), float(valid.max())
    return low, high
