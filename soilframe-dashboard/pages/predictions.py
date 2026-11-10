"""Visualização de previsões já produzidas por execuções concluídas."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from soilframe_dashboard.data_access import detect_column
from soilframe_dashboard.metrics import (
    format_metric_value,
    metric_description,
    metric_label,
    variable_label,
)
from soilframe_dashboard.ui import (
    get_job_manager,
    page_header,
    render_geographic_filters,
)


PREDICTION_LABELS = {
    "temperature_2m": "Temperatura do ar a 2 m",
    "temperature_2m_max": "Temperatura máxima do ar a 2 m",
    "temperature_2m_min": "Temperatura mínima do ar a 2 m",
    "tmax_c": "Temperatura máxima do ar",
    "tmin_c": "Temperatura mínima do ar",
    "tmean_c": "Temperatura média do ar",
    "dew_point_2m": "Temperatura do ponto de orvalho a 2 m",
    "relative_humidity_2m": "Umidade relativa do ar a 2 m",
    "relative_humidity": "Umidade relativa do ar",
    "vapour_pressure_deficit": "Déficit de pressão de vapor",
    "eto_mm": "Evapotranspiração de referência (ET₀)",
    "et0_mm": "Evapotranspiração de referência (ET₀)",
    "swi_010": "Índice de água no solo (SWI_010)",
    "precipitation_sum": "Precipitação acumulada",
    "precipitacao_mm": "Precipitação",
    "precipitation_mm": "Precipitação",
    "snow_depth": "Profundidade da neve",
    "wind_speed_10m": "Velocidade do vento a 10 m",
    "wind_speed_10m_max": "Velocidade máxima do vento a 10 m",
    "radiation_mj_m2": "Radiação solar",
    "shortwave_radiation_sum": "Radiação solar acumulada",
}
PREDICTION_UNITS = {
    "temperature_2m": "°C",
    "temperature_2m_max": "°C",
    "temperature_2m_min": "°C",
    "tmax_c": "°C",
    "tmin_c": "°C",
    "tmean_c": "°C",
    "dew_point_2m": "°C",
    "relative_humidity_2m": "%",
    "relative_humidity": "%",
    "vapour_pressure_deficit": "kPa",
    "eto_mm": "mm/dia",
    "et0_mm": "mm/dia",
    "precipitation_sum": "mm",
    "precipitacao_mm": "mm",
    "precipitation_mm": "mm",
    "snow_depth": "m",
    "wind_speed_10m": "m/s",
    "wind_speed_10m_max": "m/s",
    "radiation_mj_m2": "MJ/m²",
    "shortwave_radiation_sum": "MJ/m²",
}


def prediction_variable_name(column_name: str, target: str | None = None) -> str:
    """Devolve o nome humano da variável, sem expor o identificador interno."""
    source_name = target if column_name in {"mean", "median"} and target else column_name
    key = source_name.removeprefix("previsao_").casefold()
    if key in PREDICTION_LABELS:
        return PREDICTION_LABELS[key]
    label = variable_label(key)
    technical_suffix = f" ({key})"
    return label.removesuffix(technical_suffix)


def prediction_series_label(column_name: str, target: str | None = None) -> str:
    """Nome legível usado no seletor e no gráfico de previsões."""
    variable = prediction_variable_name(column_name, target)
    if column_name == "mean":
        return f"Média prevista de {variable}"
    if column_name == "median":
        return f"Mediana prevista de {variable}"
    return f"Previsão · {variable}"


def prediction_unit(column_name: str, target: str | None = None) -> str | None:
    """Unidade conhecida do alvo; não infere unidade para campos desconhecidos."""
    source_name = target if column_name in {"mean", "median"} and target else column_name
    key = source_name.removeprefix("previsao_").casefold()
    if key.startswith("soil_moisture_"):
        return "m³/m³"
    if key.startswith("soil_temperature_"):
        return "°C"
    return PREDICTION_UNITS.get(key)


page_header(
    "Resultados preditivos",
    "Consulte gráficos, métricas e arquivos gerados pelos modelos treinados.",
)
render_geographic_filters()
app_root = Path(__file__).resolve().parents[1]
manager = get_job_manager(str(app_root / "outputs"))
completed_runs = [
    run
    for run in manager.list_runs()
    if run["status"] == "completed"
    and run["task_type"] in {"tabular", "timeseries"}
]
if not completed_runs:
    st.info(
        "Ainda não há previsões concluídas. Inicie uma execução "
        "na página Treinar modelo AutoML."
    )
    st.stop()

run_ids = [run["run_id"] for run in completed_runs]
selected_run_id = st.selectbox("Execução", options=run_ids)
selected_run = next(run for run in completed_runs if run["run_id"] == selected_run_id)
target_names = {
    "eto_mm": "Evapotranspiração de referência (ET₀)",
    "et0_mm": "Evapotranspiração de referência (ET₀)",
    "swi_010": "Índice de água no solo (SWI_010)",
}
task_names = {"tabular": "Modelo tabular", "timeseries": "Série temporal"}
target = selected_run["target"]
task_type = selected_run["task_type"]
st.caption(
    f"Alvo: {target_names.get(target, prediction_variable_name(target))} · "
    f"tipo: {task_names.get(task_type, task_type)} · "
    f"criada: {selected_run['created_at']}"
)
if selected_run.get("metrics"):
    metric_items = [
        (name, value)
        for name, value in selected_run["metrics"].items()
        if isinstance(value, (int, float))
    ]
    if metric_items:
        metric_columns = st.columns(min(4, len(metric_items)))
        for index, (name, value) in enumerate(metric_items[:4]):
            metric_columns[index].metric(
                metric_label(name),
                format_metric_value(name, value),
                help=metric_description(name),
            )

predictions_path = selected_run.get("predictions_path")
if not predictions_path or not Path(predictions_path).is_file():
    st.warning("O arquivo de previsões não está disponível nesta execução.")
    st.stop()

predictions_dataframe = pd.read_csv(predictions_path)
date_column = detect_column(
    list(predictions_dataframe.columns),
    ("data", "date", "timestamp", "timestamp_utc", "datetime"),
)
prediction_candidates = [
    column
    for column in predictions_dataframe.select_dtypes(include="number").columns
    if column.startswith("previsao_") or column in {"mean", "median"}
]
if prediction_candidates:
    prediction_column = st.selectbox(
        "Variável prevista",
        prediction_candidates,
        format_func=lambda column: prediction_series_label(column, target),
    )
    if date_column:
        chart_data = predictions_dataframe.copy()
        chart_data["_chart_date"] = pd.to_datetime(
            chart_data[date_column], errors="coerce"
        )
        chart_data["_chart_value"] = pd.to_numeric(
            chart_data[prediction_column], errors="coerce"
        )
        chart_data = chart_data.dropna(subset=["_chart_date", "_chart_value"])
        if chart_data.empty:
            st.info("Esta execução não contém datas e valores previstos que possam ser exibidos.")
        else:
            locality_column = detect_column(
                list(chart_data.columns),
                (
                    "location_name", "nome_localidade", "municipio", "município",
                    "location_id", "cell_id", "grid_id", "item_id",
                ),
            )
            state_column = detect_column(
                list(chart_data.columns), ("uf", "state", "estado", "sigla_uf")
            )
            point_id_column = detect_column(
                list(chart_data.columns), ("location_id", "cell_id", "grid_id", "item_id")
            )
            chart_data["_chart_locality"] = "Localidade não informada"
            if locality_column:
                chart_data["_chart_locality"] = (
                    chart_data[locality_column]
                    .astype("string")
                    .fillna("Localidade sem nome")
                    .astype(str)
                )
                if state_column and state_column != locality_column:
                    chart_data["_chart_locality"] += (
                        " · "
                        + chart_data[state_column]
                        .astype("string")
                        .fillna("UF não informada")
                        .astype(str)
                    )
                if point_id_column and point_id_column != locality_column:
                    chart_data["_chart_locality"] += (
                        " · ponto " + chart_data[point_id_column].astype(str)
                    )
                values = sorted(chart_data["_chart_locality"].dropna().unique())
                if len(values) > 1:
                    selected_locality = st.selectbox("Localidade da previsão", values)
                    chart_data = chart_data.loc[
                        chart_data["_chart_locality"] == selected_locality
                    ]

            chart_data = chart_data.sort_values("_chart_date")
            variable_name = prediction_variable_name(prediction_column, target)
            series_name = prediction_series_label(prediction_column, target)
            unit = prediction_unit(prediction_column, target)
            y_title = f"{variable_name} ({unit})" if unit else variable_name
            time_deltas = chart_data["_chart_date"].diff().dropna()
            hourly = not time_deltas.empty and time_deltas.median() < pd.Timedelta(days=1)
            time_format = "%d/%m %H:%M" if hourly else "%d/%m/%Y"
            hover_time_format = "%d/%m/%Y %H:%M" if hourly else "%d/%m/%Y"
            value_format = f"%{{y:.2f}} {unit}" if unit else "%{y:.2f}"
            figure = px.line(
                chart_data,
                x="_chart_date",
                y="_chart_value",
                custom_data=["_chart_locality"],
                labels={"_chart_date": "Data e hora", "_chart_value": y_title},
                title=series_name,
            )
            figure.update_traces(
                hovertemplate=(
                    f"<b>{variable_name}</b><br>"
                    f"Data e hora: %{{x|{hover_time_format}}}<br>"
                    "Localidade: %{customdata[0]}<br>"
                    f"Valor previsto: {value_format}<extra></extra>"
                )
            )
            figure.update_layout(
                xaxis_title="Data e hora" if hourly else "Data",
                yaxis_title=y_title,
                hovermode="closest",
                legend_title_text="Localidade",
                showlegend=False,
                separators=",.",
            )
            figure.update_xaxes(tickformat=time_format)
            figure.update_yaxes(tickformat=".2f")
            st.caption(
                "Passe o cursor sobre um ponto para ver data, localidade, variável e valor "
                + (f"na unidade {unit}." if unit else "da previsão.")
            )
            st.plotly_chart(figure, use_container_width=True)
    else:
        st.info("Não encontrei uma coluna de data/hora para montar a série prevista.")

table_column_config = {}
for column in prediction_candidates:
    unit = prediction_unit(column, target)
    label = prediction_series_label(column, target)
    table_column_config[column] = st.column_config.NumberColumn(
        label=f"{label} ({unit})" if unit else label,
        format="%.2f",
    )
if date_column:
    table_column_config[date_column] = st.column_config.TextColumn(
        label="Data e hora"
    )
st.dataframe(
    predictions_dataframe.head(5_000),
    column_config=table_column_config,
    use_container_width=True,
)
st.download_button(
    "Baixar previsões CSV",
    data=predictions_dataframe.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"previsoes_{selected_run_id}.csv",
    mime="text/csv",
)
