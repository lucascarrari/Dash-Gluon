from __future__ import annotations

from abc import ABC, abstractmethod
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import unquote, urlsplit

import pandas as pd

from .dataset import Dataset


AutoGluonTask = Literal["tabular", "timeseries"]
TabularProblemType = Literal["binary", "multiclass", "regression"]


class EstrategiaModelo(ABC):
    """Define o contrato Strategy para motores de treino e inferência."""

    @abstractmethod
    def fit(
        self,
        train_data: pd.DataFrame | Dataset | None = None,
        tuning_data: pd.DataFrame | Dataset | None = None,
    ) -> Self:
        """Treina o motor com dados de treino e, opcionalmente, ajuste.

        Args:
            train_data: Dados de treino ou ``None`` para carregar a fonte configurada.
            tuning_data: Dados opcionais de ajuste do AutoGluon.

        Returns:
            A própria estratégia treinada.
        """

    @abstractmethod
    def predict(
        self,
        data: pd.DataFrame | Dataset,
        known_covariates: pd.DataFrame | Dataset | None = None,
    ) -> pd.DataFrame:
        """Gera previsões usando dados tabulares ou históricos de séries temporais.

        Args:
            data: Features tabulares ou histórico da série.
            known_covariates: Covariáveis futuras conhecidas, quando aplicável.

        Returns:
            DataFrame com previsões do AutoGluon.
        """


class EstrategiaTransformacao(ABC):
    """Strategy opcional para limpeza e transformação de dados."""

    def limpar(self, dados: Any) -> Any:
        return dados

    @abstractmethod
    def transformar(self, dados: Any) -> Any:
        ...


class EstrategiaDownload(ABC):
    """Strategy abstrata para planejamento e otimização de download de dados."""

    @abstractmethod
    def planejar(self, **kwargs: Any) -> Any:
        """Gera um plano de download com alocação ótima e estimativa de volume."""
        ...

    @abstractmethod
    def estimar_volume(self, plano: Any) -> dict[str, Any]:
        """Calcula métricas de volume e economia do plano."""
        ...


class AutoGluonStrategy(EstrategiaModelo):
    """Strategy para AutoGluon TabularPredictor e TimeSeriesPredictor.

    ``data_uri`` aceita um arquivo Parquet local, um caminho SQLite ou uma URI
    ``sqlite:///...``. Para SQLite, informe ``sqlite_table`` ou uma consulta
    ``sqlite_query`` somente de leitura. Também é possível injetar uma conexão
    ``sqlite3.Connection`` já aberta.
    """

    def __init__(
        self,
        *,
        task_type: AutoGluonTask,
        target: str,
        path: str | Path,
        problem_type: TabularProblemType | None = None,
        eval_metric: str | None = None,
        presets: str = "medium_quality",
        time_limit: int = 300,
        num_cpus: int | str = "auto",
        num_gpus: int | str = 0,
        verbosity: int = 2,
        prediction_length: int = 7,
        item_id_column: str = "location_id",
        timestamp_column: str = "data",
        freq: str | None = "D",
        known_covariates_names: tuple[str, ...] = (),
        data_uri: str | Path | None = None,
        sqlite_connection: sqlite3.Connection | None = None,
        sqlite_table: str | None = None,
        sqlite_query: str | None = None,
    ) -> None:
        """Configura AutoGluon e uma fonte local opcional.

        Args:
            task_type: Tipo de predictor, ``tabular`` ou ``timeseries``.
            target: Coluna de saída a modelar.
            path: Diretório de artefatos do predictor.
            problem_type: Classificação ou regressão para tarefa Tabular.
            eval_metric: Métrica principal aceita pelo predictor selecionado.
            presets: Preset de qualidade do AutoGluon.
            time_limit: Tempo limite de treinamento em segundos.
            num_cpus: CPUs para treino Tabular.
            num_gpus: GPUs para treino Tabular.
            verbosity: Nível de saída do AutoGluon.
            prediction_length: Horizonte de previsão para TimeSeries.
            item_id_column: Coluna que identifica cada série.
            timestamp_column: Coluna temporal de cada observação.
            freq: Frequência temporal, como ``D`` para diário.
            known_covariates_names: Features futuras disponíveis no horizonte.
            data_uri: Arquivo Parquet ou banco SQLite local.
            sqlite_connection: Conexão SQLite já aberta, opcional.
            sqlite_table: Tabela Gold de origem.
            sqlite_query: Consulta SQLite somente de leitura.

        Raises:
            ValueError: Se a configuração da tarefa ou fonte for inválida.
        """
        if task_type not in {"tabular", "timeseries"}:
            raise ValueError("task_type deve ser 'tabular' ou 'timeseries'.")
        if not target.strip():
            raise ValueError("target não pode ser vazio.")
        if time_limit < 1:
            raise ValueError("time_limit deve ser um inteiro positivo.")
        if prediction_length < 1:
            raise ValueError("prediction_length deve ser um inteiro positivo.")
        if data_uri is not None and sqlite_connection is not None:
            raise ValueError("Informe data_uri ou sqlite_connection, não ambos.")

        self.task_type = task_type
        self.target = target
        self.path = Path(path).expanduser().resolve()
        self.problem_type = problem_type
        default_metric = (
            "root_mean_squared_error"
            if task_type == "tabular" and problem_type == "regression"
            else None
        )
        self.eval_metric = eval_metric or default_metric
        self.presets = presets
        self.time_limit = int(time_limit)
        self.num_cpus = num_cpus
        self.num_gpus = num_gpus
        self.verbosity = verbosity
        self.prediction_length = int(prediction_length)
        self.item_id_column = item_id_column
        self.timestamp_column = timestamp_column
        self.freq = freq
        self.known_covariates_names = tuple(known_covariates_names)
        self.data_uri = str(data_uri) if data_uri is not None else None
        self.sqlite_connection = sqlite_connection
        self.sqlite_table = sqlite_table
        self.sqlite_query = sqlite_query
        self.predictor: Any = None
        self._diagnostic_data: pd.DataFrame | None = None
        self._leaderboard = pd.DataFrame()

    @staticmethod
    def _as_frame(data: pd.DataFrame | Dataset) -> pd.DataFrame:
        """Converte uma entrada SoilFrame em cópia independente de DataFrame."""
        frame = data.data if isinstance(data, Dataset) else data
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(
                "AutoGluonStrategy exige pandas.DataFrame ou Dataset tabular."
            )
        return frame.copy()

    @staticmethod
    def _sqlite_path(source_uri: str | Path) -> tuple[str, bool]:
        """Converte caminho ou URI SQLite em URI local somente leitura."""
        source = str(source_uri)
        if source.startswith("file:"):
            return source, True
        if source.startswith("sqlite:///"):
            parsed = urlsplit(source)
            raw_path = unquote(parsed.path)
            if re.match(r"^/[A-Za-z]:/", raw_path):
                raw_path = raw_path[1:]
            if not raw_path:
                raise ValueError("A URI SQLite precisa apontar para um arquivo local.")
            path = Path(raw_path).expanduser().resolve()
            query = parsed.query or "mode=ro"
            return f"{path.as_uri()}?{query}", True
        path = Path(source).expanduser().resolve()
        if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
            raise ValueError("A fonte não é Parquet nem um arquivo SQLite reconhecido.")
        return f"{path.as_uri()}?mode=ro", True

    @staticmethod
    def _select_sql(table: str | None, query: str | None) -> str:
        """Valida e constrói uma consulta SQLite de leitura."""
        if query is not None:
            statement = query.strip()
            if not re.match(r"^(select|with)\b", statement, flags=re.IGNORECASE):
                raise ValueError(
                    "sqlite_query aceita apenas SELECT ou WITH ... SELECT."
                )
            return statement
        if table is None or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError("Informe sqlite_table válida ou sqlite_query de leitura.")
        return f'SELECT * FROM "{table}"'

    def load_dataframe(
        self,
        source_uri: str | Path | None = None,
        *,
        sqlite_connection: sqlite3.Connection | None = None,
        sqlite_table: str | None = None,
        sqlite_query: str | None = None,
    ) -> pd.DataFrame:
        """Carrega uma tabela Gold Parquet ou SQLite para um DataFrame.

        Args:
            source_uri: Caminho do arquivo ou URI SQLite opcional.
            sqlite_connection: Conexão aberta, se já disponível.
            sqlite_table: Nome da tabela SQLite a consultar.
            sqlite_query: Consulta somente de leitura, alternativa ao nome da tabela.

        Returns:
            Dados carregados em um DataFrame Pandas.

        Raises:
            ValueError: Se a fonte ou consulta não estiver configurada corretamente.
            RuntimeError: Se o arquivo ou banco não puder ser lido.
        """
        selected_source = str(source_uri) if source_uri is not None else self.data_uri
        selected_connection = sqlite_connection
        if selected_connection is None:
            selected_connection = self.sqlite_connection
        selected_table = sqlite_table or self.sqlite_table
        selected_query = sqlite_query or self.sqlite_query

        if selected_connection is not None:
            statement = self._select_sql(selected_table, selected_query)
            try:
                return pd.read_sql_query(statement, selected_connection)
            except Exception as exc:
                raise RuntimeError(
                    "Falha ao ler a tabela Gold pela conexão SQLite."
                ) from exc
        if selected_source is None:
            raise ValueError(
                "Informe data_uri ou sqlite_connection para carregar os dados."
            )

        source_path = selected_source
        if selected_source.startswith("file://"):
            parsed = urlsplit(selected_source)
            source_path = unquote(parsed.path)
            if re.match(r"^/[A-Za-z]:/", source_path):
                source_path = source_path[1:]
        suffix = Path(urlsplit(str(source_path)).path).suffix.casefold()
        if suffix == ".parquet":
            try:
                return pd.read_parquet(source_path, engine="pyarrow")
            except Exception as exc:
                raise RuntimeError(
                    f"Falha ao ler o arquivo Parquet {source_path!r}."
                ) from exc

        connection_uri, use_uri = self._sqlite_path(selected_source)
        statement = self._select_sql(selected_table, selected_query)
        connection = sqlite3.connect(connection_uri, uri=use_uri, timeout=30.0)
        try:
            return pd.read_sql_query(statement, connection)
        except Exception as exc:
            raise RuntimeError(
                f"Falha ao ler a fonte SQLite {selected_source!r}."
            ) from exc
        finally:
            connection.close()

    def _prepare_tabular_frame(self, data: pd.DataFrame | Dataset) -> pd.DataFrame:
        """Valida alvo e normaliza valores tabulares para o predictor."""
        frame = self._as_frame(data)
        if self.target not in frame.columns:
            raise ValueError(f"A coluna-alvo {self.target!r} não existe no DataFrame.")
        frame = frame.loc[frame[self.target].notna()].copy()
        if frame.empty:
            raise ValueError(
                f"A coluna-alvo {self.target!r} não contém valores válidos."
            )
        if self.problem_type == "regression":
            frame[self.target] = pd.to_numeric(frame[self.target], errors="raise")
        return frame

    def _prepare_timeseries_frame(
        self,
        data: pd.DataFrame | Dataset,
    ) -> tuple[pd.DataFrame, Any]:
        """Valida séries e converte os dados para TimeSeriesDataFrame."""
        frame = self._as_frame(data)
        required = {self.item_id_column, self.timestamp_column, self.target}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(
                f"Colunas obrigatórias para TimeSeries ausentes: {sorted(missing)}."
            )
        frame[self.timestamp_column] = pd.to_datetime(
            frame[self.timestamp_column], errors="coerce"
        )
        frame = frame.dropna(
            subset=[self.item_id_column, self.timestamp_column, self.target]
        ).copy()
        frame[self.target] = pd.to_numeric(frame[self.target], errors="raise")
        if frame.empty:
            raise ValueError(
                "Não há observações completas para treinar a série temporal."
            )
        if frame.duplicated([self.item_id_column, self.timestamp_column]).any():
            raise ValueError(
                "Cada série precisa ter uma observação única por timestamp."
            )
        try:
            from autogluon.timeseries import TimeSeriesDataFrame
        except ImportError as exc:
            raise ImportError(
                "TimeSeriesPredictor não está instalado; instale o extra "
                "AutoGluon TimeSeries compatível."
            ) from exc
        time_series_frame = TimeSeriesDataFrame.from_data_frame(
            frame,
            id_column=self.item_id_column,
            timestamp_column=self.timestamp_column,
        )
        return frame, time_series_frame

    def fit(
        self,
        train_data: pd.DataFrame | Dataset | None = None,
        tuning_data: pd.DataFrame | Dataset | None = None,
    ) -> Self:
        """Inicializa e treina TabularPredictor ou TimeSeriesPredictor.

        Args:
            train_data: Dados de treino ou ``None`` para carregar a fonte Gold.
            tuning_data: Conjunto opcional de ajuste do AutoGluon.

        Returns:
            A estratégia treinada.

        Raises:
            ImportError: Se o componente AutoGluon selecionado não estiver instalado.
            RuntimeError: Se inicialização ou treino do predictor falhar.
        """
        source = train_data if train_data is not None else self.load_dataframe()
        if self.task_type == "tabular":
            try:
                from autogluon.tabular import TabularPredictor
            except ImportError as exc:
                raise ImportError(
                    "TabularPredictor não está instalado; instale o extra "
                    "AutoGluon Tabular."
                ) from exc
            train_frame = self._prepare_tabular_frame(source)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.predictor = TabularPredictor(
                    label=self.target,
                    problem_type=self.problem_type,
                    eval_metric=self.eval_metric,
                    path=str(self.path),
                    verbosity=self.verbosity,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Não foi possível inicializar o TabularPredictor."
                ) from exc
            fit_options: dict[str, Any] = {
                "train_data": train_frame,
                "presets": self.presets,
                "time_limit": self.time_limit,
                "num_cpus": self.num_cpus,
                "num_gpus": self.num_gpus,
            }
            if tuning_data is not None:
                fit_options["tuning_data"] = self._prepare_tabular_frame(tuning_data)
            try:
                self.predictor.fit(**fit_options)
            except Exception as exc:
                raise RuntimeError("O treinamento do TabularPredictor falhou.") from exc
        else:
            try:
                from autogluon.timeseries import TimeSeriesPredictor
            except ImportError as exc:
                raise ImportError(
                    "TimeSeriesPredictor não está instalado; instale o extra "
                    "AutoGluon TimeSeries."
                ) from exc
            train_frame, train_series = self._prepare_timeseries_frame(source)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            predictor_options: dict[str, Any] = {
                "target": self.target,
                "prediction_length": self.prediction_length,
                "path": str(self.path),
                "eval_metric": self.eval_metric or "WQL",
                "verbosity": self.verbosity,
            }
            if self.known_covariates_names:
                predictor_options["known_covariates_names"] = list(
                    self.known_covariates_names
                )
            if self.freq is not None:
                predictor_options["freq"] = self.freq
            try:
                self.predictor = TimeSeriesPredictor(**predictor_options)
            except Exception as exc:
                raise RuntimeError(
                    "Não foi possível inicializar o TimeSeriesPredictor."
                ) from exc
            fit_options = {
                "train_data": train_series,
                "presets": self.presets,
                "time_limit": self.time_limit,
            }
            if tuning_data is not None:
                _, tuning_series = self._prepare_timeseries_frame(tuning_data)
                fit_options["tuning_data"] = tuning_series
            try:
                self.predictor.fit(**fit_options)
            except Exception as exc:
                raise RuntimeError(
                    "O treinamento do TimeSeriesPredictor falhou."
                ) from exc
            self._diagnostic_data = train_frame

        self._leaderboard = self.leaderboard()
        return self

    def predict(
        self,
        data: pd.DataFrame | Dataset,
        known_covariates: pd.DataFrame | Dataset | None = None,
    ) -> pd.DataFrame:
        """Gera inferências tabulares ou previsões para o horizonte temporal.

        Args:
            data: Features de inferência ou histórico das séries.
            known_covariates: Covariáveis futuras conhecidas para TimeSeries.

        Returns:
            DataFrame com previsões e, para séries, os índices temporais.
        """
        if self.predictor is None:
            self.load_predictor()
        if self.task_type == "tabular":
            frame = self._as_frame(data)
            features = frame.drop(columns=[self.target], errors="ignore")
            predictions = self.predictor.predict(features)
            return predictions.rename(f"previsao_{self.target}").to_frame()

        _, time_series_frame = self._prepare_timeseries_frame(data)
        covariates = None
        if known_covariates is not None:
            covariate_frame = self._as_frame(known_covariates)
            required = {
                self.item_id_column,
                self.timestamp_column,
                *self.known_covariates_names,
            }
            missing = required.difference(covariate_frame.columns)
            if missing:
                raise ValueError(f"Covariáveis futuras ausentes: {sorted(missing)}.")
            covariate_frame[self.timestamp_column] = pd.to_datetime(
                covariate_frame[self.timestamp_column], errors="coerce"
            )
            covariate_keys = covariate_frame[
                [self.item_id_column, self.timestamp_column]
            ]
            if covariate_keys.isna().any().any():
                raise ValueError(
                    "IDs e timestamps das covariáveis futuras não podem ser nulos."
                )
            from autogluon.timeseries import TimeSeriesDataFrame

            covariates = TimeSeriesDataFrame.from_data_frame(
                covariate_frame,
                id_column=self.item_id_column,
                timestamp_column=self.timestamp_column,
            )
        forecast = self.predictor.predict(
            time_series_frame,
            known_covariates=covariates,
        )
        return forecast.reset_index()

    def leaderboard(self, data: pd.DataFrame | Dataset | None = None) -> pd.DataFrame:
        """Retorna o ranking AutoGluon para o conjunto de avaliação informado.

        Args:
            data: Dados de avaliação; usa os dados diagnósticos se omitidos.

        Returns:
            Cópia do leaderboard em formato DataFrame.
        """
        if self.predictor is None:
            raise RuntimeError(
                "Treine ou carregue o AutoGluonStrategy antes do leaderboard."
            )
        evaluation_data = data if data is not None else self._diagnostic_data
        if self.task_type == "tabular":
            if evaluation_data is None:
                result = self.predictor.leaderboard(silent=True)
            else:
                result = self.predictor.leaderboard(
                    self._prepare_tabular_frame(evaluation_data),
                    silent=True,
                )
        else:
            if evaluation_data is None:
                result = self.predictor.leaderboard(display=False)
            else:
                _, series_data = self._prepare_timeseries_frame(evaluation_data)
                result = self.predictor.leaderboard(series_data, display=False)
        self._leaderboard = result.copy()
        return self._leaderboard.copy()

    def feature_importance(
        self,
        data: pd.DataFrame | Dataset | None = None,
        *,
        time_limit: int = 60,
        subsample_size: int = 500,
        num_iterations: int = 1,
    ) -> pd.DataFrame:
        """Calcula importância das features para a tarefa configurada.

        Args:
            data: Dados de avaliação opcionais.
            time_limit: Limite de execução para importância Tabular, em segundos.
            subsample_size: Tamanho máximo da amostra Tabular.
            num_iterations: Número de permutações ou iterações.

        Returns:
            Importância das features em DataFrame.
        """
        if self.predictor is None:
            raise RuntimeError(
                "Treine ou carregue o AutoGluonStrategy antes da importância."
            )
        evaluation_data = data if data is not None else self._diagnostic_data
        options: dict[str, Any] = {}
        if self.task_type == "tabular":
            options["time_limit"] = time_limit
            if evaluation_data is not None:
                options["data"] = self._prepare_tabular_frame(evaluation_data)
                options["subsample_size"] = subsample_size
            options["num_shuffle_sets"] = num_iterations
        else:
            if evaluation_data is not None:
                _, series_data = self._prepare_timeseries_frame(evaluation_data)
                options["data"] = series_data
            options["num_iterations"] = num_iterations
        result = self.predictor.feature_importance(**options)
        return result.copy()

    def set_diagnostic_data(self, data: pd.DataFrame | Dataset | None) -> None:
        """Define dados de validação para relatórios do rastreador.

        Args:
            data: Conjunto reservado ou ``None`` para limpar os diagnósticos.
        """
        self._diagnostic_data = self._as_frame(data) if data is not None else None

    def load_predictor(self, path: str | Path | None = None) -> Self:
        """Carrega o predictor salvo pelo AutoGluon.

        Args:
            path: Pasta de artefatos; usa ``self.path`` se omitida.

        Returns:
            A estratégia com o predictor carregado.

        Raises:
            FileNotFoundError: Se a pasta do modelo não existir.
            ImportError: Se o módulo AutoGluon necessário não estiver instalado.
            RuntimeError: Se o artefato não puder ser carregado.
        """
        predictor_path = (
            Path(path).expanduser().resolve() if path is not None else self.path
        )
        if not predictor_path.exists():
            raise FileNotFoundError(
                f"Diretório do predictor AutoGluon não existe: {predictor_path}"
            )
        if self.task_type == "tabular":
            try:
                from autogluon.tabular import TabularPredictor
            except ImportError as exc:
                raise ImportError("TabularPredictor não está instalado.") from exc
            try:
                self.predictor = TabularPredictor.load(
                    str(predictor_path), require_version_match=False
                )
            except Exception as exc:
                raise RuntimeError(
                    "Não foi possível carregar o TabularPredictor salvo."
                ) from exc
        else:
            try:
                from autogluon.timeseries import TimeSeriesPredictor
            except ImportError as exc:
                raise ImportError("TimeSeriesPredictor não está instalado.") from exc
            try:
                self.predictor = TimeSeriesPredictor.load(
                    str(predictor_path), require_version_match=False
                )
            except Exception as exc:
                raise RuntimeError(
                    "Não foi possível carregar o TimeSeriesPredictor salvo."
                ) from exc
        self.path = predictor_path
        return self

    def __getstate__(self) -> dict[str, Any]:
        """Evita duplicar o predictor e conexões ao serializar o modelo SoilFrame."""
        state = self.__dict__.copy()
        state["predictor"] = None
        state["sqlite_connection"] = None
        state["_diagnostic_data"] = None
        state["_leaderboard"] = pd.DataFrame()
        return state

