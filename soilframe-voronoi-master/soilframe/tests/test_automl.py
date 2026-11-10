import pandas as pd
import numpy as np
import pytest
from pathlib import Path

from soilframe import Dataset, Registry, ModeloAutoMLClassificador, Metricas


@pytest.fixture
def dummy_agroclimatic_dataset() -> Dataset:
    np.random.seed(42)
    n_days = 40
    cells = ["cell_1", "cell_2"]
    rows = []
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    
    for cell in cells:
        for dt in dates:
            tmin = np.random.uniform(15.0, 22.0)
            tmax = tmin + np.random.uniform(5.0, 15.0)
            p = np.random.choice([0.0, 0.0, 2.5, 12.0, 30.0])
            et0 = np.random.uniform(2.5, 6.0)
            rows.append({
                "cell_id": cell,
                "data": dt.strftime("%Y-%m-%d"),
                "tmax_c": round(tmax, 2),
                "tmin_c": round(tmin, 2),
                "tmean_c": round((tmax + tmin) / 2, 2),
                "precipitacao_mm": round(p, 2),
                "et0_mm": round(et0, 2),
                "radiacao_solar_mj_m2": round(np.random.uniform(14.0, 25.0), 2),
                "vento_10m_ms": round(np.random.uniform(1.0, 4.0), 2),
                "lat": -19.9,
                "lon": -43.9,
                "area_km2": 331.0,
            })
    df = pd.DataFrame(rows)
    return Dataset(df, metadata={"teste": True})


def test_automl_registry_discovery():
    reg = Registry()
    modelo = reg.get_model("modelo_automl_classificador")
    assert isinstance(modelo, ModeloAutoMLClassificador)
    assert modelo.name == "modelo_automl_classificador"


def test_automl_train_and_predict(dummy_agroclimatic_dataset):
    modelo = ModeloAutoMLClassificador(
        alvo="classe_deficit_hidrico",
        modo_predicao="proximo_dia",
        cv_folds=2,
        test_size=0.2,
        random_state=42,
    )
    modelo.treinar(dummy_agroclimatic_dataset)

    assert modelo.melhor_modelo is not None
    assert modelo.melhor_algoritmo != ""
    assert len(modelo.classes_) >= 2
    assert not modelo.leaderboard_df.empty

    # Testa Leaderboard
    df_lead = modelo.tabela_leaderboard()
    assert "algoritmo" in df_lead.columns
    assert "acuracia_cv" in df_lead.columns

    # Testa Avaliação
    metricas = modelo.avaliar(dummy_agroclimatic_dataset)
    assert isinstance(metricas, Metricas)
    assert "accuracy" in metricas.valores

    # Testa Predição
    preds = modelo.prever(dummy_agroclimatic_dataset)
    assert isinstance(preds, Dataset)
    assert "previsao_classe_deficit_hidrico" in preds.data.columns
    assert "confianca_previsao" in preds.data.columns
    assert len(preds.data) == len(dummy_agroclimatic_dataset.data)


def test_automl_save_and_load(dummy_agroclimatic_dataset, tmp_path):
    modelo = ModeloAutoMLClassificador(cv_folds=2, random_state=42)
    modelo.treinar(dummy_agroclimatic_dataset)

    save_dir = tmp_path / "automl_test_export"
    modelo.salvar(save_dir)

    assert (save_dir / "model.pkl").exists()
    assert (save_dir / "metadata.json").exists()
    assert (save_dir / "leaderboard.csv").exists()

    carregado = ModeloAutoMLClassificador.carregar(save_dir)
    assert carregado.melhor_algoritmo == modelo.melhor_algoritmo

    # Prever com o modelo carregado
    res = carregado.prever(dummy_agroclimatic_dataset)
    assert "previsao_classe_deficit_hidrico" in res.data.columns
