"""Acesso local e somente leitura aos arquivos Gold do Data Lake."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


MAX_SOURCE_ROWS = 250_000
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
CSV_SUFFIXES = {".csv"}


def csv_source_files(source: Path) -> list[Path]:
    """Retorna arquivos CSV de uma fonte Gold (arquivo ou coleção local)."""
    if source.is_file() and source.suffix.casefold() in CSV_SUFFIXES:
        return [source]
    if source.is_dir():
        return [
            path
            for path in sorted(source.glob("*.csv"))
            if not path.stem.casefold().startswith(("coverage", "cobertura"))
        ]
    return []


def csv_separator(path: Path) -> str:
    """Detecta o separador usado nos CSVs Gold do Data Lake."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        header = stream.readline()
    return ";" if header.count(";") > header.count(",") else ","


@st.cache_data(ttl=30, max_entries=8, show_spinner=False)
def list_sqlite_tables(database_path: str) -> list[str]:
    """Lista tabelas de um banco local sem permitir escrita.

    Args:
        database_path: Caminho local para arquivo SQLite.

    Returns:
        Nomes das tabelas existentes.

    Raises:
        FileNotFoundError: Se o arquivo do banco não existir.
        RuntimeError: Se o arquivo não puder ser aberto como SQLite.
    """
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Banco SQLite não encontrado: {path}")
    if path.suffix.casefold() not in SQLITE_SUFFIXES:
        raise ValueError("Selecione um arquivo .db, .sqlite ou .sqlite3.")

    connection_uri = f"file:{path.as_posix()}?mode=ro"
    connection = None
    try:
        connection = sqlite3.connect(connection_uri, uri=True, timeout=10)
        with connection:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Não foi possível consultar o SQLite: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
    return [str(row[0]) for row in rows]


@st.cache_data(ttl=30, max_entries=8, show_spinner=False)
def load_source(
    source_path: str,
    table_name: str | None = None,
    row_limit: int = MAX_SOURCE_ROWS,
) -> pd.DataFrame:
    """Lê Parquet, CSV/coleção CSV ou tabela SQLite Gold para Pandas.

    Args:
        source_path: Caminho local para Parquet, CSV, coleção de CSVs ou SQLite.
        table_name: Tabela a ler quando a fonte é SQLite.
        row_limit: Limite de linhas para proteger a interface local.

    Returns:
        DataFrame com os registros carregados.

    Raises:
        FileNotFoundError: Se a fonte não existir.
        ValueError: Se a extensão, tabela ou limite forem inválidos.
        RuntimeError: Se a fonte não puder ser lida.
    """
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Fonte Gold não encontrada: {path}")
    if row_limit < 1:
        raise ValueError("row_limit precisa ser maior que zero.")

    suffix = path.suffix.casefold()
    try:
        if suffix == ".parquet":
            return pd.read_parquet(path, engine="pyarrow").head(row_limit)
        csv_files = csv_source_files(path)
        if csv_files:
            frames: list[pd.DataFrame] = []
            remaining = row_limit
            for csv_path in csv_files:
                frame = pd.read_csv(
                    csv_path,
                    sep=csv_separator(csv_path),
                    nrows=remaining,
                )
                frames.append(frame)
                remaining -= len(frame)
                if remaining <= 0:
                    break
            if not frames:
                raise ValueError("A fonte CSV não contém linhas de dados.")
            return pd.concat(frames, ignore_index=True).head(row_limit)
        if suffix in SQLITE_SUFFIXES:
            if not table_name:
                raise ValueError("Selecione uma tabela SQLite para carregar os dados.")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
                raise ValueError("O nome da tabela SQLite contém caracteres inválidos.")
            connection_uri = f"file:{path.as_posix()}?mode=ro"
            connection = sqlite3.connect(connection_uri, uri=True, timeout=30)
            try:
                with connection:
                    connection.execute("PRAGMA query_only = ON")
                    quoted_table = f'"{table_name}"'
                    return pd.read_sql_query(
                        f"SELECT * FROM {quoted_table} LIMIT ?",
                        connection,
                        params=(row_limit,),
                    )
            finally:
                connection.close()
    except (ValueError, FileNotFoundError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Falha ao ler a fonte Gold {path}: {exc}") from exc

    raise ValueError(
        "Formato não suportado. Informe Parquet, CSV, coleção de CSVs ou SQLite."
    )


def detect_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    """Retorna a primeira coluna que corresponde a uma lista de aliases.

    Args:
        columns: Colunas encontradas nos dados.
        candidates: Nomes alternativos em ordem de preferência.

    Returns:
        Nome da coluna encontrada ou ``None``.
    """
    normalized = {column.casefold(): column for column in columns}
    return next(
        (normalized[candidate.casefold()] for candidate in candidates
         if candidate.casefold() in normalized),
        None,
    )


def dataframe_schema(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Resume tipo, preenchimento e cardinalidade das colunas.

    Args:
        dataframe: Dados exibidos no dashboard.

    Returns:
        DataFrame descritivo do esquema observado.
    """
    rows: list[dict[str, Any]] = []
    for column in dataframe.columns:
        series = dataframe[column]
        rows.append(
            {
                "Coluna": column,
                "Tipo": str(series.dtype),
                "Valores preenchidos": int(series.notna().sum()),
                "Nulos": int(series.isna().sum()),
                "Valores únicos": int(series.nunique(dropna=True)),
            }
        )
    return pd.DataFrame(rows)
