from __future__ import annotations

import json
import pickle
import shutil
import time
from pathlib import Path
from typing import Any, ClassVar, Literal

import pandas as pd

from ..core.dataset import Dataset
from ..core.metrics import Metricas
from ..core.model import Model
from ..core.strategy import AutoGluonStrategy

ProblemType = Literal["binary", "multiclass", "regression"]


class ModeloAutoGluonTabular(Model):
    """Adapta o AutoGluon Tabular ao contrato de modelos do SoilFrame.

    O adaptador prepara conjuntos de treino e validação, delega treino e
    inferência à estratégia injetada e mantém métricas e artefatos do experimento.
    """

    name: ClassVar[str] = "modelo_automl_autogluon"
    version: ClassVar[str] = "1.0.0"

    def __init__(
        self,
        alvo: str,
        tipo_problema: ProblemType = "multiclass",
        metrica: str | None = None,
        estrategia_validacao: str = "temporal",
        limite_tempo: int = 300,
        preset: str = "medium_quality",
        caminho_modelo: str | Path | None = None,
        random_state: int = 42,
        data_uri: str | Path | None = None,
        sqlite_connection: Any = None,
        sqlite_table: str | None = None,
        sqlite_query: str | None = None,
        strategy: AutoGluonStrategy | None = None,
        tracker: Any = None,
        **parameters: Any,
    ) -> None:
        """Configura parâmetros de treino, fonte e rastreamento.

        Args:
            alvo: Coluna a prever.
            tipo_problema: Tipo de classificação ou regressão.
            metrica: Métrica principal do AutoGluon.
            estrategia_validacao: ``temporal`` ou ``localidade``.
            limite_tempo: Tempo máximo de treino em segundos.
            preset: Preset de qualidade do AutoGluon.
            caminho_modelo: Pasta para os artefatos do predictor.
            random_state: Semente da divisão por localidade.
            data_uri: Arquivo Parquet ou banco SQLite Gold.
            sqlite_connection: Conexão SQLite opcional já aberta.
            sqlite_table: Tabela SQLite de origem.
            sqlite_query: Consulta SQLite somente de leitura.
            strategy: Estratégia AutoGluon injetada opcionalmente.
            tracker: Rastreador chamado após o treino.
            **parameters: Parâmetros adicionais do contrato Model.

        Raises:
            ValueError: Se parâmetros necessários forem inválidos.
        """
        if tipo_problema not in {"binary", "multiclass", "regression"}:
            raise ValueError(
                "tipo_problema deve ser binary, multiclass ou regression."
            )
        if limite_tempo < 1:
            raise ValueError("limite_tempo deve ser positivo.")
        if not alvo.strip():
            raise ValueError("alvo não pode ser vazio.")

        super().__init__(**parameters)
        self.alvo = alvo
        self.target = alvo
        self.tipo_problema = tipo_problema
        self.metrica = metrica or self._metrica_padrao(tipo_problema)
        self.estrategia_validacao = estrategia_validacao
        self.limite_tempo = int(limite_tempo)
        self.preset = preset
        self.caminho_modelo = Path(caminho_modelo).resolve() if caminho_modelo else None
        self.random_state = int(random_state)
        self.melhor_modelo: Any = None
        self.caminho_predictor: str | None = None
        self.leaderboard_df = pd.DataFrame()
        self.predicoes_teste = pd.DataFrame()
        self.metricas_teste: dict[str, Any] = {}
        self.colunas_treino: list[str] = []
        self.data_uri = data_uri
        self.sqlite_connection = sqlite_connection
        self.sqlite_table = sqlite_table
        self.sqlite_query = sqlite_query
        self.estrategia = strategy
        if tracker is not None:
            self.tracker = tracker

    @staticmethod
    def _metrica_padrao(tipo_problema: ProblemType) -> str:
        """Escolhe métrica padrão para regressão ou classificação."""
        return (
            "root_mean_squared_error"
            if tipo_problema == "regression"
            else "f1_macro"
        )

    @staticmethod
    def _obter_dataframe(entrada: Any) -> pd.DataFrame:
        """Extrai dados tabulares de Dataset, fonte ou pipeline SoilFrame.

        Args:
            entrada: DataFrame, Dataset, fonte com ``dataset`` ou pipeline
                com ``rodar``.

        Returns:
            Cópia dos dados como DataFrame.

        Raises:
            TypeError: Se a entrada não fornecer dados tabulares.
        """
        if isinstance(entrada, Dataset):
            return entrada.data.copy()
        if isinstance(entrada, pd.DataFrame):
            return entrada.copy()
        if hasattr(entrada, "dataset"):
            dados = entrada.dataset()
            return dados.data.copy() if isinstance(dados, Dataset) else dados.copy()
        if hasattr(entrada, "rodar"):
            dados = entrada.rodar()
            return dados.data.copy() if isinstance(dados, Dataset) else dados.copy()
        raise TypeError(
            "O AutoGluon SoilFrame espera Dataset, DataFrame ou "
            "uma fonte/pipeline compatível."
        )

    def _separar_treino_teste(
        self,
        frame: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Divide os dados sem misturar datas ou localidades entre conjuntos.

        Args:
            frame: Dados preparados que incluem a coluna-alvo.

        Returns:
            Tupla com conjuntos de treino e teste.

        Raises:
            ValueError: Se alvo, classes, datas ou grupos forem insuficientes.
        """
        if self.alvo not in frame.columns:
            raise ValueError(
                f"A coluna-alvo {self.alvo!r} não existe nos dados selecionados."
            )

        dados = frame.loc[frame[self.alvo].notna()].copy()
        if len(dados) < 20:
            raise ValueError(
                "São necessários pelo menos 20 registros com alvo preenchido "
                "para treinar."
            )

        if self.tipo_problema not in {"binary", "multiclass", "regression"}:
            raise ValueError("tipo_problema deve ser binary, multiclass ou regression.")
        if self.tipo_problema == "regression":
            dados[self.alvo] = pd.to_numeric(dados[self.alvo], errors="coerce")
            dados = dados.loc[dados[self.alvo].notna()].copy()
        else:
            dados[self.alvo] = dados[self.alvo].astype(str)
            classes = dados[self.alvo].nunique()
            if self.tipo_problema == "binary" and classes != 2:
                raise ValueError(
                    "Classificação binária requer 2 classes; foram encontradas "
                    f"{classes}."
                )
            if self.tipo_problema == "multiclass" and classes < 2:
                raise ValueError(
                    "Classificação multiclasse requer pelo menos 2 classes."
                )

        if self.estrategia_validacao == "temporal":
            if "data" not in dados.columns:
                raise ValueError(
                    "Validação temporal requer uma coluna 'data' no dataset."
                )
            dados["data"] = pd.to_datetime(dados["data"], errors="coerce")
            dados = dados.loc[dados["data"].notna()].sort_values("data").copy()
            datas = dados["data"].drop_duplicates().sort_values().to_list()
            if len(datas) < 2:
                raise ValueError(
                    "Validação temporal requer pelo menos duas datas distintas."
                )
            corte = max(1, min(len(datas) - 1, int(len(datas) * 0.8)))
            data_teste = datas[corte]
            treino = dados.loc[dados["data"] < data_teste].copy()
            teste = dados.loc[dados["data"] >= data_teste].copy()
        elif self.estrategia_validacao == "localidade":
            grupo = (
                "location_id"
                if "location_id" in dados.columns
                else "cell_id" if "cell_id" in dados.columns else None
            )
            if grupo is None:
                raise ValueError(
                    "Validação por localidade requer location_id ou cell_id."
                )
            grupos = dados[grupo].dropna().drop_duplicates().to_numpy()
            if len(grupos) < 2:
                raise ValueError(
                    "Validação por localidade requer pelo menos duas localidades."
                )
            n_teste = max(1, min(len(grupos) - 1, round(len(grupos) * 0.2)))
            grupos_teste = set(
                pd.Series(grupos)
                .sample(n=n_teste, random_state=self.random_state)
                .tolist()
            )
            teste = dados.loc[dados[grupo].isin(grupos_teste)].copy()
            treino = dados.loc[~dados[grupo].isin(grupos_teste)].copy()
        else:
            raise ValueError("estrategia_validacao deve ser temporal ou localidade.")

        if treino.empty or teste.empty:
            raise ValueError(
                "A separação produziu treino ou teste vazio; revise os dados "
                "e a validação escolhida."
            )
        return treino, teste

    def treinar(
        self,
        pipeline: Any,
        parameters: dict[str, Any] | None = None,
    ) -> "ModeloAutoGluonTabular":
        """Treina o AutoGluon e registra métricas de validação.

        Args:
            pipeline: Dataset, DataFrame, pipeline ou ``None`` para ler a fonte Gold.
            parameters: Sobrescritas pontuais de configuração.

        Returns:
            O próprio modelo treinado.

        Raises:
            ValueError: Se a fonte, o alvo ou a divisão de dados forem inválidos.
            RuntimeError: Se o treino do AutoGluon falhar.
        """
        options = {**self.parameters, **(parameters or {})}
        self.alvo = str(options.get("alvo", self.alvo))
        self.target = self.alvo
        self.tipo_problema = str(options.get("tipo_problema", self.tipo_problema))
        self.metrica = str(options.get("metrica", self.metrica))
        self.estrategia_validacao = str(
            options.get("estrategia_validacao", self.estrategia_validacao)
        )
        self.limite_tempo = int(options.get("limite_tempo", self.limite_tempo))
        self.preset = str(options.get("preset", self.preset))
        output_path = options.get("caminho_modelo", self.caminho_modelo)
        if not output_path:
            raise ValueError(
                "Informe caminho_modelo para armazenar os artefatos AutoGluon."
            )
        self.caminho_modelo = Path(output_path).resolve()

        self.data_uri = options.get("data_uri", self.data_uri)
        self.sqlite_connection = options.get(
            "sqlite_connection",
            self.sqlite_connection,
        )
        self.sqlite_table = options.get("sqlite_table", self.sqlite_table)
        self.sqlite_query = options.get("sqlite_query", self.sqlite_query)
        if pipeline is None:
            if self.estrategia is None:
                self.estrategia = self._criar_estrategia()
            entrada = self.estrategia.load_dataframe()
        else:
            entrada = (
                pipeline
                if isinstance(pipeline, Dataset)
                else self._obter_dataframe(pipeline)
            )
        frame = entrada.data.copy() if isinstance(entrada, Dataset) else entrada
        treino, teste = self._separar_treino_teste(frame)
        self.colunas_treino = list(treino.columns)

        self.caminho_modelo.mkdir(parents=True, exist_ok=True)
        started_at = time.perf_counter()
        self.estrategia = self._criar_estrategia()
        try:
            self.estrategia.fit(treino)
        except Exception as exc:
            raise RuntimeError(
                "Falha durante o treinamento do modelo SoilFrame."
            ) from exc
        self.estrategia.set_diagnostic_data(teste)
        self.melhor_modelo = self.estrategia.predictor
        elapsed = time.perf_counter() - started_at

        features_teste = teste.drop(columns=[self.alvo])
        predictions = self.estrategia.predict(features_teste)[f"previsao_{self.alvo}"]
        self.metricas_teste = self._calcular_metricas(teste[self.alvo], predictions)
        colunas_contexto = [
            coluna
            for coluna in (
                "data",
                "location_id",
                "location_name",
                "state",
                "latitude",
                "longitude",
                self.alvo,
            )
            if coluna in teste.columns
        ]
        self.predicoes_teste = teste[colunas_contexto].copy().reset_index(drop=True)
        self.predicoes_teste[f"previsao_{self.alvo}"] = predictions.to_numpy()
        self.metricas_teste.update(
            {
                "rows_train": int(len(treino)),
                "rows_test": int(len(teste)),
                "training_seconds": round(elapsed, 2),
                "target": self.alvo,
                "problem_type": self.tipo_problema,
                "validation_strategy": self.estrategia_validacao,
                "primary_metric": self.metrica,
                "test_start_date": (
                    str(teste["data"].min()) if "data" in teste.columns else None
                ),
                "test_end_date": (
                    str(teste["data"].max()) if "data" in teste.columns else None
                ),
            }
        )

        leaderboard = self.estrategia.leaderboard(teste)
        self.leaderboard_df = leaderboard.head(20).reset_index(drop=True)
        self.caminho_predictor = str(self.caminho_modelo)
        if self.tracker is not None:
            from ..core.metrics import Metricas

            self.tracker.registrar_modelo(
                self,
                pipeline if pipeline is not None else self,
                Metricas(dict(self.metricas_teste)),
            )
        return self

    def _criar_estrategia(self) -> AutoGluonStrategy:
        """Retorna a estratégia injetada ou cria uma Tabular para este modelo."""
        if self.estrategia is not None:
            if (
                self.estrategia.task_type != "tabular"
                or self.estrategia.target != self.alvo
            ):
                raise ValueError(
                    "A estratégia injetada deve ser tabular e usar o mesmo "
                    "alvo do modelo."
                )
            return self.estrategia
        if self.caminho_modelo is None:
            raise ValueError(
                "Informe caminho_modelo para armazenar os artefatos AutoGluon."
            )
        return AutoGluonStrategy(
            task_type="tabular",
            target=self.alvo,
            problem_type=self.tipo_problema,
            eval_metric=self.metrica,
            path=self.caminho_modelo,
            presets=self.preset,
            time_limit=self.limite_tempo,
            num_gpus=0,
            verbosity=1,
            data_uri=self.data_uri,
            sqlite_connection=self.sqlite_connection,
            sqlite_table=self.sqlite_table,
            sqlite_query=self.sqlite_query,
        )

    def _calcular_metricas(
        self,
        y_real: pd.Series,
        y_previsto: pd.Series,
    ) -> dict[str, float]:
        """Calcula métricas adequadas ao problema de modelagem.

        Args:
            y_real: Valores observados no conjunto de teste.
            y_previsto: Valores previstos pelo AutoGluon.

        Returns:
            Métricas numéricas de regressão ou classificação.
        """
        from sklearn.metrics import (
            accuracy_score,
            f1_score,
            mean_absolute_error,
            mean_squared_error,
            r2_score,
        )

        if self.tipo_problema == "regression":
            return {
                "mae": float(mean_absolute_error(y_real, y_previsto)),
                "rmse": float(mean_squared_error(y_real, y_previsto) ** 0.5),
                "r2": float(r2_score(y_real, y_previsto)) if len(y_real) > 1 else 0.0,
            }
        return {
            "accuracy": float(accuracy_score(y_real, y_previsto)),
            "f1_macro": float(
                f1_score(y_real, y_previsto, average="macro", zero_division=0)
            ),
            "f1_weighted": float(
                f1_score(y_real, y_previsto, average="weighted", zero_division=0)
            ),
        }

    def _get_predictor(self) -> Any:
        """Retorna o predictor em memória ou carrega o artefato salvo.

        Returns:
            TabularPredictor treinado.

        Raises:
            RuntimeError: Se o modelo ainda não foi treinado ou salvo.
        """
        if self.melhor_modelo is not None:
            return self.melhor_modelo
        if not self.caminho_predictor:
            raise RuntimeError("O modelo ainda não foi treinado ou carregado.")
        if self.estrategia is None:
            self.estrategia = self._criar_estrategia()
        self.estrategia.load_predictor(self.caminho_predictor)
        self.melhor_modelo = self.estrategia.predictor
        return self.melhor_modelo

    def prever(self, data: Dataset | Any) -> Dataset:
        """Aplica inferência e devolve Dataset com coluna de previsão.

        Args:
            data: Dataset ou DataFrame com as features do modelo.

        Returns:
            Dataset com previsões e metadados do modelo.

        Raises:
            TypeError: Se a entrada não for tabular.
            RuntimeError: Se não houver predictor treinado ou salvo.
        """
        if isinstance(data, Dataset):
            frame = data.data.copy()
        elif isinstance(data, pd.DataFrame):
            frame = data.copy()
        else:
            raise TypeError("A previsão exige um Dataset ou DataFrame tabular.")
        predictor = self._get_predictor()
        features = frame.drop(columns=[self.alvo], errors="ignore")
        if self.estrategia is None:
            self.estrategia = self._criar_estrategia()
            self.estrategia.predictor = predictor
        frame[f"previsao_{self.alvo}"] = (
            self.estrategia.predict(features)[f"previsao_{self.alvo}"].to_numpy()
        )
        if self.tipo_problema != "regression":
            probabilities = predictor.predict_proba(features)
            if isinstance(probabilities, pd.DataFrame):
                for label in probabilities.columns:
                    frame[f"prob_{label}"] = probabilities[label].to_numpy()
                frame["confianca_previsao"] = probabilities.max(axis=1).to_numpy()
        metadata = data.metadata if isinstance(data, Dataset) else {}
        return Dataset(
            frame,
            {
                **metadata,
                "model": self.name,
                "model_version": str(self.version),
                "target": self.alvo,
                "problem_type": self.tipo_problema,
            },
        )

    def avaliar(self, pipeline_teste: Any) -> Metricas:
        """Avalia previsões em um conjunto de teste com alvo disponível.

        Args:
            pipeline_teste: Dados ou pipeline de teste.

        Returns:
            Métricas da avaliação.
        """
        dataset = (
            pipeline_teste
            if isinstance(pipeline_teste, Dataset)
            else Dataset(self._obter_dataframe(pipeline_teste))
        )
        if self.alvo not in dataset.data.columns:
            return Metricas({"rows": len(dataset.data), "model": self.name})
        resultado = self.prever(dataset).data
        values = self._calcular_metricas(
            dataset.data[self.alvo],
            resultado[f"previsao_{self.alvo}"],
        )
        values["rows"] = int(len(dataset.data))
        return Metricas(values)

    def tabela_leaderboard(self) -> pd.DataFrame:
        """Retorna uma cópia do leaderboard calculado durante o treino."""
        return self.leaderboard_df.copy()

    def metadata(self) -> dict[str, Any]:
        """Descreve configuração, localização do predictor e métricas."""
        return {
            "name": self.name,
            "version": str(self.version),
            "target": self.alvo,
            "problem_type": self.tipo_problema,
            "eval_metric": self.metrica,
            "validation_strategy": self.estrategia_validacao,
            "predictor_path": self.caminho_predictor,
            "metrics": self.metricas_teste,
        }

    def __getstate__(self) -> dict[str, Any]:
        """Remove conexão SQLite não serializável ao persistir o modelo."""
        state = self.__dict__.copy()
        state["sqlite_connection"] = None
        return state

    def salvar(self, path: str | Path, metadata: dict[str, Any] | None = None) -> Path:
        """Copia os artefatos AutoGluon e persiste modelo e metadados.

        Args:
            path: Diretório de destino do modelo.
            metadata: Metadados adicionais a incluir no JSON.

        Returns:
            Caminho do diretório persistido.

        Raises:
            OSError: Se os artefatos não puderem ser gravados ou copiados.
            RuntimeError: Se o predictor não puder ser carregado.
        """
        destination = Path(path).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        predictor = self._get_predictor()
        source = Path(predictor.path).resolve()
        target = (destination / "autogluon").resolve()
        if source != target:
            shutil.copytree(source, target, dirs_exist_ok=True)
        self.caminho_predictor = str(target)
        model_copy = self.__class__.__new__(self.__class__)
        model_copy.__dict__ = self.__dict__.copy()
        model_copy.melhor_modelo = None
        with (destination / "model.pkl").open("wb") as stream:
            pickle.dump(model_copy, stream)
        payload = {**self.metadata(), **(metadata or {})}
        (destination / "metadata.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        return destination


__all__ = ["ModeloAutoGluonTabular"]
