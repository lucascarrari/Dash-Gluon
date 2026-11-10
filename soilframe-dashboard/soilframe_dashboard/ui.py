"""Componentes visuais e configuração compartilhada das páginas."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from .data_access import csv_source_files, detect_column, list_sqlite_tables, load_source
from .filters import add_region_column


DEFAULT_GOLD_SOURCE = "ERA5-Land · Tmax/Tmin e solo diária · 67 localidades/27 UFs"
LEGACY_LAKE_DIRECTORY_NAMES = {"datalake acquacrop", "datalake openmeteo"}


def _gold_sources() -> dict[str, str]:
    """Lista produtos Gold existentes no novo Data Lake, sem unir modelos."""
    lake_root = Path(__file__).resolve().parents[2] / "Base de dados"
    gold_root = lake_root / "3_ouro"
    candidates = {
        DEFAULT_GOLD_SOURCE: gold_root
        / "era5_land_daily_national"
        / "tmax_tmin_soil_temp_era5_land_national.csv",
        "ERA5 · precipitação diária · 27 UFs": gold_root
        / "era5"
        / "precipitacao_diaria.csv",
        "ERA5-Seamless · ETo diária parcial · 31 localidades/18 UFs": gold_root
        / "regional"
        / "era5_seamless"
        / "eto_diaria_nacional_parcial.csv",
        "ERA5-Land · horária · produto Gold existente": gold_root
        / "era5_land"
        / "aquacrop_brasil_era5_land_horario.parquet",
        "ERA5 · horária Norte/Centro-Oeste · 24 localidades": gold_root
        / "regional"
        / "era5_hourly"
        / "era5_horario_norte_centro_oeste.csv",
        "ERA5 · horária expansão · 16 localidades": gold_root
        / "regional"
        / "era5_hourly_national_expansion",
    }
    available = {
        label: str(path) for label, path in candidates.items() if path.exists()
    }
    configured = os.getenv("SOILFRAME_GOLD_PATH", "").strip()
    if configured and not _is_legacy_lake_path(configured):
        configured_path = Path(configured).expanduser()
        if configured_path.exists() and str(configured_path) not in available.values():
            available[f"Fonte configurada · {configured_path.name}"] = str(configured_path)
    return available


def _is_legacy_lake_path(source_path: str) -> bool:
    """Identifica caminhos antigos que não devem mais ser fonte do dashboard."""
    parts = source_path.replace("\\", "/").casefold().split("/")
    return any(part in LEGACY_LAKE_DIRECTORY_NAMES for part in parts)


def _select_gold_source() -> None:
    """Aponta a fonte ativa para a base Gold escolhida no menu."""
    selected_name = st.session_state.get("soilframe_gold_dataset", "")
    selected_path = _gold_sources().get(selected_name)
    if selected_path:
        st.session_state.soilframe_source_path = selected_path


def render_geographic_filters() -> None:
    """Renderiza os filtros geográficos em cascata no corpo da página atual."""
    source_path = st.session_state.get("soilframe_source_path", "").strip()
    table_name = st.session_state.get("soilframe_sqlite_table")
    if not source_path or not Path(source_path).exists():
        return
    try:
        from .map_view import load_classified_points

        try:
            points = load_classified_points(source_path, table_name)
        except Exception:
            points = load_source(source_path, table_name)
        points = add_region_column(points)
    except Exception as exc:
        st.warning(f"Filtros geográficos indisponíveis: {exc}")
        return

    region_column = detect_column(
        list(points.columns), ("macro_region", "regiao", "região", "region")
    )
    state_column = detect_column(
        list(points.columns), ("uf", "state", "estado", "sigla_uf")
    )
    municipality_column = detect_column(
        list(points.columns),
        ("municipio", "município", "municipality", "city", "location_name", "nome_localidade", "localidade"),
    )
    location_column = detect_column(
        list(points.columns), ("grid_id", "cell_id", "location_id", "id_celula")
    )
    if state_column is None and region_column is None:
        st.info("A fonte não possui campos geográficos reconhecíveis.")
        return

    st.subheader("Filtros geográficos")
    st.caption(
        "A seleção é compartilhada entre as páginas. Região limita as UFs; "
        "UF limita municípios e pontos do grid."
    )
    filter_columns = st.columns(4)
    region_options = ["Todas"]
    if region_column:
        region_options += sorted(
            str(value)
            for value in points[region_column].dropna().unique()
            if str(value).strip()
        )
    if st.session_state.get("global_region") not in region_options:
        st.session_state.global_region = "Todas"
    with filter_columns[0]:
        selected_region = st.selectbox(
            "Região", region_options, key="global_region"
        )

    regional_points = points
    if selected_region != "Todas" and region_column:
        regional_points = regional_points.loc[
            regional_points[region_column].astype(str).eq(selected_region)
        ]

    state_options = ["Todas"]
    if state_column:
        state_options += sorted(
            str(value).upper()
            for value in regional_points[state_column].dropna().unique()
            if str(value).strip()
        )
    if st.session_state.get("global_state") not in state_options:
        st.session_state.global_state = "Todas"
    with filter_columns[1]:
        selected_state = st.selectbox(
            "Unidade da Federação", state_options, key="global_state"
        )

    state_points = regional_points
    if selected_state != "Todas" and state_column:
        state_points = state_points.loc[
            state_points[state_column].astype(str).str.upper().eq(selected_state)
        ]

    municipality_options = ["Todos"]
    if municipality_column:
        municipality_options += sorted(
            str(value)
            for value in state_points[municipality_column].dropna().unique()
            if str(value).strip()
        )
    if st.session_state.get("global_municipality") not in municipality_options:
        st.session_state.global_municipality = "Todos"
    with filter_columns[2]:
        selected_municipality = st.selectbox(
            "Município", municipality_options, key="global_municipality"
        )

    location_points = state_points
    if selected_municipality != "Todos" and municipality_column:
        location_points = location_points.loc[
            location_points[municipality_column].astype(str).eq(
                selected_municipality
            )
        ]
    location_options = ["Todas"]
    if location_column:
        location_options += sorted(
            str(value)
            for value in location_points[location_column].dropna().unique()
            if str(value).strip()
        )
    if st.session_state.get("global_location") not in location_options:
        st.session_state.global_location = "Todas"
    with filter_columns[3]:
        st.selectbox(
            "Localidade / ponto do grid",
            location_options,
            key="global_location",
        )


def apply_theme() -> None:
    """Carrega os estilos compartilhados do dashboard."""
    stylesheet_path = (
        Path(__file__).resolve().parents[1] / "assets" / "styles.css"
    )
    stylesheet = stylesheet_path.read_text(encoding="utf-8")
    st.markdown(
        f"<style>\n{stylesheet}\n</style>",
        unsafe_allow_html=True,
    )


def render_source_sidebar() -> None:
    """Exibe os produtos do novo Data Lake na barra lateral."""
    gold_sources = _gold_sources()
    if not gold_sources:
        st.sidebar.error(
            "Não encontrei os produtos Gold em `SoilFrame-Dashboard-e-Dados/Base de dados`."
        )
        return
    default_gold_path = gold_sources.get(
        DEFAULT_GOLD_SOURCE, next(iter(gold_sources.values()))
    )
    ignored_legacy_path = False
    if "soilframe_source_path" not in st.session_state:
        configured_path = os.getenv("SOILFRAME_GOLD_PATH", "").strip()
        if configured_path and _is_legacy_lake_path(configured_path):
            configured_path = ""
            ignored_legacy_path = True
        st.session_state.soilframe_source_path = configured_path or default_gold_path
    elif _is_legacy_lake_path(st.session_state.soilframe_source_path):
        st.session_state.soilframe_source_path = default_gold_path
        ignored_legacy_path = True

    selectable_sources = [
        *gold_sources,
        "Personalizada · Parquet, CSV ou SQLite",
    ]
    if st.session_state.get("soilframe_gold_dataset") not in selectable_sources:
        configured_path = Path(st.session_state.soilframe_source_path).as_posix()
        matching_source = next(
            (
                name
                for name, path in gold_sources.items()
                if Path(path).as_posix() == configured_path
            ),
            selectable_sources[-1],
        )
        st.session_state.soilframe_gold_dataset = matching_source

    with st.sidebar:
        st.caption("Base de dados · camada Gold · somente leitura")
        if ignored_legacy_path:
            st.warning("O caminho do Lake antigo foi removido da seleção; usando o novo Data Lake.")
        st.selectbox(
            "Base Gold para análise",
            options=selectable_sources,
            key="soilframe_gold_dataset",
            on_change=_select_gold_source,
            help=(
                "Escolha um produto por modelo e frequência. Os produtos mantêm "
                "sua proveniência e cobertura discreta; eles não são combinados "
                "automaticamente."
            ),
        )
        st.text_input(
            "Caminho da fonte selecionada",
            key="soilframe_source_path",
            placeholder="C:/dados/gold/produto.csv",
            help=(
                "O caminho é atualizado ao escolher um produto acima. Aceita "
                "Parquet, CSV, uma pasta de CSVs Gold ou SQLite."
            ),
        )
        source_path = st.session_state.soilframe_source_path.strip()
        if source_path:
            source = Path(source_path)
            if source.exists() and not _is_legacy_lake_path(source_path):
                if source.is_dir():
                    count = len(csv_source_files(source))
                    if count:
                        st.caption(f"Coleção pronta: {count} arquivos CSV Gold")
                    else:
                        st.warning("A pasta não contém CSVs Gold reconhecidos.")
                else:
                    st.caption(f"Fonte pronta: {source.name}")
            elif _is_legacy_lake_path(source_path):
                st.warning("O Lake antigo não é mais aceito como fonte do dashboard.")
            else:
                st.warning("A fonte selecionada não foi encontrada neste computador.")
        if source_path and Path(source_path).suffix.casefold() in {
            ".db",
            ".sqlite",
            ".sqlite3",
        }:
            try:
                tables = list_sqlite_tables(source_path)
                if tables:
                    selected_table = st.session_state.get("soilframe_sqlite_table")
                    environment_table = os.getenv("SOILFRAME_GOLD_TABLE", "")
                    if selected_table not in tables:
                        st.session_state.soilframe_sqlite_table = (
                            environment_table
                            if environment_table in tables
                            else tables[0]
                        )
                    st.selectbox(
                        "Tabela Gold",
                        options=tables,
                        key="soilframe_sqlite_table",
                    )
                else:
                    st.warning("O banco não contém tabelas de usuário.")
            except Exception as exc:
                st.error(str(exc))
    with st.sidebar:
        st.divider()
        st.caption("Modelos e execuções são salvos em outputs.")


def load_configured_dataframe():
    """Carrega a fonte selecionada ou mostra uma orientação na página.

    Returns:
        DataFrame Gold, ou ``None`` se a fonte ainda não estiver configurada.
    """
    from .data_access import load_source

    source_path = st.session_state.get("soilframe_source_path", "").strip()
    if not source_path:
        st.info(
            "Escolha um produto Gold do novo Data Lake ou informe um caminho "
            "Parquet, CSV, pasta de CSVs ou banco SQLite na barra lateral."
        )
        return None
    sqlite_table = st.session_state.get("soilframe_sqlite_table")
    try:
        dataframe = load_source(source_path, sqlite_table)
        try:
            from .map_view import load_classified_points
            from .geography import apply_geographic_lookup

            classified_points = load_classified_points(source_path, sqlite_table)
            dataframe = apply_geographic_lookup(dataframe, classified_points)
        except Exception:
            # Bases sem coordenadas continuam utilizáveis pelos demais filtros.
            pass
        return dataframe
    except Exception as exc:
        st.error(f"Não foi possível carregar os dados: {exc}")
        return None


def page_header(title: str, subtitle: str) -> None:
    """Renderiza título e contexto da página atual."""
    st.title(title)
    st.caption(subtitle)


@st.cache_resource(show_spinner=False)
def get_job_manager(workspace: str):
    """Compartilha uma fila de treino e histórico entre sessões do app."""
    from .jobs import JobManager

    return JobManager(workspace)
