"""Identificação geográfica de pontos para exibição no dashboard.

Os nomes municipais e as UFs são enriquecimentos temporários calculados a
partir das coordenadas; nenhuma coluna é gravada de volta no Data Lake.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from .data_access import csv_separator, csv_source_files


IBGE_BASE_URL = "https://servicodados.ibge.gov.br/api"
IBGE_UF_PREFIXES = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA",
    "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE",
    "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE",
    "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT",
    "52": "GO", "53": "DF",
}
LATITUDE_ALIASES = ("latitude", "lat", "lat_y", "y")
LONGITUDE_ALIASES = ("longitude", "lon", "lng", "long", "lon_x", "x")
POINT_ID_ALIASES = ("grid_id", "location_id", "cell_id", "id_celula")
MUNICIPALITY_ALIASES = ("municipio", "município", "municipality", "city")
STATE_ALIASES = ("state", "uf", "estado", "sigla_uf")
LOCATION_NAME_ALIASES = ("location_name", "nome_localidade", "localidade", "location")


def _request_json(url: str) -> Any:
    """Obtém JSON de um endpoint público do IBGE com timeout limitado."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SoilFrameDashboard/0.2 (geographic display)",
            "Accept-Encoding": "gzip, identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read()
            content_encoding = response.headers.get("Content-Encoding", "").casefold()
            if content_encoding == "gzip" or response_body.startswith(b"\x1f\x8b"):
                response_body = gzip.decompress(response_body)
            charset = response.headers.get_content_charset() or "utf-8"
            response_text = response_body.decode(charset)
            return json.loads(response_text.lstrip("\ufeff"))
    except (
        urllib.error.URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        OSError,
        EOFError,
    ) as exc:
        raise RuntimeError(f"Não foi possível consultar os dados geográficos do IBGE: {exc}") from exc


@st.cache_data(ttl=30 * 24 * 60 * 60, show_spinner=False)
def load_municipality_boundaries() -> list[dict[str, Any]]:
    """Carrega polígonos municipais simplificados do serviço de malhas do IBGE.

    Returns:
        Polígonos GeoJSON indexáveis pelo código IBGE do município.

    Raises:
        RuntimeError: Se o serviço não fornecer uma malha municipal válida.
    """
    query = urllib.parse.urlencode(
        {
            "formato": "application/vnd.geo+json",
            "qualidade": "intermediaria",
            "intrarregiao": "municipio",
        }
    )
    payload = _request_json(f"{IBGE_BASE_URL}/v3/malhas/paises/BR?{query}")
    features = payload.get("features", []) if isinstance(payload, dict) else []
    boundaries: list[dict[str, Any]] = []
    for feature in features:
        properties = feature.get("properties") or {}
        code = str(properties.get("codarea") or properties.get("CD_MUN") or "")
        geometry = feature.get("geometry") or {}
        if len(code) == 7 and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            boundaries.append(
                {"code": code, "type": geometry["type"], "coordinates": geometry.get("coordinates", [])}
            )
    if not boundaries:
        raise RuntimeError("O IBGE não retornou polígonos municipais reconhecíveis.")
    return boundaries


@st.cache_data(ttl=30 * 24 * 60 * 60, show_spinner=False)
def load_brazil_state_features() -> dict[str, Any]:
    """Carrega as geometrias das UFs para desenhar apenas o território brasileiro.

    Returns:
        FeatureCollection GeoJSON com os limites estaduais do Brasil.

    Raises:
        RuntimeError: Se a API do IBGE não retornar limites estaduais.
    """
    query = urllib.parse.urlencode(
        {
            "formato": "application/vnd.geo+json",
            "qualidade": "minima",
            "intrarregiao": "UF",
        }
    )
    payload = _request_json(f"{IBGE_BASE_URL}/v3/malhas/paises/BR?{query}")
    features = payload.get("features", []) if isinstance(payload, dict) else []
    state_features = [
        feature
        for feature in features
        if str((feature.get("properties") or {}).get("codarea", ""))[:2]
        in IBGE_UF_PREFIXES
        and (feature.get("geometry") or {}).get("type") in {"Polygon", "MultiPolygon"}
    ]
    if not state_features:
        raise RuntimeError("O IBGE não retornou limites estaduais reconhecíveis.")
    return {"type": "FeatureCollection", "features": state_features}


@st.cache_data(ttl=30 * 24 * 60 * 60, show_spinner=False)
def load_municipality_names() -> dict[str, dict[str, str]]:
    """Carrega nomes oficiais de municípios e associa a UF pelo geocódigo.

    Returns:
        Mapa de geocódigo municipal para nome e sigla da UF.

    Raises:
        RuntimeError: Se a API de localidades não retornar municípios.
    """
    payload = _request_json(f"{IBGE_BASE_URL}/v1/localidades/municipios?orderBy=nome")
    result: dict[str, dict[str, str]] = {}
    if isinstance(payload, list):
        for municipality in payload:
            code = str(municipality.get("id", ""))
            name = str(municipality.get("nome", "")).strip()
            state = IBGE_UF_PREFIXES.get(code[:2], "")
            if len(code) == 7 and name and state:
                result[code] = {"municipio": name, "state": state}
    if not result:
        raise RuntimeError("A API de localidades do IBGE não retornou municípios reconhecíveis.")
    return result


def _point_in_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    """Testa se um ponto está dentro de um anel GeoJSON, em longitude/latitude."""
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        if (y1 > latitude) != (y2 > latitude):
            crossing_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing_x:
                inside = not inside
        previous = current
    return inside


def _point_in_polygon(
    longitude: float,
    latitude: float,
    rings: list[list[list[float]]],
) -> bool:
    """Testa inclusão no contorno exterior e exclusão de eventuais vazios."""
    return bool(rings) and _point_in_ring(longitude, latitude, rings[0]) and not any(
        _point_in_ring(longitude, latitude, hole) for hole in rings[1:]
    )


def classify_coordinates(
    locations: pd.DataFrame,
    boundaries: list[dict[str, Any]],
    municipality_names: dict[str, dict[str, str]],
) -> pd.DataFrame:
    """Associa coordenadas distintas a município/UF e devolve uma tabela de pontos.

    Args:
        locations: Tabela com latitude, longitude e opcionalmente um ID de ponto.
        boundaries: Malha GeoJSON municipal simplificada do IBGE.
        municipality_names: Nomes oficiais indexados pelo código IBGE.

    Returns:
        Cópia deduplicada dos pontos com município e UF para apresentação.
    """
    points = locations.copy()
    points["latitude"] = pd.to_numeric(points["latitude"], errors="coerce")
    points["longitude"] = pd.to_numeric(points["longitude"], errors="coerce")
    points = points.dropna(subset=["latitude", "longitude"]).drop_duplicates(
        subset=["latitude", "longitude"]
    )
    prepared_polygons: list[
        tuple[str, list[list[list[float]]], float, float, float, float]
    ] = []
    for boundary in boundaries:
        code = boundary["code"]
        if code not in municipality_names:
            continue
        polygons = (
            [boundary["coordinates"]]
            if boundary["type"] == "Polygon"
            else boundary["coordinates"]
        )
        for polygon in polygons:
            if not polygon or not polygon[0]:
                continue
            exterior = polygon[0]
            longitude_values = [coordinate[0] for coordinate in exterior]
            latitude_values = [coordinate[1] for coordinate in exterior]
            prepared_polygons.append(
                (
                    code,
                    polygon,
                    min(longitude_values),
                    max(longitude_values),
                    min(latitude_values),
                    max(latitude_values),
                )
            )
    municipalities_by_point: list[str] = []
    states_by_point: list[str] = []
    for point in points.itertuples(index=False):
        municipality_code = ""
        point_longitude = float(point.longitude)
        point_latitude = float(point.latitude)
        for code, polygon, min_lon, max_lon, min_lat, max_lat in prepared_polygons:
            in_bounds = (
                min_lon <= point_longitude <= max_lon
                and min_lat <= point_latitude <= max_lat
            )
            if in_bounds and _point_in_polygon(
                point_longitude, point_latitude, polygon
            ):
                municipality_code = code
                break
        municipality = municipality_names.get(municipality_code, {})
        municipalities_by_point.append(municipality.get("municipio", ""))
        states_by_point.append(municipality.get("state", ""))
    points["municipio"] = municipalities_by_point
    points["state"] = states_by_point
    points["identificacao_geografica"] = points["municipio"].ne("")
    return points.reset_index(drop=True)


@st.cache_data(ttl=300, max_entries=8, show_spinner=False)
def load_coordinate_points(source_path: str, table_name: str | None = None) -> pd.DataFrame:
    """Lê somente metadados de coordenadas e IDs da fonte Gold selecionada.

    Args:
        source_path: Caminho Parquet/CSV, coleção CSV ou banco SQLite.
        table_name: Tabela Gold opcional para fontes SQLite.

    Returns:
        Pontos únicos identificados na fonte.

    Raises:
        FileNotFoundError: Se o arquivo configurado não existir.
        ValueError: Se a fonte/tabela não tiver coordenadas reconhecíveis.
        RuntimeError: Se não for possível ler as colunas geográficas.
    """
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Fonte Gold não encontrada: {path}")
    try:
        csv_files = csv_source_files(path)
        if csv_files:
            point_frames: list[pd.DataFrame] = []
            selected_columns: dict[str, str | None] | None = None
            for csv_path in csv_files:
                separator = csv_separator(csv_path)
                available_columns = list(
                    pd.read_csv(csv_path, sep=separator, nrows=0).columns
                )
                file_columns = _point_columns(available_columns)
                if not file_columns["latitude"] or not file_columns["longitude"]:
                    continue
                columns_to_read = list(
                    dict.fromkeys(
                        column for column in file_columns.values() if column
                    )
                )
                frame = pd.read_csv(
                    csv_path,
                    sep=separator,
                    usecols=columns_to_read,
                )
                point_frames.append(_normalize_point_columns(frame, file_columns))
                selected_columns = file_columns
            if not point_frames or selected_columns is None:
                raise ValueError("Os CSVs não contêm colunas de latitude e longitude.")
            points = pd.concat(point_frames, ignore_index=True)
            return points.drop_duplicates(
                subset=["latitude", "longitude"]
            ).reset_index(drop=True)
        if path.suffix.casefold() == ".parquet":
            import pyarrow.parquet as parquet

            available_columns = parquet.read_schema(path).names
            selected_columns = _point_columns(available_columns)
            if not selected_columns["latitude"] or not selected_columns["longitude"]:
                raise ValueError("O Parquet não contém colunas de latitude e longitude.")
            columns_to_read = list(
                dict.fromkeys(column for column in selected_columns.values() if column)
            )
            frame = pd.read_parquet(path, columns=columns_to_read, engine="pyarrow")
            return _normalize_point_columns(frame, selected_columns)
        if path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
            if not table_name or not table_name.replace("_", "").isalnum():
                raise ValueError("Selecione uma tabela SQLite com nome válido.")
            connection_uri = f"file:{path.as_posix()}?mode=ro"
            with sqlite3.connect(connection_uri, uri=True, timeout=20) as connection:
                connection.execute("PRAGMA query_only = ON")
                columns = [
                    row[1]
                    for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                ]
                selected_columns = _point_columns(columns)
                if not selected_columns["latitude"] or not selected_columns["longitude"]:
                    raise ValueError("A tabela não contém colunas de latitude e longitude.")
                source_columns = list(
                    dict.fromkeys(column for column in selected_columns.values() if column)
                )
                quoted_columns = ", ".join(f'"{column}"' for column in source_columns)
                frame = pd.read_sql_query(
                    f'SELECT DISTINCT {quoted_columns} FROM "{table_name}"', connection
                )
            return _normalize_point_columns(frame, selected_columns)
        raise ValueError(
            "A identificação geográfica aceita Parquet, CSV, coleção CSV ou SQLite."
        )
    except (FileNotFoundError, ValueError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Não foi possível ler as coordenadas da fonte Gold: {exc}") from exc


def apply_geographic_lookup(
    frame: pd.DataFrame,
    classified_points: pd.DataFrame,
) -> pd.DataFrame:
    """Acrescenta município/UF a uma cópia dos registros sem alterar a fonte.

    Args:
        frame: Linhas Gold lidas para a página atual.
        classified_points: Pontos únicos enriquecidos com município/UF do IBGE.

    Returns:
        Cópia dos registros com filtros geográficos disponíveis em memória.
    """
    result = frame.copy()
    if result.empty or classified_points.empty:
        return result
    columns = {column.casefold(): column for column in result.columns}
    latitude_column = next((columns[name] for name in LATITUDE_ALIASES if name in columns), None)
    longitude_column = next((columns[name] for name in LONGITUDE_ALIASES if name in columns), None)
    if latitude_column is None or longitude_column is None:
        return result

    latitude_values = pd.to_numeric(result[latitude_column], errors="coerce")
    longitude_values = pd.to_numeric(result[longitude_column], errors="coerce")
    coordinate_index = pd.MultiIndex.from_arrays([latitude_values, longitude_values])
    lookup = {
        (float(row.latitude), float(row.longitude)): (row.municipio, row.state)
        for row in classified_points.itertuples(index=False)
    }
    municipality_values = coordinate_index.map(
        {key: value[0] or pd.NA for key, value in lookup.items()}
    )
    state_values = coordinate_index.map(
        {key: value[1] or pd.NA for key, value in lookup.items()}
    )
    municipality_column = next(
        (columns[name] for name in MUNICIPALITY_ALIASES if name in columns),
        "municipio",
    )
    state_column = next(
        (columns[name] for name in STATE_ALIASES if name in columns),
        "state",
    )
    if municipality_column not in result:
        result[municipality_column] = pd.NA
    if state_column not in result:
        result[state_column] = pd.NA
    current_municipality = result[municipality_column].replace("", pd.NA)
    current_state = result[state_column].replace("", pd.NA)
    result[municipality_column] = current_municipality.fillna(
        pd.Series(municipality_values, index=result.index)
    )
    result[state_column] = current_state.fillna(
        pd.Series(state_values, index=result.index)
    )
    return result


def _point_columns(columns: list[str]) -> dict[str, str | None]:
    """Resolve colunas de coordenadas, identificador, município e UF."""
    by_name = {column.casefold(): column for column in columns}
    aliases = {
        "latitude": LATITUDE_ALIASES,
        "longitude": LONGITUDE_ALIASES,
        "point_id": POINT_ID_ALIASES,
        "municipio_original": MUNICIPALITY_ALIASES + LOCATION_NAME_ALIASES,
        "state_original": STATE_ALIASES,
    }
    return {
        key: next((by_name[name] for name in names if name in by_name), None)
        for key, names in aliases.items()
    }


def _normalize_point_columns(
    frame: pd.DataFrame,
    selected_columns: dict[str, str | None],
) -> pd.DataFrame:
    """Padroniza nomes, coordenadas e rótulos existentes nos pontos."""
    rename = {
        source: target
        for target, source in (
            ("latitude", selected_columns["latitude"]),
            ("longitude", selected_columns["longitude"]),
            ("grid_id", selected_columns["point_id"]),
            ("municipio_origem", selected_columns["municipio_original"]),
            ("state_origem", selected_columns["state_original"]),
        )
        if source is not None and source != target
    }
    frame = frame.rename(columns=rename)
    for column in ("grid_id", "municipio_origem", "state_origem"):
        if column not in frame:
            frame[column] = ""
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    return frame.dropna(subset=["latitude", "longitude"]).drop_duplicates(
        subset=["latitude", "longitude"]
    ).reset_index(drop=True)


def add_geographic_labels(frame: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Preenche município e UF ausentes numa cópia do DataFrame para uso visual.

    Args:
        frame: Registros da camada Gold que serão exibidos.

    Returns:
        Cópia com município e estado preenchidos quando as coordenadas permitirem,
        mais uma nota de origem/limitação para a interface.
    """
    result = frame.copy()
    columns = {column.casefold(): column for column in result.columns}
    latitude_column = next((columns[name] for name in LATITUDE_ALIASES if name in columns), None)
    longitude_column = next((columns[name] for name in LONGITUDE_ALIASES if name in columns), None)
    if latitude_column is None or longitude_column is None:
        return result, None

    municipality_column = next((columns[name] for name in MUNICIPALITY_ALIASES if name in columns), None)
    state_column = next((columns[name] for name in STATE_ALIASES if name in columns), None)
    if municipality_column is None:
        municipality_column = "municipio"
        result[municipality_column] = pd.NA
    if state_column is None:
        state_column = "state"
        result[state_column] = pd.NA

    latitude = pd.to_numeric(result[latitude_column], errors="coerce")
    longitude = pd.to_numeric(result[longitude_column], errors="coerce")
    needs_labels = (
        (result[municipality_column].isna() | result[municipality_column].astype(str).str.strip().eq(""))
        & latitude.notna()
        & longitude.notna()
    )
    if not needs_labels.any():
        return result, None
    points = pd.DataFrame({"latitude": latitude, "longitude": longitude}).drop_duplicates()
    try:
        classified = classify_coordinates(
            points,
            load_municipality_boundaries(),
            load_municipality_names(),
        )
    except Exception as exc:
        return result, f"Identificação municipal do IBGE indisponível; mantidas as coordenadas originais. Detalhe: {exc}"
    lookup = {
        (row.latitude, row.longitude): (row.municipio, row.state)
        for row in classified.itertuples(index=False)
    }
    missing_index = result.index[needs_labels]
    labels = [
        lookup.get((float(longitude.loc[index]), float(latitude.loc[index])), ("", ""))
        for index in missing_index
    ]
    municipality_values = pd.Series(
        [municipality or pd.NA for municipality, _ in labels],
        index=missing_index,
        dtype="object",
    )
    state_values = pd.Series(
        [state or pd.NA for _, state in labels],
        index=missing_index,
        dtype="object",
    )
    current_municipality = result.loc[missing_index, municipality_column].replace("", pd.NA)
    current_state = result.loc[missing_index, state_column].replace("", pd.NA)
    result.loc[missing_index, municipality_column] = current_municipality.fillna(municipality_values)
    result.loc[missing_index, state_column] = current_state.fillna(state_values)
    matched = sum(bool(municipality) for municipality, _ in labels)
    unassigned = len(labels) - matched
    note = f"Município e UF estimados por coordenadas com malha do IBGE: {matched:,} registros classificados."
    if unassigned:
        note += f" {unassigned:,} pontos ficaram sem município correspondente."
    return result, note
