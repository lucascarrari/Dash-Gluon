"""API pública com carregamento tardio dos módulos opcionais do SoilFrame.

As APIs mais pesadas de geoprocessamento, raster e notebooks só são importadas
quando solicitadas. Isso permite que aplicações tabulares usem Dataset, fontes
locais, Registry e modelos sem instalar todo o conjunto geoespacial.
"""

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ArtifactStore": "soilframe.core.artifacts",
    "Dataset": "soilframe.core.dataset",
    "Model": "soilframe.core.model",
    "Pipeline": "soilframe.core.pipeline",
    "Prediction": "soilframe.core.prediction",
    "Registry": "soilframe.core.registry",
    "FonteDados": "soilframe.core.data_sources",
    "ArquivoFonte": "soilframe.core.data_sources",
    "INMET": "soilframe.core.data_sources",
    "ERA5": "soilframe.core.data_sources",
    "Xavier": "soilframe.core.data_sources",
    "S3Curado": "soilframe.core.data_sources",
    "Metricas": "soilframe.core.metrics",
    "RepositorioModelos": "soilframe.core.model_repository",
    "RastreadorExperimento": "soilframe.core.tracking",
    "MLflowTracker": "soilframe.core.tracking",
    "AutoGluonTracker": "soilframe.core.tracking",
    "AutoGluonStrategy": "soilframe.core.strategy",
    "EstrategiaModelo": "soilframe.core.strategy",
    "EstrategiaDownload": "soilframe.core.strategy",
    "EstrategiaTransformacao": "soilframe.core.strategy",
    "EstrategiaDownloadUniforme": "soilframe.download",
    "EstrategiaDownloadVoronoi": "soilframe.download",
    "FonteSentinelVoronoi": "soilframe.download",
    "FonteERA5LandVoronoi": "soilframe.download",
    "PlanoDownload": "soilframe.download",
    "PipelineDownloadSentinel": "soilframe.pipelines.pipeline_download",
    "PipelineAquaCropERA5": "soilframe.pipelines.pipeline_aquacrop",
    "PipelineAquaCropLakehouse": "soilframe.pipelines.pipeline_lakehouse",
    "ModeloAutoMLClassificador": "soilframe.models.modelo_automl",
    "ModeloAutoGluonTabular": "soilframe.models.modelo_autogluon",
    "ModeloSolo": "soilframe.models.modelo_solo",
    "LakehouseManager": "soilframe.lakehouse",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Importa sob demanda um símbolo da API pública.

    Args:
        name: Símbolo público solicitado pelo chamador.

    Returns:
        O símbolo importado do módulo correspondente.

    Raises:
        AttributeError: Se o símbolo não fizer parte da API pública.
    """
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Lista símbolos já carregados e símbolos públicos disponíveis."""
    return sorted([*globals(), *__all__])



