"""Nomes acessíveis, explicações e formatação das métricas de modelos."""

from __future__ import annotations

from typing import Any

import pandas as pd


METRIC_LABELS = {
    "mae": "Erro absoluto médio (MAE)",
    "rmse": "Raiz do erro quadrático médio (RMSE)",
    "r2": "Coeficiente de determinação (R²)",
    "rows_train": "Linhas usadas no treinamento (rows_train)",
    "rows_test": "Linhas usadas na avaliação (rows_test)",
    "rows_used": "Linhas usadas nesta execução (rows_used)",
    "training_seconds": "Duração do treinamento (segundos)",
    "rows_output": "Registros gerados (rows_output)",
    "columns_output": "Colunas geradas (columns_output)",
    "ufs_output": "Estados processados (ufs_output)",
    "primary_metric": "Métrica principal (primary_metric)",
    "problem_type": "Tipo de problema (problem_type)",
    "validation_strategy": "Estratégia de validação (validation_strategy)",
    "target": "Variável-alvo (target)",
    "test_start_date": "Início do período de avaliação",
    "test_end_date": "Fim do período de avaliação",
}

METRIC_DESCRIPTIONS = {
    "mae": (
        "Média da diferença absoluta entre valores observados e previstos; "
        "fica na unidade da variável-alvo. Menor é melhor."
    ),
    "rmse": (
        "Erro médio que penaliza mais as diferenças grandes; fica na unidade "
        "da variável-alvo. Menor é melhor."
    ),
    "r2": (
        "Proporção da variação observada explicada pelo modelo. 1 indica "
        "ajuste perfeito; pode ser negativo."
    ),
    "rows_train": "Quantidade de registros usados para ajustar o modelo.",
    "rows_test": "Quantidade de registros reservados para avaliar o modelo.",
    "rows_used": "Quantidade de registros entregues à execução.",
    "training_seconds": "Tempo total gasto no treinamento, em segundos.",
}

COUNT_METRICS = {
    "rows_train",
    "rows_test",
    "rows_used",
    "rows_output",
    "columns_output",
    "ufs_output",
}

VARIABLE_LABELS = {
    "tmax_c": "Temperatura máxima do ar (tmax_c)",
    "temp_max_c": "Temperatura máxima do ar (temp_max_c)",
    "temperature_2m_max": "Temperatura máxima do ar a 2 m (temperature_2m_max)",
    "tmin_c": "Temperatura mínima do ar (tmin_c)",
    "temp_min_c": "Temperatura mínima do ar (temp_min_c)",
    "temperature_2m_min": "Temperatura mínima do ar a 2 m (temperature_2m_min)",
    "tmean_c": "Temperatura média do ar (tmean_c)",
    "temp_mean_c": "Temperatura média do ar (temp_mean_c)",
    "temperature_2m": "Temperatura do ar a 2 m (temperature_2m)",
    "dew_point_2m": "Temperatura do ponto de orvalho a 2 m (dew_point_2m)",
    "relative_humidity_2m": "Umidade relativa do ar a 2 m (relative_humidity_2m)",
    "vapour_pressure_deficit": "Déficit de pressão de vapor (vapour_pressure_deficit)",
    "eto_mm": "Evapotranspiração de referência (ET₀ · eto_mm)",
    "raw_eto_mm": "Evapotranspiração de referência bruta (raw_eto_mm)",
    "precipitation_mm": "Precipitação diária (precipitation_mm)",
    "precipitation_sum": "Precipitação acumulada (precipitation_sum)",
    "soil_temp_shallow_c": "Temperatura superficial do solo (soil_temp_shallow_c)",
    "soil_temperature_0_to_7cm": "Temperatura do solo de 0 a 7 cm (soil_temperature_0_to_7cm)",
    "soil_temperature_7_to_28cm": "Temperatura do solo de 7 a 28 cm (soil_temperature_7_to_28cm)",
    "soil_temperature_28_to_100cm": "Temperatura do solo de 28 a 100 cm (soil_temperature_28_to_100cm)",
    "soil_temperature_100_to_255cm": "Temperatura do solo de 100 a 255 cm (soil_temperature_100_to_255cm)",
    "soil_moisture_0_to_7cm": "Umidade do solo de 0 a 7 cm (soil_moisture_0_to_7cm)",
    "soil_moisture_7_to_28cm": "Umidade do solo de 7 a 28 cm (soil_moisture_7_to_28cm)",
    "soil_moisture_28_to_100cm": "Umidade do solo de 28 a 100 cm (soil_moisture_28_to_100cm)",
    "soil_moisture_100_to_255cm": "Umidade do solo de 100 a 255 cm (soil_moisture_100_to_255cm)",
    "snow_depth": "Profundidade da neve (snow_depth)",
    "elevation": "Elevação do ponto (elevation)",
    "elevation_m": "Elevação do ponto em metros (elevation_m)",
    "altitude_m": "Altitude do ponto em metros (altitude_m)",
    "thermal_amplitude_c": "Amplitude térmica diária (thermal_amplitude_c)",
    "gdd_c": "Graus-dia de crescimento (gdd_c)",
    "gda": "Graus-dia acumulados (gda)",
    "climatic_balance_mm": "Balanço climático (precipitação − ET₀)",
    "balanco_hidrico_diario": "Balanço hídrico diário (balanco_hidrico_diario)",
    "razao_p_et0": "Razão entre precipitação e ET₀ (razao_p_et0)",
    "gdd": "Graus-dia de crescimento (gdd)",
    "gdd_c": "Graus-dia de crescimento (gdd_c)",
    "is_frost_risk": "Indicador de risco de geada (is_frost_risk)",
    "is_heat_stress": "Indicador de estresse térmico (is_heat_stress)",
    "soil_moisture": "Umidade do solo (soil_moisture)",
    "relative_humidity": "Umidade relativa do ar (relative_humidity)",
    "wind_speed_10m": "Velocidade do vento a 10 m (wind_speed_10m)",
    "radiation_mj_m2": "Radiação solar diária (radiation_mj_m2)",
}


def variable_label(name: str) -> str:
    """Devolve a descrição legível de uma variável e preserva seu nome técnico."""
    return VARIABLE_LABELS.get(
        name,
        f"{name.replace('_', ' ').capitalize()} ({name})",
    )


def metric_label(name: str) -> str:
    """Converte a chave interna de uma métrica em um rótulo legível."""
    return METRIC_LABELS.get(name, name.replace("_", " ").capitalize())


def metric_description(name: str) -> str | None:
    """Retorna a explicação da métrica para ajuda contextual."""
    return METRIC_DESCRIPTIONS.get(name)


def format_metric_value(name: str, value: Any) -> str:
    """Formata contagens, durações e valores decimais para exibição."""
    if name in COUNT_METRICS and isinstance(value, (int, float)):
        return f"{int(value):,}".replace(",", ".")
    if name == "training_seconds" and isinstance(value, (int, float)):
        return f"{value:.1f} s".replace(".", ",")
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(value)


def metrics_table(metrics: dict[str, Any]) -> pd.DataFrame:
    """Monta uma tabela traduzida com valores e explicações de métricas."""
    return pd.DataFrame(
        [
            {
                "Métrica": metric_label(name),
                "Resultado": format_metric_value(name, value),
                "O que representa": metric_description(name) or "",
            }
            for name, value in metrics.items()
        ]
    )
