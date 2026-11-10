import pandas as pd
from soil_analysis.seasonal import (
    adicionar_anomalias,
    adicionar_estacao,
    associar_oni,
    correlacoes_oni,
    identificar_picos,
)

def test_verao_e_rotulado_pelo_ano_de_janeiro():
    dados = pd.DataFrame({"data": pd.to_datetime(["2023-12-15", "2024-01-15", "2024-02-15"]), "x": [1, 2, 3]})
    out = adicionar_estacao(dados)
    assert out["ano_estacao"].tolist() == [2024, 2024, 2024]
    assert out["estacao"].eq("verao").all()
    assert out["estacao_completa"].all()


def test_anomalia_e_pico_por_ano():
    datas = pd.date_range("2019-01-01", periods=12, freq="MS")
    dados = pd.DataFrame({"data": datas, "x": range(1, 13)})
    sazonal = __import__("soil_analysis.seasonal", fromlist=["agregar_sazonal"]).agregar_sazonal(dados, ["x"])
    anom = adicionar_anomalias(sazonal, ["x_media"])
    picos = identificar_picos(sazonal, ["x"], usar={"x": "media"})
    assert "x_media_anomalia" in anom
    assert picos.loc[0, "estacao_pico_x"] == "primavera"


def test_oni_correlacao_e_classificacao():
    sazonal = pd.DataFrame({"ano_estacao": [2015, 2016, 2017, 2018], "estacao": ["verao"] * 4, "x_media": [1, 2, 3, 4]})
    oni = pd.DataFrame({"ano": [2015, 2016, 2017, 2018], "oni": [-1, -0.2, 0.2, 1], "classificacao_enso": ["La Niña", "Neutro", "Neutro", "El Niño"], "periodo_oni": [4] * 4})
    associado = associar_oni(sazonal, oni)
    corr = correlacoes_oni(associado, ["x_media"])
    assert associado["oni"].notna().all()
    assert corr.loc[0, "n"] == 4
    assert corr.loc[0, "pearson_r"] > 0.9
