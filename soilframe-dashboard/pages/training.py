"""Execução de treinos AutoGluon em worker local."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path

import pandas as pd
import streamlit as st

from soilframe_dashboard.data_access import detect_column
from soilframe_dashboard.filters import (
    apply_global_geography_filters,
    render_filters,
)
from soilframe_dashboard.training_config import (
    DATE_COLUMN_ALIASES,
    recommend_problem_type,
    recommend_quality,
    tabular_target_candidates,
    timeseries_target_candidates,
)
from soilframe_dashboard.ui import (
    get_job_manager,
    load_configured_dataframe,
    page_header,
    render_geographic_filters,
)


def target_label(column_name: str) -> str:
    """Expande variáveis AquaCrop conhecidas e mantém a coluna entre parênteses."""
    descriptions = {
        "et0_mm": "Evapotranspiração de referência (ET₀, mm/dia)",
        "eto_mm": "Evapotranspiração de referência (ET₀, mm/dia)",
        "precipitacao_mm": "Precipitação (mm/dia)",
        "tmax_c": "Temperatura máxima do ar (°C)",
        "tmin_c": "Temperatura mínima do ar (°C)",
        "tmean_c": "Temperatura média do ar (°C)",
        "radiacao_solar_mj_m2": "Radiação solar (MJ/m²/dia)",
        "vento_10m_media_ms": "Velocidade média diária do vento a 10 m (m/s)",
        "balanco_hidrico_diario": "Balanço hídrico diário (precipitação − ET₀)",
        "razao_p_et0": "Razão entre precipitação e ET₀ (P/ET₀)",
        "classe_deficit_hidrico": "Classe de déficit hídrico",
        "swi_010": "Índice de água no solo na camada de 0–10 cm (SWI_010)",
        "swi_020": "Índice de água no solo na camada de 0–20 cm (SWI_020)",
    }
    description = descriptions.get(column_name.casefold())
    if description:
        return f"{description} ({column_name})"
    readable_name = column_name.replace("_", " ").strip().capitalize()
    return f"{readable_name} ({column_name})"


page_header(
    "Treinar modelo AutoML",
    "Escolha os dados filtrados, configure o AutoGluon e acompanhe "
    "o tempo da execução.",
)
try:
    tabular_available = find_spec("autogluon.tabular") is not None
except ModuleNotFoundError:
    tabular_available = False
if not tabular_available:
    st.warning(
        "O AutoGluon Tabular não está instalado. Instale "
        "`requirements-automl.txt` para habilitar treinamento."
    )
    st.stop()

try:
    timeseries_available = find_spec("autogluon.timeseries") is not None
except ModuleNotFoundError:
    timeseries_available = False

source_dataframe = load_configured_dataframe()
if source_dataframe is None:
    st.stop()

render_geographic_filters()
source_dataframe = apply_global_geography_filters(source_dataframe)
filtered_dataframe = render_filters(source_dataframe, "training")
st.caption(f"Este treinamento usará {len(filtered_dataframe):,} linhas filtradas.")
st.caption(
    "O alvo precisa representar o resultado que você quer prever. As demais "
    "colunas do recorte ficam disponíveis como preditoras."
)

task_options = ["Regressão/classificação tabular"]
if timeseries_available:
    task_options.append("Série temporal")
else:
    st.caption(
        "Previsão de séries temporais é opcional. Para habilitá-la, instale "
        "`requirements-timeseries.txt`."
    )

task_label = st.selectbox(
    "Tipo de modelo",
    options=task_options,
    key="training_task_label",
)
is_timeseries = task_label == "Série temporal"

if is_timeseries:
    time_series_id_names = {"location_id", "cell_id", "municipio", "uf"}
    id_candidates = [
        column
        for column in filtered_dataframe.columns
        if str(column).casefold() in time_series_id_names
    ]
    timestamp_names = {name.casefold() for name in DATE_COLUMN_ALIASES}
    timestamp_candidates = [
        column
        for column in filtered_dataframe.columns
        if str(column).casefold() in timestamp_names
    ]
    if not id_candidates or not timestamp_candidates:
        st.warning(
            "TimeSeries requer uma coluna identificadora de série "
            "(location_id/cell_id) e uma coluna temporal (data/date)."
        )
        st.stop()
    target_candidates = timeseries_target_candidates(filtered_dataframe)
else:
    target_candidates = tabular_target_candidates(filtered_dataframe)
if not target_candidates:
    st.warning(
        "Não há alvos elegíveis neste recorte. O AutoML precisa de uma variável "
        "com pelo menos dois valores; datas, identificadores e colunas quase "
        "únicas não são oferecidos como alvo."
    )
    st.stop()

preferred_target = next(
    (
        candidate
        for candidate in (
            "SWI_010",
            "eto_mm",
            "et0_mm",
            "balanco_hidrico_diario",
        )
        if candidate in target_candidates
    ),
    target_candidates[0],
)
if st.session_state.get("training_target") not in target_candidates:
    st.session_state.training_target = preferred_target
target = st.selectbox(
    "Variável-alvo",
    options=target_candidates,
    format_func=target_label,
    index=target_candidates.index(preferred_target),
    key="training_target",
)

date_column = detect_column(
    list(filtered_dataframe.columns),
    DATE_COLUMN_ALIASES,
)
target_series = filtered_dataframe[target]
usable_target_rows = filtered_dataframe.loc[target_series.notna()]
location_column = detect_column(
    list(filtered_dataframe.columns),
    ("location_id", "cell_id"),
)
valid_strategies = []
if (
    date_column
    and pd.to_datetime(
        usable_target_rows[date_column],
        errors="coerce",
    ).nunique()
    >= 2
):
    valid_strategies.append("temporal")
if (
    location_column
    and usable_target_rows[location_column].nunique(dropna=True) >= 2
):
    valid_strategies.append("localidade")

recommended_problem, problem_reason = recommend_problem_type(target_series)
usable_rows = int(target_series.notna().sum())
recommended_preset, preset_reason = recommend_quality(usable_rows)
recommended_strategy = (
    "temporal"
    if "temporal" in valid_strategies
    else valid_strategies[0]
    if valid_strategies
    else "temporal"
)
class_count = int(target_series.dropna().nunique())
recommendation_signature = (
    task_label,
    target,
    len(filtered_dataframe),
    usable_rows,
    class_count,
    tuple(valid_strategies),
)
if (
    st.session_state.get("training_recommendation_signature")
    != recommendation_signature
):
    st.session_state.training_problem_type = recommended_problem
    st.session_state.training_preset = recommended_preset
    st.session_state.training_strategy = recommended_strategy
    st.session_state.training_recommendation_signature = recommendation_signature

strategy_labels = {
    "temporal": "Temporal (treina no passado e avalia em datas posteriores)",
    "localidade": "Por localidade (separa células/localidades entre conjuntos)",
}
problem_labels = {
    "regression": "Regressão (valor contínuo)",
    "binary": "Classificação binária (duas classes)",
    "multiclass": "Classificação multiclasse (três ou mais classes)",
}
preset_labels = {
    "medium_quality": "Média — treino inicial mais rápido",
    "good_quality": "Boa — mais tempo para buscar melhor desempenho",
    "best_quality": "Máxima — pode exigir mais tempo e recursos",
}
quality_options = ["medium_quality", "good_quality", "best_quality"]
if recommended_preset not in quality_options:
    quality_options.insert(0, recommended_preset)

time_limit = st.number_input(
    "Limite de treino (segundos)",
    min_value=30,
    max_value=3600,
    value=300,
    step=30,
    key="training_time_limit",
)
preset = st.selectbox(
    "Qualidade do AutoGluon",
    options=quality_options,
    format_func=lambda value: preset_labels.get(value, value),
    key="training_preset",
)

if not is_timeseries:
    config_columns = st.columns(2)
    problem_type = config_columns[0].selectbox(
        "Tipo da variável-alvo",
        options=["regression", "binary", "multiclass"],
        format_func=lambda value: problem_labels[value],
        key="training_problem_type",
    )
    target_is_numeric = pd.api.types.is_numeric_dtype(target_series)
    problem_is_valid = (
        problem_type == "regression" and target_is_numeric
    ) or (problem_type == "binary" and class_count == 2) or (
        problem_type == "multiclass" and class_count >= 2
    )
    can_train = (
        bool(valid_strategies)
        and usable_rows >= 20
        and class_count >= 2
        and problem_is_valid
    )
    if not valid_strategies:
        st.warning(
            "A validação tabular exige pelo menos duas datas válidas ou duas "
            "localidades/células com alvo preenchido."
        )
        strategy_options = [recommended_strategy]
    else:
        strategy_options = valid_strategies
    validation_strategy = config_columns[1].selectbox(
        "Separação treino/teste",
        options=strategy_options,
        format_func=lambda value: strategy_labels.get(value, value),
        key="training_strategy",
    )
    random_state = st.number_input(
        "Semente da divisão treino/teste",
        min_value=0,
        max_value=2_147_483_647,
        value=42,
        step=1,
        help="Use sementes diferentes em execuções repetidas para medir a estabilidade da avaliação. Na divisão temporal, a semente não altera o corte.",
        key="training_random_state",
    )
    st.caption(
        "Sugestão para este alvo: "
        f"{problem_labels[recommended_problem]} · "
        f"{preset_labels[recommended_preset]} · "
        f"{strategy_labels[recommended_strategy]}. "
        "Os campos continuam editáveis."
    )
    st.caption(f"Motivo da sugestão: {problem_reason}; {preset_reason}.")
    if class_count < 2:
        st.warning(
            "O alvo tem menos de duas classes/valores distintos neste recorte. "
            "Amplie os filtros ou escolha outra variável."
        )
    elif not problem_is_valid:
        st.warning(
            "O tipo de problema selecionado não corresponde ao tipo de dado "
            "ou à quantidade de classes do alvo."
        )
    submitted = st.button(
        "Iniciar treinamento",
        type="primary",
        use_container_width=True,
        disabled=not can_train,
    )
    options = {
        "task_type": "tabular",
        "target": target,
        "problem_type": problem_type,
        "validation_strategy": validation_strategy,
        "random_state": int(random_state),
        "date_column": date_column,
        "time_limit": int(time_limit),
        "preset": preset,
        "source_path": st.session_state.get("soilframe_source_path"),
        "source_table": st.session_state.get("soilframe_sqlite_table"),
        "source_label": st.session_state.get("soilframe_gold_dataset"),
    }
else:
    st.caption(
        "Sugestão: alvo contínuo, divisão temporal e "
        f"{preset_labels[recommended_preset]}. Os campos continuam editáveis."
    )
    time_columns = st.columns(3)
    item_id_column = time_columns[0].selectbox(
        "ID da série",
        options=id_candidates,
    )
    timestamp_column = time_columns[1].selectbox(
        "Coluna temporal",
        options=timestamp_candidates,
        index=(
            next(
                (
                    index
                    for index, column in enumerate(timestamp_candidates)
                    if str(column).casefold() == "data"
                ),
                0,
            )
        ),
    )
    prediction_length = time_columns[2].number_input(
        "Horizonte (períodos)",
        min_value=1,
        max_value=90,
        value=10,
    )
    frequency = st.selectbox(
        "Frequência dos dados",
        options=["D", "10D", "W", "MS"],
        format_func=lambda value: {
            "D": "Diária",
            "10D": "Decendial",
            "W": "Semanal",
            "MS": "Mensal",
        }[value],
    )
    valid_timestamp_count = pd.to_datetime(
        filtered_dataframe[timestamp_column],
        errors="coerce",
    ).nunique()
    valid_series_count = filtered_dataframe[item_id_column].nunique(dropna=True)
    can_train_timeseries = (
        usable_rows >= 20
        and class_count >= 2
        and valid_timestamp_count >= 2
        and valid_series_count >= 1
    )
    if valid_timestamp_count < 2:
        st.warning("A série temporal precisa ter ao menos duas datas válidas.")
    if usable_rows < 20 or class_count < 2:
        st.warning(
            "A série precisa ter pelo menos 20 valores preenchidos e dois "
            "valores distintos no alvo."
        )
    submitted = st.button(
        "Iniciar previsão temporal",
        type="primary",
        use_container_width=True,
        disabled=not can_train_timeseries,
    )
    options = {
        "task_type": "timeseries",
        "target": target,
        "time_limit": int(time_limit),
        "preset": preset,
        "prediction_length": int(prediction_length),
        "item_id_column": item_id_column,
        "timestamp_column": timestamp_column,
        "frequency": frequency,
        "source_path": st.session_state.get("soilframe_source_path"),
        "source_table": st.session_state.get("soilframe_sqlite_table"),
        "source_label": st.session_state.get("soilframe_gold_dataset"),
    }

if submitted:
    app_root = Path(__file__).resolve().parents[1]
    manager = get_job_manager(str(app_root / "outputs"))
    run_id = manager.submit(filtered_dataframe, options)
    st.session_state.active_soilframe_run = run_id
    st.success(f"Execução `{run_id}` enviada para a fila.")
    st.rerun()


def _render_active_run(run_id: str, auto_refresh: bool) -> None:
    """Mostra estado, cronômetro e eventual erro de uma execução."""
    app_root = Path(__file__).resolve().parents[1]
    manager = get_job_manager(str(app_root / "outputs"))
    run = manager.get_run(run_id)
    if run is None:
        st.error("Não encontrei a execução solicitada no histórico do dashboard.")
        return
    status_labels = {
        "queued": "Na fila",
        "running": "Treinando",
        "completed": "Concluído",
        "failed": "Falhou",
        "interrupted": "Interrompido",
    }
    st.subheader(f"Execução {run_id}")
    if run["status"] in {"queued", "running"}:
        started_at = run.get("started_at")
        if started_at:
            start_time = datetime.fromisoformat(started_at)
            elapsed_seconds = max(
                0,
                int((datetime.now(timezone.utc) - start_time).total_seconds()),
            )
        else:
            elapsed_seconds = 0
        minutes, seconds = divmod(elapsed_seconds, 60)
        st.info(
            f"{status_labels[run['status']]} · tempo decorrido "
            f"{minutes:02d}:{seconds:02d}"
        )
        if auto_refresh:
            st.caption(
                "O estado atualiza automaticamente enquanto esta página "
                "estiver aberta."
            )
    elif run["status"] == "completed":
        duration = run.get("duration_seconds") or 0
        minutes, seconds = divmod(int(duration), 60)
        st.success(f"Concluído em {minutes:02d}:{seconds:02d}.")
        if run.get("metrics"):
            st.json(run["metrics"])
    elif run["status"] == "failed":
        st.error(
            f"Treinamento falhou: {run.get('error', 'erro sem detalhes')}"
        )
    else:
        st.warning("A execução foi interrompida antes de terminar.")
    if auto_refresh and run["status"] not in {"queued", "running"}:
        st.rerun()


active_run_id = st.session_state.get("active_soilframe_run")
if active_run_id:
    app_root = Path(__file__).resolve().parents[1]
    manager = get_job_manager(str(app_root / "outputs"))
    active_record = manager.get_run(active_run_id)
    is_active = bool(
        active_record
        and active_record["status"] in {"queued", "running"}
    )

    @st.fragment(run_every="2s" if is_active else None)
    def active_run_panel() -> None:
        _render_active_run(active_run_id, is_active)

    active_run_panel()
