"""Mapa interativo da camada Gold AquaCrop."""

from __future__ import annotations

import streamlit as st

from soilframe_dashboard.map_view import load_classified_points, render_coordinate_map
from soilframe_dashboard.ui import page_header, render_geographic_filters


page_header(
    "Mapa da camada Gold",
    "Explore as variáveis climáticas nos pontos do grid brasileiro e compare "
    "as distribuições geográficas.",
)
source_path = st.session_state.get("soilframe_source_path", "").strip()
source_table = st.session_state.get("soilframe_sqlite_table")
if not source_path:
    st.info("Escolha uma fonte Gold Parquet, CSV, coleção CSV ou SQLite na barra lateral.")
    st.stop()

render_geographic_filters()

try:
    with st.spinner("Identificando municípios e preparando os pontos brasileiros..."):
        classified_points = load_classified_points(source_path, source_table)
except Exception as exc:
    st.error(f"Não foi possível identificar os pontos da camada Gold: {exc}")
    st.stop()

render_coordinate_map(source_path, source_table, classified_points)
