"""Resumo dos dados AquaCrop disponíveis na fonte Gold selecionada."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from soilframe_dashboard.data_access import detect_column, dataframe_schema
from soilframe_dashboard.metrics import variable_label
from soilframe_dashboard.filters import (
    apply_global_geography_filters,
    render_filters,
)
from soilframe_dashboard.ui import (
    load_configured_dataframe,
    page_header,
    render_geographic_filters,
)


page_header(
    "Dashboard",
    "Escolha uma base Gold no menu lateral para atualizar estes indicadores, "
    "gráficos e filtros.",
)
source_dataframe = load_configured_dataframe()
if source_dataframe is None:
    st.subheader("Comece conectando a camada Gold")
    st.markdown(
        "Escolha um produto Gold do novo Data Lake ou informe um caminho "
        "Parquet, CSV, pasta de CSVs ou banco SQLite. A fonte é lida sem alterações."
    )
    setup_columns = st.columns(3)
    setup_columns[0].markdown(
        "**Indicadores AquaCrop**\n\n"
        "Consulte precipitação, ET₀, balanço hídrico e as demais variáveis "
        "presentes na fonte."
    )
    setup_columns[1].markdown(
        "**Recortes por local e período**\n\n"
        "Filtre por UF, município, célula, cultura e datas, conforme as "
        "colunas disponíveis."
    )
    setup_columns[2].markdown(
        "**Modelos e previsões**\n\n"
        "Inicie treinamentos AutoGluon e acompanhe métricas e resultados "
        "nas páginas de operação."
    )
    st.stop()

render_geographic_filters()
source_dataframe = apply_global_geography_filters(source_dataframe)
selected_product = st.session_state.get(
    "soilframe_gold_dataset", "Produto Gold personalizado"
)
selected_path = Path(
    st.session_state.get("soilframe_source_path", "")
).expanduser()

st.caption(
    f"Base ativa: **{selected_product}** · "
    f"{len(source_dataframe):,} linhas × {len(source_dataframe.columns)} colunas · "
    f"{selected_path.name if selected_path.is_file() else 'coleção Gold'}"
)
filtered_dataframe = render_filters(source_dataframe, "overview")

date_column = detect_column(
    list(filtered_dataframe.columns),
    ("data", "date", "timestamp", "timestamp_utc", "datetime"),
)
location_column = detect_column(
    list(filtered_dataframe.columns),
    ("grid_id", "cell_id", "location_id", "municipio", "municipality"),
)
state_column = detect_column(
    list(filtered_dataframe.columns), ("state", "uf", "estado", "sigla_uf")
)
numeric_columns = filtered_dataframe.select_dtypes(include="number").columns.tolist()
non_climate_columns = {
    "latitude", "longitude", "api_latitude", "api_longitude", "altitude_m",
    "elevation", "elevation_m", "year", "month", "day", "day_of_year",
    "ingestion_timestamp",
}
numeric_columns = [
    column
    for column in numeric_columns
    if column.casefold() not in non_climate_columns
]

metric_columns = st.columns(5)
metric_columns[0].metric("Registros filtrados", f"{len(filtered_dataframe):,}")
metric_columns[1].metric(
    "Localidades/células",
    f"{filtered_dataframe[location_column].nunique():,}"
    if location_column
    else "—",
)
metric_columns[2].metric(
    "UFs",
    str(filtered_dataframe[state_column].nunique()) if state_column else "—",
)
metric_columns[3].metric(
    "Variáveis numéricas",
    str(len(numeric_columns)),
)
if date_column:
    parsed_dates = pd.to_datetime(filtered_dataframe[date_column], errors="coerce")
    valid_dates = parsed_dates.dropna()
    date_value = (
        f"{valid_dates.min():%d/%m/%Y} – {valid_dates.max():%d/%m/%Y}"
        if not valid_dates.empty
        else "—"
    )
else:
    date_value = "—"
metric_columns[4].metric("Período", date_value)

st.subheader("Série observada")
if not numeric_columns:
    st.info("A fonte não contém colunas numéricas para plotar.")
elif date_column:
    selected_variable = st.selectbox(
        "Variável climática ou AquaCrop",
        options=numeric_columns,
        format_func=variable_label,
        index=(numeric_columns.index("et0_mm") if "et0_mm" in numeric_columns else 0),
    )
    chart_data = filtered_dataframe[[date_column, selected_variable]].copy()
    chart_data[date_column] = pd.to_datetime(chart_data[date_column], errors="coerce")
    chart_data = chart_data.dropna().sort_values(date_column)
    if location_column and filtered_dataframe[location_column].nunique() <= 8:
        chart_data[location_column] = filtered_dataframe.loc[
            chart_data.index, location_column
        ]
        figure = px.line(
            chart_data,
            x=date_column,
            y=selected_variable,
            color=location_column,
            title=variable_label(selected_variable),
        )
    else:
        daily_summary = (
            chart_data.groupby(date_column, as_index=False)[selected_variable]
            .median()
            .sort_values(date_column)
        )
        figure = px.line(
            daily_summary,
            x=date_column,
            y=selected_variable,
            title=f"Mediana temporal · {variable_label(selected_variable)}",
        )
    figure.update_layout(margin=dict(l=8, r=8, t=45, b=8))
    figure.update_yaxes(title_text=variable_label(selected_variable))
    st.plotly_chart(figure, use_container_width=True)
else:
    selected_variable = st.selectbox(
        "Variável", options=numeric_columns, format_func=variable_label
    )
    st.bar_chart(filtered_dataframe[selected_variable].dropna().head(100))

with st.expander("Esquema e qualidade dos dados"):
    st.dataframe(dataframe_schema(filtered_dataframe), use_container_width=True)

with st.expander("Amostra dos dados filtrados"):
    st.dataframe(filtered_dataframe.head(500), use_container_width=True)
