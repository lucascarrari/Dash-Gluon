"""Mapa analítico da camada Gold, inspirado nas ferramentas do projeto antigo."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pydeck as pdk
import streamlit as st

from .data_access import load_source
from .geography import (
    apply_geographic_lookup,
    classify_coordinates,
    load_brazil_state_features,
    load_coordinate_points,
    load_municipality_boundaries,
    load_municipality_names,
)
from .filters import apply_global_geography_filters
from .map_logic import (
    close_map_selection,
    clip_polygons_to_brazil,
    color_for_value,
    fit_map_view,
    format_number,
    make_geographic_cells,
    make_voronoi_cells,
    metric_label,
    metric_ramp,
    metric_unit,
    remember_map_selection,
    selected_map_object,
    summarize_selected_point,
)


STATE_REGION = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste", "DF": "Centro-Oeste", "GO": "Centro-Oeste",
    "MT": "Centro-Oeste", "MS": "Centro-Oeste", "ES": "Sudeste",
    "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste", "PR": "Sul",
    "RS": "Sul", "SC": "Sul",
}
MAP_ROW_LIMIT = 1_000_000
GRID_POINT_RADIUS_PX = 7
GRID_POINT_HALO_RADIUS_PX = 13
EXCLUDED_MAP_COLUMNS = {
    "latitude", "longitude", "api_latitude", "api_longitude", "altitude_m",
    "elevation_m", "elevation", "year", "month",
    "day", "day_of_year", "id", "location_id", "grid_id", "is_frost_risk",
    "is_heat_stress",
}
AGGREGATIONS = {
    "Média": "mean",
    "Mediana": "median",
    "Soma no período": "sum",
    "Máximo": "max",
    "Mínimo": "min",
}


@st.cache_data(ttl=5 * 60, max_entries=6, show_spinner=False)
def load_classified_points(source_path: str, table_name: str | None) -> pd.DataFrame:
    """Lê e classifica pontos únicos da fonte selecionada."""
    return classify_coordinates(
        load_coordinate_points(source_path, table_name),
        load_municipality_boundaries(),
        load_municipality_names(),
    )


@st.cache_resource(ttl=5 * 60, max_entries=4, show_spinner=False)
def load_map_source(source_path: str, table_name: str | None) -> pd.DataFrame:
    """Carrega todas as linhas Gold necessárias às agregações do mapa.

    A página geral preserva o limite de leitura para manter os gráficos leves.
    O mapa, por sua vez, precisa de toda a série Gold para agregar corretamente
    os valores dos 850 pontos no período escolhido.
    """
    source = Path(source_path).expanduser().resolve()
    if source.suffix.casefold() == ".parquet":
        import pyarrow as pa
        import pyarrow.parquet as parquet

        schema = parquet.read_schema(source)
        coordinate_and_dimension_names = {
            "data", "date", "datetime", "timestamp", "timestamp_utc", "latitude", "lat",
            "longitude", "lon", "lng", "grid_id", "location_id", "state",
            "uf", "macro_region", "municipio", "municipality",
        }
        selected_columns = [
            field.name
            for field in schema
            if field.name.casefold() in coordinate_and_dimension_names
            or pa.types.is_integer(field.type)
            or pa.types.is_floating(field.type)
        ]
        return pd.read_parquet(source, columns=selected_columns, engine="pyarrow")
    return load_source(str(source), table_name, row_limit=MAP_ROW_LIMIT)


def _prepare_map_frame(
    dataframe: pd.DataFrame,
    classified_points: pd.DataFrame,
) -> pd.DataFrame:
    """Normaliza datas, rótulos e chaves espaciais em uma cópia do Gold."""
    frame = apply_geographic_lookup(dataframe, classified_points)
    date_column = next(
        (
            column
            for column in ("data", "date", "datetime", "timestamp", "timestamp_utc")
            if column in frame
        ),
        None,
    )
    if date_column is None:
        raise ValueError("A camada Gold precisa conter uma coluna de data para o mapa.")
    if date_column != "data":
        frame = frame.rename(columns={date_column: "data"})
    frame["data"] = pd.to_datetime(frame["data"], errors="coerce", utc=True).dt.tz_convert(None)
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    frame = frame.dropna(subset=["data", "latitude", "longitude"])
    frame["state"] = frame.get("state", pd.Series("", index=frame.index)).fillna("").astype(str)
    frame["municipio"] = frame.get(
        "municipio", pd.Series("", index=frame.index)
    ).fillna("").astype(str)
    frame["macro_region"] = frame["state"].map(STATE_REGION).fillna("")
    identifier = frame.get("grid_id", pd.Series("", index=frame.index)).fillna("").astype(str)
    location_id = frame.get("location_id", pd.Series("", index=frame.index)).fillna("").astype(str)
    coordinate_key = (
        frame["latitude"].round(5).astype("string")
        + ","
        + frame["longitude"].round(5).astype("string")
    )
    frame["_point_key"] = identifier.mask(identifier.eq(""), location_id)
    frame["_point_key"] = frame["_point_key"].mask(frame["_point_key"].eq(""), coordinate_key)
    frame["_point_label"] = (
        frame["municipio"].str.strip()
        + ", "
        + frame["state"].str.strip()
    ).str.strip(", ")
    frame["_point_label"] = frame["_point_label"].mask(
        frame["_point_label"].eq(""), "Município não identificado"
    )
    frame["_point_label"] = frame["_point_label"] + " · " + frame["_point_key"].astype(str)
    return frame


def _numeric_metrics(frame: pd.DataFrame) -> list[str]:
    """Lista variáveis de clima numéricas e remove metadados da seleção."""
    columns: list[str] = []
    for column in frame.columns:
        if column.casefold() in EXCLUDED_MAP_COLUMNS or column.startswith("_") or column == "data":
            continue
        numeric_values = pd.to_numeric(frame[column], errors="coerce")
        if numeric_values.notna().any():
            columns.append(column)
    return columns


def _render_map_filters(
    frame: pd.DataFrame,
    source_key: str,
) -> tuple[pd.DataFrame, Any, Any]:
    """Aplica o período local e os filtros geográficos globais ao mapa."""
    minimum_date = frame["data"].min().date()
    maximum_date = frame["data"].max().date()
    key_suffix = re.sub(r"\W+", "_", source_key, flags=re.UNICODE)[-24:]

    period = st.date_input(
        "Período analisado",
        value=(minimum_date, maximum_date),
        min_value=minimum_date,
        max_value=maximum_date,
        format="DD/MM/YYYY",
        key=f"gold_map_period_{key_suffix}",
    )
    if not isinstance(period, (tuple, list)) or len(period) != 2:
        start_date = end_date = period
    else:
        start_date, end_date = period
    filtered = frame.loc[frame["data"].dt.date.between(start_date, end_date)].copy()
    filtered = apply_global_geography_filters(filtered)
    return filtered, start_date, end_date


def render_coordinate_map(
    source_path: str,
    table_name: str | None = None,
    classified_points: pd.DataFrame | None = None,
) -> None:
    """Renderiza análise Gold com pontos, células, Voronoi e detalhes interativos.

    Args:
        source_path: Caminho do Parquet ou SQLite conectado ao dashboard.
        table_name: Tabela Gold opcional para uma fonte SQLite.
        classified_points: Classificação município/UF em cache, se já carregada.
    """
    st.subheader("Mapa e distribuição espacial · camada Gold")
    st.caption(
        "Mapa inspirado no projeto anterior: filtra período e território, "
        "agrega as observações por ponto e permite alternar entre marcadores, "
        "células geográficas e polígonos Voronoi. Região, UF, município e "
        "ponto usam a seleção compartilhada na barra lateral."
    )
    try:
        if classified_points is None or classified_points.empty:
            classified_points = load_classified_points(source_path, table_name)
        if classified_points.empty:
            raise RuntimeError("A classificação geográfica não retornou pontos.")
        with st.spinner("Carregando o histórico Gold completo para o mapa..."):
            raw_frame = load_map_source(source_path, table_name)
            frame = _prepare_map_frame(raw_frame, classified_points)
    except Exception as exc:
        st.error(f"Não foi possível preparar o mapa da camada Gold: {exc}")
        return

    frame = frame.loc[
        frame["municipio"].ne("") & frame["state"].ne("")
    ].copy()
    if frame.empty:
        st.warning("Não há registros Gold associados a municípios brasileiros.")
        return

    metrics = _numeric_metrics(frame)
    if not metrics:
        st.info("A camada Gold não contém métricas numéricas para colorir o mapa.")
        return

    control_columns = st.columns([1.6, 1, 1.25])
    default_metric = metrics.index("eto_mm") if "eto_mm" in metrics else 0
    with control_columns[0]:
        metric = st.selectbox(
            "Parâmetro climático",
            metrics,
            index=default_metric,
            format_func=metric_label,
            key="gold_map_metric",
        )
    aggregation_labels = list(AGGREGATIONS)
    default_aggregation = (
        "Soma no período"
        if any(token in metric.casefold() for token in ("precipitation", "eto_mm", "evapotranspiration", "balance"))
        else "Média"
    )
    with control_columns[1]:
        aggregation_label = st.selectbox(
            "Resumo no período",
            aggregation_labels,
            index=aggregation_labels.index(default_aggregation),
            key="gold_map_aggregation",
        )
    map_modes = ["Pontos do grid", "Células geográficas", "Voronoi · ponto mais próximo"]
    with control_columns[2]:
        map_mode = st.selectbox("Representação do mapa", map_modes, key="gold_map_mode")

    filtered, start_date, end_date = _render_map_filters(frame, source_path)
    if filtered.empty:
        st.info("Não há registros no período e nos filtros geográficos escolhidos.")
        return

    setting_columns = st.columns(3)
    if map_mode == "Células geográficas":
        with setting_columns[0]:
            cell_size = st.slider(
                "Lado da célula geográfica (km)",
                min_value=10,
                max_value=100,
                value=45,
                step=5,
                key="gold_map_cell_size",
            )
    filtered["_value"] = pd.to_numeric(filtered[metric], errors="coerce")
    valid_frame = filtered.dropna(subset=["_value", "latitude", "longitude"])
    if valid_frame.empty:
        st.info("A variável selecionada não possui valores no recorte atual.")
        return
    aggregation = AGGREGATIONS[aggregation_label]
    group_columns = [
        "_point_key", "_point_label", "latitude", "longitude", "state",
        "macro_region", "municipio",
    ]
    points = (
        valid_frame.groupby(group_columns, dropna=False, sort=False)["_value"]
        .agg(aggregation)
        .reset_index(name="valor")
    )
    points = points.drop_duplicates(subset=["_point_key", "latitude", "longitude"])
    points["point_key"] = points["_point_key"].astype(str)
    points["valor_formatado"] = points["valor"].map(format_number)
    points["latitude_formatada"] = points["latitude"].map(lambda value: format_number(value, 5))
    points["longitude_formatada"] = points["longitude"].map(lambda value: format_number(value, 5))
    points["_point_label_safe"] = points["_point_label"].map(lambda value: html.escape(str(value)))
    unit = metric_unit(metric)
    if aggregation == "sum" and unit.endswith("/dia"):
        unit = "mm no período"
    unit_suffix = f" {html.escape(unit)}" if unit else ""
    ramp = metric_ramp(metric)
    low = float(points["valor"].quantile(0.02))
    high = float(points["valor"].quantile(0.98))
    if high <= low:
        low, high = float(points["valor"].min()), float(points["valor"].max())
    center_latitude, center_longitude, zoom = fit_map_view(points)
    state_features: dict[str, Any]
    try:
        state_features = load_brazil_state_features()
    except Exception as exc:
        st.error(f"Não foi possível carregar a malha territorial brasileira do IBGE: {exc}")
        return

    selected_key = ""
    active_selection = st.session_state.get("_active_map_point") or {}
    point_widget_key = "gold_map_point_selection"
    if active_selection.get("widget_key") == point_widget_key:
        selected_key = str(active_selection.get("point_key") or "")
    points["color"] = points["valor"].map(
        lambda value: color_for_value(value, low, high, ramp, 150)
    )
    points["halo_color"] = points["valor"].map(
        lambda value: color_for_value(value, low, high, ramp, 48)
    )
    has_selected_point = bool(selected_key) and points["point_key"].eq(selected_key).any()
    if has_selected_point:
        points["color"] = points["color"].map(lambda color: color[:3] + [38])

    map_values = points
    map_layers: list[pdk.Layer] = []
    tooltip: dict[str, Any]
    if map_mode == "Pontos do grid":
        points["radius"] = GRID_POINT_RADIUS_PX
        points["halo_radius"] = GRID_POINT_HALO_RADIUS_PX
        map_layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                id="gold-point-halo",
                data=points,
                get_position="[longitude, latitude]",
                get_fill_color="halo_color",
                get_radius="halo_radius",
                radius_units="pixels",
                radius_min_pixels=GRID_POINT_HALO_RADIUS_PX,
                radius_max_pixels=GRID_POINT_HALO_RADIUS_PX,
                stroked=False,
                filled=True,
                pickable=False,
            )
        )
        map_layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                id="collection-points",
                data=points,
                get_position="[longitude, latitude]",
                get_fill_color="color",
                get_line_color=[255, 255, 255, 170],
                get_line_width=1,
                get_radius="radius",
                radius_units="pixels",
                radius_min_pixels=GRID_POINT_RADIUS_PX,
                radius_max_pixels=GRID_POINT_RADIUS_PX,
                line_width_min_pixels=1,
                stroked=True,
                filled=True,
                pickable=True,
                auto_highlight=True,
            )
        )
        if has_selected_point:
            selected_points = points.loc[points["point_key"].eq(selected_key)].copy()
            selected_points["color"] = selected_points["color"].map(
                lambda color: color[:3] + [255]
            )
            map_layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    id="selected-point",
                    data=selected_points,
                    get_position="[longitude, latitude]",
                    get_fill_color="color",
                    get_line_color=[255, 255, 255, 255],
                    get_line_width=2,
                    get_radius="radius",
                    radius_units="pixels",
                    radius_min_pixels=GRID_POINT_RADIUS_PX,
                    radius_max_pixels=GRID_POINT_RADIUS_PX,
                    line_width_min_pixels=2,
                    stroked=True,
                    filled=True,
                    pickable=False,
                )
            )
        tooltip = {
            "html": (
                "<b>{_point_label_safe}</b><br/>"
                "Variável: " + html.escape(metric_label(metric)) + "<br/>"
                f"Valor: {{valor_formatado}}{unit_suffix}<br/>"
                "Latitude: {latitude_formatada}° · Longitude: {longitude_formatada}°"
            ),
            "style": {"backgroundColor": "#26351f", "color": "white"},
        }
    elif map_mode == "Células geográficas":
        map_values, low, high = make_geographic_cells(
            points, cell_size, aggregation, ramp
        )
        try:
            map_values = clip_polygons_to_brazil(map_values, state_features)
        except Exception as exc:
            st.error(f"Não foi possível limitar as células ao Brasil: {exc}")
            return
        if map_values.empty:
            st.warning("Nenhuma célula ficou dentro do território brasileiro neste recorte.")
            return
        map_values["valor_formatado"] = map_values["valor"].map(format_number)
        map_layers.append(
            pdk.Layer(
                "PolygonLayer",
                id="gold-geographic-cells",
                data=map_values,
                get_polygon="polygon",
                get_fill_color="color",
                get_line_color=[255, 255, 255, 220],
                line_width_min_pixels=1,
                stroked=True,
                filled=True,
                pickable=True,
                auto_highlight=True,
            )
        )
        tooltip = {
            "html": (
                f"<b>Célula de {cell_size} km</b><br/>"
                "Variável: " + html.escape(metric_label(metric)) + "<br/>"
                f"Valor: {{valor_formatado}}{unit_suffix}<br/>Pontos agregados: {{pontos}}"
            ),
            "style": {"backgroundColor": "#26351f", "color": "white"},
        }
    else:
        try:
            map_values, low, high = make_voronoi_cells(points, ramp)
            map_values = clip_polygons_to_brazil(map_values, state_features)
        except Exception as exc:
            st.warning(f"Não foi possível gerar as células Voronoi: {exc}")
            return
        if map_values.empty:
            st.warning("As células Voronoi não cobrem pontos dentro do Brasil neste recorte.")
            return
        map_values["valor_formatado"] = map_values["valor"].map(format_number)
        map_values["latitude_formatada"] = map_values["latitude"].map(
            lambda value: format_number(value, 5)
        )
        map_values["longitude_formatada"] = map_values["longitude"].map(
            lambda value: format_number(value, 5)
        )
        map_values["_point_label_safe"] = map_values["_point_label"].map(
            lambda value: html.escape(str(value))
        )
        map_layers.append(
            pdk.Layer(
                "PolygonLayer",
                id="gold-voronoi-cells",
                data=map_values,
                get_polygon="polygon",
                get_fill_color="color",
                get_line_color=[255, 255, 255, 220],
                line_width_min_pixels=1,
                stroked=True,
                filled=True,
                pickable=True,
                auto_highlight=True,
            )
        )
        tooltip = {
            "html": (
                "<b>{_point_label_safe}</b><br/>"
                f"Valor do ponto: {{valor_formatado}}{unit_suffix}<br/>"
                "Latitude: {latitude_formatada}° · Longitude: {longitude_formatada}°"
            ),
            "style": {"backgroundColor": "#26351f", "color": "white"},
        }

    state_layer: list[pdk.Layer] = []
    _append_brazil_boundary(state_layer, state_features)
    deck_layers = [*state_layer, *map_layers]
    view_data = points if map_mode == "Pontos do grid" else map_values
    center_latitude, center_longitude, zoom = fit_map_view(view_data)
    deck = pdk.Deck(
        layers=deck_layers,
        initial_view_state=pdk.ViewState(
            latitude=center_latitude,
            longitude=center_longitude,
            zoom=zoom,
            min_zoom=2.5,
            max_zoom=13,
            pitch=0,
        ),
        map_style=None,
        tooltip=tooltip,
    )
    if map_mode == "Pontos do grid":
        map_event = st.pydeck_chart(
            deck,
            width="stretch",
            height=620,
            on_select="rerun",
            selection_mode="single-object",
            key="gold_map_point_selection",
        )
        if remember_map_selection(
            "gold_map_point_selection",
            selected_map_object(map_event, "collection-points"),
            points,
        ):
            st.rerun()
    else:
        st.pydeck_chart(deck, width="stretch", height=620)

    ramp_css = ", ".join(
        f"rgb({color[0]},{color[1]},{color[2]}) {index / (len(ramp) - 1) * 100:.0f}%"
        for index, color in enumerate(ramp)
    )
    unit_html = html.escape(unit)
    st.markdown(
        "<div class='map-legend'>"
        f"<span>P2 · {format_number(low, 3)} {unit_html}</span>"
        f"<div class='map-gradient' style='background:linear-gradient(90deg,{ramp_css})'></div>"
        f"<span>P98 · {format_number(high, 3)} {unit_html}</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{len(points):,} pontos com valores válidos · "
        f"{metric_label(metric)} · {aggregation_label.casefold()} · "
        + (
            f"marcadores semitranslúcidos padronizados em {GRID_POINT_RADIUS_PX} px · "
            if map_mode == "Pontos do grid"
            else ""
        )
        + "cores calibradas entre os percentis 2 e 98. "
        + "Arraste para mover o mapa, use +/− para zoom e passe o cursor para consultar os valores."
    )
    omitted_points = max(
        0,
        len(classified_points)
        - int(classified_points["identificacao_geografica"].sum()),
    )
    if omitted_points:
        st.caption(
            f"{omitted_points:,} coordenadas sem município correspondente foram "
            "omitidas para manter a visualização restrita ao território brasileiro."
        )

    if map_mode == "Pontos do grid":
        _render_selected_point(
            filtered,
            points,
            metrics,
            metric,
            start_date,
            end_date,
            point_widget_key,
        )
    with st.expander("Valores usados no mapa"):
        preferred_columns = [
            "_point_label", "municipio", "state", "macro_region", "latitude",
            "longitude", "valor", "pontos",
        ]
        display_columns = [
            column for column in preferred_columns if column in map_values.columns
        ]
        display_map = map_values[display_columns].copy()
        display_map = display_map.rename(
            columns={
                "_point_label": "Localidade e ponto",
                "_point_key": "ID do ponto",
                "municipio": "Município",
                "macro_region": "Região",
                "state": "UF",
                "latitude": "Latitude",
                "longitude": "Longitude",
                "valor": f"{metric_label(metric)} · {aggregation_label.casefold()}",
                "pontos": "Pontos agregados",
            }
        )
        for coordinate_column in ("Latitude", "Longitude"):
            if coordinate_column in display_map:
                display_map[coordinate_column] = display_map[coordinate_column].map(
                    lambda value: format_number(value, 5)
                )
        value_column = f"{metric_label(metric)} · {aggregation_label.casefold()}"
        if value_column in display_map:
            display_map[value_column] = display_map[value_column].map(format_number)
        st.dataframe(display_map, use_container_width=True, hide_index=True)


def _append_brazil_boundary(
    layers: list[pdk.Layer],
    state_features: dict[str, Any],
) -> None:
    """Adiciona a silhueta/UFs como pano de fundo do mapa Gold."""
    layers.append(
        pdk.Layer(
            "GeoJsonLayer",
            id="brazil-boundary",
            data=state_features,
            stroked=True,
            filled=False,
            get_line_color=[105, 125, 71, 230],
            get_line_width=1,
            line_width_min_pixels=1,
            pickable=False,
        )
    )


def _render_selected_point(
    filtered: pd.DataFrame,
    points: pd.DataFrame,
    metrics: list[str],
    metric: str,
    start_date: Any,
    end_date: Any,
    widget_key: str,
) -> None:
    """Mostra o resumo persistente da localidade selecionada no mapa."""
    active = st.session_state.get("_active_map_point") or {}
    selected_key = str(active.get("point_key") or "")
    if active.get("widget_key") != widget_key or not selected_key:
        return
    point_rows = filtered.loc[filtered["_point_key"].astype(str).eq(selected_key)]
    selected_map_rows = points.loc[points["point_key"].eq(selected_key)]
    if point_rows.empty or selected_map_rows.empty:
        return
    selected = selected_map_rows.iloc[0]
    state_label = str(selected["state"] or "UF não identificada")
    region_label = str(selected["macro_region"] or "Região não identificada")
    latitude_label = format_number(selected["latitude"], 5)
    longitude_label = format_number(selected["longitude"], 5)
    header_col, close_col = st.columns([1, 0.12], gap="small", vertical_alignment="top")
    with header_col:
        st.markdown(
            "<div class='point-window-head'>"
            "<div class='point-window-kicker'>Detalhes do ponto selecionado</div>"
            f"<div class='point-window-title'>{html.escape(str(selected['municipio']))}</div>"
            f"<div class='point-window-meta'>{html.escape(state_label)} · {html.escape(region_label)}</div>"
            f"<div class='point-window-meta'>Latitude: {html.escape(latitude_label)}° · "
            f"Longitude: {html.escape(longitude_label)}°</div>"
            f"<div class='point-window-meta'>Período: {start_date.strftime('%d/%m/%Y')} a "
            f"{end_date.strftime('%d/%m/%Y')}</div>"
            f"<div class='point-window-meta'>Parâmetro do mapa: {html.escape(metric_label(metric))}</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    with close_col:
        st.button(
            "×",
            key="close-gold-map-point-details",
            help="Fechar detalhes do ponto",
            on_click=close_map_selection,
            args=(widget_key, selected_key),
        )
    summaries = summarize_selected_point(point_rows, metrics)
    if summaries.empty:
        st.info("Não há outras variáveis com valores válidos para este ponto no período.")
    else:
        summary_rows = "".join(
            "<div class='point-metric-row'>"
            f"<div class='point-metric-name'>{html.escape(str(row['Variável']))}</div>"
            f"<div class='point-metric-value'>{html.escape(str(row['Resumo no período']))}</div>"
            "</div>"
            for _, row in summaries.iterrows()
        )
        st.markdown(
            f"<div class='point-metric-list'>{summary_rows}</div>",
            unsafe_allow_html=True,
        )
