from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from ..core.dataset import Dataset
from .modelo_autogluon import ModeloAutoGluonTabular


class ModeloSolo(ModeloAutoGluonTabular):
    """Regressor AutoGluon para prever SWI a partir de dados agrometeorológicos."""

    name = "modelo_solo"
    version = "2.0.0"

    def __init__(
        self,
        alvo: str = "SWI_010",
        *,
        caminho_modelo: str | Path | None = None,
        data_uri: str | Path | None = None,
        sqlite_connection: sqlite3.Connection | None = None,
        sqlite_table: str | None = None,
        sqlite_query: str | None = None,
        limite_tempo: int = 300,
        preset: str = "medium_quality",
        **parameters: Any,
    ) -> None:
        """Configura um regressor AutoGluon para o Índice de Água no Solo.

        Args:
            alvo: Variável contínua de umidade; por padrão, ``SWI_010``.
            caminho_modelo: Pasta de armazenamento dos artefatos AutoGluon.
            data_uri: Caminho de Parquet ou SQLite da camada Gold.
            sqlite_connection: Conexão SQLite opcional já aberta.
            sqlite_table: Tabela Gold a consultar.
            sqlite_query: Consulta somente de leitura alternativa à tabela.
            limite_tempo: Limite de treinamento em segundos.
            preset: Preset de qualidade do AutoGluon.
            **parameters: Opções adicionais do adaptador tabular.
        """
        super().__init__(
            alvo=alvo,
            tipo_problema="regression",
            metrica="root_mean_squared_error",
            estrategia_validacao="temporal",
            limite_tempo=limite_tempo,
            preset=preset,
            caminho_modelo=caminho_modelo,
            data_uri=data_uri,
            sqlite_connection=sqlite_connection,
            sqlite_table=sqlite_table,
            sqlite_query=sqlite_query,
            **parameters,
        )

    def prever_sqlite(
        self,
        *,
        sqlite_connection: sqlite3.Connection | None = None,
        sqlite_table: str | None = None,
        sqlite_query: str | None = None,
    ) -> Dataset:
        """Carrega observações SQLite da camada Gold e prevê o SWI.

        Args:
            sqlite_connection: Conexão já aberta opcional.
            sqlite_table: Tabela a consultar, se diferente da configuração.
            sqlite_query: Consulta de leitura opcional.

        Returns:
            Dataset com dados carregados e a coluna ``previsao_{alvo}``.

        Raises:
            ValueError: Se não houver fonte ou consulta válida.
            RuntimeError: Se SQLite falhar ou o predictor não estiver disponível.
        """
        if self.estrategia is None:
            self.estrategia = self._criar_estrategia()
        frame: pd.DataFrame = self.estrategia.load_dataframe(
            sqlite_connection=sqlite_connection,
            sqlite_table=sqlite_table,
            sqlite_query=sqlite_query,
        )
        return self.prever(Dataset(frame, {"source": "sqlite", "layer": "gold"}))
