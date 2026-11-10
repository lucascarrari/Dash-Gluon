"""Histórico e metadados dos jobs do dashboard."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from soilframe_dashboard.metrics import metrics_table
from soilframe_dashboard.ui import (
    get_job_manager,
    page_header,
    render_geographic_filters,
)


page_header(
    "Histórico de execuções",
    "Consulte o status, os parâmetros e as métricas dos pipelines e modelos.",
)
render_geographic_filters()
app_root = Path(__file__).resolve().parents[1]
manager = get_job_manager(str(app_root / "outputs"))
runs = manager.list_runs()
if not runs:
    st.info(
        "O histórico está vazio. As execuções aparecerão aqui depois "
        "do primeiro treino."
    )
    st.stop()

history = pd.DataFrame(
    [
        {
            "ID": run["run_id"],
            "Status": run["status"],
            "Tarefa": run["task_type"],
            "Alvo": run["target"],
            "Início": run["started_at"] or run["created_at"],
            "Duração (s)": run["duration_seconds"],
        }
        for run in runs
    ]
)
st.dataframe(history, use_container_width=True, hide_index=True)

selected_run_id = st.selectbox(
    "Detalhes da execução",
    options=[run["run_id"] for run in runs],
)
selected_run = next(run for run in runs if run["run_id"] == selected_run_id)
left_column, right_column = st.columns(2)
with left_column:
    st.markdown("#### Configuração")
    st.json(selected_run["options"])
with right_column:
    st.markdown("#### Métricas")
    if selected_run["metrics"]:
        st.dataframe(
            metrics_table(selected_run["metrics"]),
            use_container_width=True,
            hide_index=True,
        )
    elif selected_run.get("error"):
        st.error(selected_run["error"])
    else:
        st.caption("Métricas ainda não disponíveis.")

if selected_run.get("leaderboard_path"):
    leaderboard_path = Path(selected_run["leaderboard_path"])
    if leaderboard_path.is_file():
        report_title = (
            "Relatório do pipeline"
            if selected_run["task_type"] == "pipeline"
            else "Leaderboard AutoGluon"
        )
        st.markdown(f"#### {report_title}")
        st.dataframe(pd.read_csv(leaderboard_path), use_container_width=True)
