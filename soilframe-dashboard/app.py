"""Ponto de entrada do dashboard SoilFrame."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

from soilframe_dashboard.ui import apply_theme, render_source_sidebar


APP_ROOT = Path(__file__).resolve().parent
load_dotenv(APP_ROOT / ".env")

st.set_page_config(
    page_title="Dashboard · SoilFrame",
    page_icon="S",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()
logo_path = APP_ROOT / "assets" / "soil-logo.webp"
if logo_path.is_file():
    st.logo(str(logo_path), size="large")
render_source_sidebar()

navigation = st.navigation(
    {
        "Análise de dados": [
            st.Page(
                "pages/overview.py",
                title="Dashboard",
                default=True,
            ),
            st.Page("pages/gold_map.py", title="Mapa da camada Gold"),
            st.Page("pages/data_explorer.py", title="Explorar dados Gold"),
            st.Page("pages/predictions.py", title="Resultados preditivos"),
            st.Page("pages/model_accuracy.py", title="Acurácia e confiabilidade"),
        ],
        "Operação SoilFrame": [
            st.Page("pages/pipeline_control.py", title="Ingestão ERA5-Land"),
            st.Page("pages/training.py", title="Treinar modelo AutoML"),
            st.Page("pages/experiments.py", title="Histórico de execuções"),
        ],
    }
)
navigation.run()
