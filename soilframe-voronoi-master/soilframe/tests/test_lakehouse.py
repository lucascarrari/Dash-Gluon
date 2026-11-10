import pandas as pd
import numpy as np
import pytest
from pathlib import Path

from soilframe import LakehouseManager, PipelineAquaCropLakehouse, Registry


@pytest.fixture
def dummy_raw_climate() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    for d in dates:
        rows.append({
            "cell_id": 101,
            "municipio": "Sorriso",
            "uf": "MT",
            "lat": -12.55,
            "lon": -54.97,
            "area_km2": 9300.0,
            "data": d.strftime("%Y-%m-%d"),
            "tmax_c": 32.5,
            "tmin_c": 22.0,
            "tmean_c": 27.25,
            "precipitacao_mm": 5.0,
            "et0_mm": 4.2,
            "radiacao_solar_mj_m2": 18.5,
            "vento_10m_ms": 2.1,
        })
    return pd.DataFrame(rows)


def test_lakehouse_lifecycle(tmp_path, dummy_raw_climate):
    lh = LakehouseManager(base_dir=tmp_path / "lakehouse_test")

    # 1. Salvar Bronze
    p_bronze = lh.salvar_bronze(dummy_raw_climate, uf="MT", ano=2024)
    assert p_bronze.exists()
    assert lh.existe_em_bronze("MT", 2024)

    # 2. Promover para Prata
    df_prata = lh.promover_para_prata(uf="MT", ano=2024)
    assert lh.existe_em_prata("MT", 2024)
    assert len(df_prata) == len(dummy_raw_climate)

    # 3. Promover para Ouro
    df_ouro = lh.promover_para_ouro(uf="MT", ano=2024, gerar_arquivos_aquacrop=True)
    assert lh.existe_em_ouro("MT", 2024)
    assert "balanco_hidrico_diario" in df_ouro.columns
    assert "classe_deficit_hidrico" in df_ouro.columns
    assert "amplitude_termica" in df_ouro.columns

    # 4. Resumo Lakehouse
    resumo = lh.resumo_lakehouse()
    assert not resumo.empty
    assert "MT" in resumo["uf"].values

    # 5. Consolidação Nacional
    df_nac = lh.consolidar_nacional(ano=2024)
    assert len(df_nac) == len(df_ouro)


def test_registry_pipeline_lakehouse():
    reg = Registry()
    p = reg.get_pipeline("pipeline_aquacrop_lakehouse")
    assert isinstance(p, PipelineAquaCropLakehouse)
