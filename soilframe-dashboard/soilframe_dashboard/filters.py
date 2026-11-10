"""Filtros compartilhados para exploração de dados AquaCrop."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .data_access import detect_column


STATE_REGION = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste", "DF": "Centro-Oeste", "GO": "Centro-Oeste",
    "MT": "Centro-Oeste", "MS": "Centro-Oeste", "ES": "Sudeste",
    "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste", "PR": "Sul",
    "RS": "Sul", "SC": "Sul",
}


def add_region_column(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta a macrorregião brasileira a partir da UF, quando possível."""
    result = dataframe.copy()
    state_column = detect_column(
        list(result.columns), ("uf", "state", "estado", "sigla_uf")
    )
    if state_column is not None:
        result["macro_region"] = (
            result[state_column].astype("string").str.upper().map(STATE_REGION)
        )
    return result


def apply_global_geography_filters(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Aplica Região, UF e Município selecionados globalmente no dashboard."""
    filtered = add_region_column(dataframe)
    region = st.session_state.get("global_region", "Todas")
    state = st.session_state.get("global_state", "Todas")
    municipality = st.session_state.get("global_municipality", "Todos")
    location = st.session_state.get("global_location", "Todas")

    region_column = detect_column(
        list(filtered.columns), ("macro_region", "regiao", "região", "region")
    )
    state_column = detect_column(
        list(filtered.columns), ("uf", "state", "estado", "sigla_uf")
    )
    municipality_column = detect_column(
        list(filtered.columns),
        (
            "municipio", "município", "municipality", "city",
            "location_name", "nome_localidade", "localidade",
        ),
    )
    location_column = detect_column(
        list(filtered.columns),
        ("grid_id", "cell_id", "location_id", "id_celula", "item_id"),
    )
    if region != "Todas" and region_column:
        filtered = filtered.loc[filtered[region_column].eq(region)]
    if state != "Todas" and state_column:
        filtered = filtered.loc[filtered[state_column].astype(str).str.upper().eq(state)]
    if municipality != "Todos" and municipality_column:
        filtered = filtered.loc[
            filtered[municipality_column].astype(str).eq(municipality)
        ]
    if location != "Todas" and location_column:
        filtered = filtered.loc[filtered[location_column].astype(str).eq(location)]
    return filtered.reset_index(drop=True)


def render_filters(dataframe: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """Renderiza filtros dimensionais e temporais aplicáveis aos dados.

    Args:
        dataframe: Dados Gold carregados.
        key_prefix: Prefixo único para chaves dos widgets Streamlit.

    Returns:
        Cópia filtrada dos dados.
    """
    filtered = dataframe.copy()
    columns = list(dataframe.columns)
    dimension_aliases = (
        ("Localidade/célula", ("grid_id", "cell_id", "location_id", "id_celula")),
        ("Cultura", ("cultura", "culture", "crop", "cultivar")),
        ("Estação", ("estacao_ano", "estação_ano", "season")),
    )

    present_dimensions = [
        (label, detect_column(columns, aliases))
        for label, aliases in dimension_aliases
    ]
    present_dimensions = [item for item in present_dimensions if item[1] is not None]
    if present_dimensions:
        filter_columns = st.columns(min(3, len(present_dimensions)))
        for index, (label, column_name) in enumerate(present_dimensions):
            assert column_name is not None
            values = dataframe[column_name].dropna().unique().tolist()
            values = sorted(values, key=lambda value: str(value))
            with filter_columns[index % len(filter_columns)]:
                if len(values) <= 80:
                    selected = st.multiselect(
                        label,
                        options=values,
                        key=f"{key_prefix}_{column_name}",
                    )
                    if selected:
                        filtered = filtered.loc[filtered[column_name].isin(selected)]
                else:
                    search = st.text_input(
                        f"Buscar {label.casefold()}",
                        key=f"{key_prefix}_{column_name}_search",
                    ).strip()
                    if search:
                        filtered = filtered.loc[
                            filtered[column_name].astype(str).str.contains(
                                search,
                                case=False,
                                regex=False,
                                na=False,
                            )
                        ]

    date_column = detect_column(
        columns,
        ("data", "date", "timestamp", "timestamp_utc", "datetime", "data_referencia"),
    )
    if date_column is not None:
        parsed_dates = pd.to_datetime(dataframe[date_column], errors="coerce")
        valid_dates = parsed_dates.dropna()
        if not valid_dates.empty:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
            date_range = st.date_input(
                "Período",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                key=f"{key_prefix}_{date_column}_range",
            )
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start_date, end_date = date_range
                filtered_dates = pd.to_datetime(filtered[date_column], errors="coerce")
                filtered = filtered.loc[
                    filtered_dates.dt.date.between(start_date, end_date)
                ]
    return filtered.reset_index(drop=True)
