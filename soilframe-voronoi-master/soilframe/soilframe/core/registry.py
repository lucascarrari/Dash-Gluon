from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any


class Registry:
    """Descobre e instancia pipelines e modelos registrados no SoilFrame."""

    def __init__(self, root: str | Path = ".") -> None:
        """Inicializa o registro de componentes.

        Args:
            root: Diretório base associado à configuração do projeto.
        """
        self.root = Path(root)

    def _package_items(self, kind: str) -> list[dict[str, Any]]:
        """Retorna componentes integrados disponíveis por categoria.

        Args:
            kind: Categoria ``pipelines`` ou ``models``.

        Returns:
            Lista de metadados de componentes importáveis.
        """
        if kind == "pipelines":
            names = {
                "pipeline_precipitacao": (
                    "soilframe.pipelines.pipeline_precipitacao:PipelinePrecipitacao"
                ),
                "pipeline_swi": "soilframe.pipelines.pipeline_swi:PipelineSWI",
                "pipeline_lst": "soilframe.pipelines.pipeline_lst:PipelineLST",
                "pipeline_solo_et0": (
                    "soilframe.pipelines.pipeline_solo_et0:PipelineSoloET0"
                ),
                "pipeline_mensal": "soilframe.pipelines.pipeline_mensal:PipelineMensal",
                "pipeline_sazonal": (
                    "soilframe.pipelines.pipeline_sazonal:PipelineSazonal"
                ),
                "pipeline_decenal": (
                    "soilframe.pipelines.pipeline_decenal:PipelineDecenal"
                ),
                "pipeline_solo": "soilframe.pipelines.pipeline_solo:PipelineSolo",
                "pipeline_et0": "soilframe.pipelines.pipeline_et0:PipelineET0",
                "pipeline_download_sentinel": (
                    "soilframe.pipelines.pipeline_download:PipelineDownloadSentinel"
                ),
                "pipeline_aquacrop_era5": (
                    "soilframe.pipelines.pipeline_aquacrop:PipelineAquaCropERA5"
                ),
                "pipeline_aquacrop_lakehouse": (
                    "soilframe.pipelines.pipeline_lakehouse:PipelineAquaCropLakehouse"
                ),
            }
        else:
            names = {
                "modelo_solo": "soilframe.models.modelo_solo:ModeloSolo",
                "modelo_et0": "soilframe.models.modelo_et0:ModeloET0",
                "modelo_solo_et0": "soilframe.models.modelo_solo_et0:ModeloSoloET0",
                "modelo_automl_classificador": (
                    "soilframe.models.modelo_automl:ModeloAutoMLClassificador"
                ),
                "modelo_automl_autogluon": (
                    "soilframe.models.modelo_autogluon:ModeloAutoGluonTabular"
                ),
                "modelo_swi_autogluon": "soilframe.models.modelo_solo:ModeloSolo",
            }
        return [
            {
                "name": name,
                "version": "1.0.0",
                "entrypoint": entrypoint,
                "status": "active",
            }
            for name, entrypoint in names.items()
        ]

    def list_pipelines(self) -> list[dict[str, Any]]:
        """Lista pipelines disponibilizadas pelo pacote."""
        return self._package_items("pipelines")

    def list_models(self) -> list[dict[str, Any]]:
        """Lista modelos disponibilizados pelo pacote."""
        return self._package_items("models")

    def _get(self, kind: str, name: str, **parameters: Any) -> Any:
        """Importa e instancia o componente selecionado.

        Args:
            kind: Categoria ``pipelines`` ou ``models``.
            name: Nome público do componente.
            **parameters: Argumentos encaminhados ao construtor.

        Returns:
            Instância do componente.

        Raises:
            KeyError: Se o nome não estiver registrado.
        """
        item = next(
            (
                item
                for item in self._package_items(kind)
                if item["name"] == name
            ),
            None,
        )
        if not item:
            raise KeyError(f"Recurso não encontrado: {name}")
        module, symbol = item["entrypoint"].split(":")
        return getattr(import_module(module), symbol)(**parameters)

    def get_pipeline(self, name: str) -> Any:
        """Instancia uma pipeline registrada."""
        return self._get("pipelines", name)

    def get_model(self, name: str, **parameters: Any) -> Any:
        """Instancia um modelo registrado, incluindo adapters AutoGluon."""
        return self._get("models", name, **parameters)
