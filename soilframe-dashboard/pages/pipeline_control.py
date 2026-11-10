"""Controles para ingestão experimental do Lakehouse AquaCrop."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from soilframe_dashboard.filters import STATE_REGION
from soilframe_dashboard.ui import (
    get_job_manager,
    page_header,
    render_geographic_filters,
)


page_header(
    "Ingestão ERA5-Land",
    "Execute o pipeline AquaCrop-Lakehouse em uma pasta isolada do dashboard. "
    "A fonte Gold selecionada e o Data Lake não são destinos de gravação.",
)
render_geographic_filters()
st.warning(
    "Esta ação pode consultar fontes externas e levar vários minutos. "
    "Os arquivos serão gravados em `soilframe-dashboard/outputs/lakehouse`."
)

app_root = Path(__file__).resolve().parents[1]
manager = get_job_manager(str(app_root / "outputs"))

all_states = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO",
    "RR", "RS", "SC", "SE", "SP", "TO",
]
selected_region = st.session_state.get("global_region", "Todas")
states = [
    state
    for state in all_states
    if selected_region == "Todas" or STATE_REGION.get(state) == selected_region
]
default_states = [
    state
    for state in states
    if state == st.session_state.get("global_state", "SP")
]
if not default_states:
    default_states = ["SP"] if "SP" in states else states[:1]
year = st.number_input(
    "Ano",
    min_value=2010,
    max_value=date.today().year,
    value=min(2024, date.today().year),
    step=1,
)
with st.form("lakehouse_pipeline_form"):
    selected_states = st.multiselect(
        "Unidades da Federação",
        options=states,
        default=default_states,
        help="Comece com uma UF para manter o primeiro teste pequeno.",
    )
    options_columns = st.columns(3)
    cells_per_state = options_columns[1].number_input(
        "Células por UF",
        min_value=1,
        max_value=500,
        value=2,
        step=1,
    )
    import_existing_mg = options_columns[2].checkbox(
        "Tentar ingerir arquivo local de MG",
        value=False,
        help="Desativado por padrão para manter a execução independente.",
    )
    date_columns = st.columns(2)
    default_start = date(int(year), 1, 1)
    default_end = min(date(int(year), 12, 31), date.today())
    start_date = date_columns[0].date_input(
        "Data inicial",
        value=default_start,
        min_value=date(2010, 1, 1),
        max_value=date.today(),
        key=f"pipeline_start_{int(year)}",
    )
    end_date = date_columns[1].date_input(
        "Data final",
        value=default_end,
        min_value=date(2010, 1, 1),
        max_value=date.today(),
        key=f"pipeline_end_{int(year)}",
    )
    submitted = st.form_submit_button(
        "Executar pipeline Lakehouse",
        type="primary",
        use_container_width=True,
        disabled=not selected_states or start_date > end_date,
    )

if submitted:
    pipeline_options = {
        "task_type": "pipeline",
        "target": "pipeline_aquacrop_lakehouse",
        "ufs": selected_states,
        "ano": int(year),
        "data_inicio": start_date.isoformat(),
        "data_fim": end_date.isoformat(),
        "celulas_por_uf": int(cells_per_state),
        "ingerir_mg_existente": import_existing_mg,
    }
    run_id = manager.submit_pipeline(pipeline_options)
    st.session_state.active_pipeline_run = run_id
    st.success(f"Pipeline enviado para a fila: `{run_id}`.")
    st.rerun()

active_run_id = st.session_state.get("active_pipeline_run")
if active_run_id:
    active_record = manager.get_run(active_run_id)
    is_active = bool(
        active_record
        and active_record["status"] in {"queued", "running"}
    )

    @st.fragment(run_every="2s" if is_active else None)
    def pipeline_status_panel() -> None:
        run = manager.get_run(active_run_id)
        if run is None:
            st.error("Não encontrei esta execução no histórico do dashboard.")
            return
        st.subheader(f"Pipeline · {active_run_id}")
        if run["status"] in {"queued", "running"}:
            started_at = run.get("started_at")
            elapsed_seconds = 0
            if started_at:
                started = datetime.fromisoformat(started_at)
                elapsed_seconds = max(
                    0,
                    int((datetime.now(timezone.utc) - started).total_seconds()),
                )
            minutes, seconds = divmod(elapsed_seconds, 60)
            st.info(
                f"{'Na fila' if run['status'] == 'queued' else 'Processando'} · "
                f"{minutes:02d}:{seconds:02d}"
            )
        elif run["status"] == "completed":
            st.success(
                f"Pipeline concluído em {run.get('duration_seconds', 0):.1f} s."
            )
            st.json(run["metrics"])
            report_path = run.get("leaderboard_path")
            if report_path and Path(report_path).is_file():
                st.dataframe(pd.read_csv(report_path), use_container_width=True)
            st.code(str(app_root / "outputs" / "lakehouse"), language=None)
        elif run["status"] == "failed":
            st.error(f"Pipeline falhou: {run.get('error', 'sem detalhes')}")
        else:
            st.warning("A execução foi interrompida.")
        if is_active and run["status"] not in {"queued", "running"}:
            st.rerun()

    pipeline_status_panel()
