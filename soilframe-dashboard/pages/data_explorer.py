"""Exploração tabular e filtros dos dados curados."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from soilframe_dashboard.data_access import detect_column, dataframe_schema
from soilframe_dashboard.filters import (
    apply_global_geography_filters,
    render_filters,
)
from soilframe_dashboard.metrics import variable_label
from soilframe_dashboard.ui import (
    load_configured_dataframe,
    page_header,
    render_geographic_filters,
)


page_header(
    "Explorar dados Gold",
    "Filtre os dados AquaCrop por região, localidade, cultura e período.",
)
source_dataframe = load_configured_dataframe()
if source_dataframe is None:
    st.stop()

render_geographic_filters()
source_dataframe = apply_global_geography_filters(source_dataframe)

filtered_dataframe = render_filters(source_dataframe, "explorer")
st.caption(f"Exibindo {len(filtered_dataframe):,} registros após os filtros.")

tab_table, tab_chart, tab_schema = st.tabs(
    ["Tabela", "Gráfico", "Esquema"]
)
with tab_table:
    st.dataframe(
        filtered_dataframe.head(5_000),
        use_container_width=True,
        height=520,
    )
    st.download_button(
        "Baixar recorte CSV",
        data=filtered_dataframe.to_csv(index=False).encode("utf-8-sig"),
        file_name="soilframe_recorte_aquacrop.csv",
        mime="text/csv",
    )

with tab_chart:
    numeric_columns = filtered_dataframe.select_dtypes(
        include="number"
    ).columns.tolist()
    if not numeric_columns:
        st.info("Não há variáveis numéricas neste recorte.")
    else:
        date_column = detect_column(
            list(filtered_dataframe.columns),
            ("data", "date", "timestamp", "timestamp_utc", "datetime"),
        )
        variable = st.selectbox(
            "Variável",
            numeric_columns,
            key="explorer_variable",
            format_func=variable_label,
        )
        if date_column:
            chart_data = filtered_dataframe[[date_column, variable]].copy()
            chart_data[date_column] = pd.to_datetime(
                chart_data[date_column],
                errors="coerce",
            )
            chart_data = chart_data.dropna().sort_values(date_column)
            summary = chart_data.groupby(date_column, as_index=False)[variable].median()
            figure = px.line(
                summary,
                x=date_column,
                y=variable,
                title=variable_label(variable),
            )
            st.plotly_chart(figure, use_container_width=True)
        else:
            st.bar_chart(filtered_dataframe[variable].dropna().head(200))

with tab_schema:
    st.dataframe(dataframe_schema(filtered_dataframe), use_container_width=True)
