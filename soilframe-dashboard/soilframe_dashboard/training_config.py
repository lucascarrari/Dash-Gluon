"""Regras de elegibilidade e recomendações para configurações de treino."""

from __future__ import annotations

import pandas as pd


DATE_COLUMN_ALIASES = (
    "data",
    "date",
    "timestamp",
    "timestamp_utc",
    "time",
    "time_utc",
    "valid_time",
    "datetime",
    "datetime_utc",
    "date_utc",
    "data_referencia",
)

IDENTIFIER_COLUMN_ALIASES = (
    "id",
    "location_id",
    "cell_id",
    "grid_id",
    "id_celula",
    "item_id",
    "municipio",
    "município",
    "municipality",
    "city",
    "location_name",
    "nome_localidade",
    "localidade",
    "uf",
    "state",
    "estado",
    "sigla_uf",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "macro_region",
    "regiao",
    "região",
    "region",
)


def _normalized_names(names: tuple[str, ...]) -> set[str]:
    return {name.casefold() for name in names}


def tabular_target_candidates(dataframe: pd.DataFrame) -> list[str]:
    """Devolve alvos numéricos ou categóricos sem datas e identificadores.

    Colunas categóricas com cardinalidade muito alta são retiradas por serem,
    em geral, identificadores ou texto livre. Nomes conhecidos de data e
    identificador são excluídos independentemente do tipo da coluna.
    """
    excluded_names = _normalized_names(
        DATE_COLUMN_ALIASES + IDENTIFIER_COLUMN_ALIASES
    )
    candidates: list[str] = []
    for column in dataframe.columns:
        series = dataframe[column].dropna()
        if column.casefold() in excluded_names or series.empty:
            continue
        unique_count = int(series.nunique())
        if unique_count < 2:
            continue
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        if not pd.api.types.is_numeric_dtype(series):
            max_class_count = min(100, max(2, int(len(series) * 0.5)))
            if unique_count > max_class_count:
                continue
        candidates.append(column)
    return candidates


def timeseries_target_candidates(dataframe: pd.DataFrame) -> list[str]:
    """Devolve apenas alvos numéricos próprios para previsão temporal."""
    excluded_names = _normalized_names(
        DATE_COLUMN_ALIASES + IDENTIFIER_COLUMN_ALIASES
    )
    return [
        column
        for column in dataframe.select_dtypes(include="number").columns
        if column.casefold() not in excluded_names
        and dataframe[column].nunique(dropna=True) >= 2
    ]


def recommend_problem_type(series: pd.Series) -> tuple[str, str]:
    """Sugere regressão ou classificação conforme tipo e cardinalidade do alvo."""
    non_null_target = series.dropna()
    class_count = int(non_null_target.nunique())
    target_name = str(series.name).casefold()
    class_name_tokens = (
        "classe",
        "class",
        "categoria",
        "category",
        "status",
        "label",
        "risco",
    )
    looks_categorical = any(token in target_name for token in class_name_tokens)

    if pd.api.types.is_bool_dtype(series):
        return "binary", "o alvo contém dois estados booleanos"
    if not pd.api.types.is_numeric_dtype(series):
        if class_count == 2:
            return "binary", "o alvo categórico possui duas classes"
        return "multiclass", f"o alvo categórico possui {class_count} classes"
    if class_count == 2 and looks_categorical:
        return "binary", "o nome e os valores do alvo indicam duas classes"
    if class_count > 2 and looks_categorical:
        return "multiclass", f"o nome do alvo indica {class_count} classes"
    if class_count == 2 and set(non_null_target.unique()) == {0, 1}:
        return "binary", "o alvo numérico está codificado como 0 e 1"
    return "regression", "o alvo é numérico e será previsto como valor contínuo"


def recommend_quality(row_count: int) -> tuple[str, str]:
    """Sugere um preset sem substituir a escolha explícita do usuário."""
    if row_count >= 50_000:
        return (
            "good_quality",
            "recorte com 50 mil linhas ou mais; prioriza qualidade preditiva",
        )
    return (
        "medium_quality",
        "recorte menor que 50 mil linhas; favorece um treino inicial mais rápido",
    )
