"""Reproduz achados sem instalar dependências e sem modificar a base."""
import json
from pathlib import Path
import sqlite3
import sys
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "soilframe-dashboard"), str(ROOT / "soilframe-voronoi-master" / "soilframe"), str(HERE / "deps")]
import pandas as pd
from soilframe_dashboard.data_access import load_source
from soilframe_dashboard.training_config import recommend_problem_type, timeseries_target_candidates
from soilframe_dashboard.ui import _gold_sources
from soilframe_dashboard.jobs import JobManager
from soilframe.models.modelo_autogluon import ModeloAutoGluonTabular

results = {}
decimal_results = []
for label, source in _gold_sources().items():
    frame = load_source(source)
    columns = {}
    for column in ["tmax_c", "tmin_c", "precipitation_mm", "eto_mm", "latitude", "longitude"]:
        if column not in frame:
            continue
        raw = frame[column]
        numeric = pd.to_numeric(raw, errors="coerce")
        normalized = pd.to_numeric(raw.astype(str).str.replace(",", ".", regex=False), errors="coerce")
        columns[column] = {"dtype": str(raw.dtype), "amostras": raw.head(3).tolist(), "validos_conversao_atual": int(numeric.notna().sum()), "validos_decimal_normalizado": int(normalized.notna().sum()), "sugestao_tipo_atual": recommend_problem_type(raw)[0], "disponivel_timeseries": column in timeseries_target_candidates(frame)}
    decimal_results.append({"label": label, "linhas": len(frame), "columns": columns})
results["decimais"] = decimal_results

source = next(value for label, value in _gold_sources().items() if "ERA5-Seamless" in label)
frame = load_source(source).head(1200).copy()
frame["eto_mm"] = pd.to_numeric(frame["eto_mm"].astype(str).str.replace(",", ".", regex=False))
manager = JobManager(HERE / "treinos")
options = {"run_id": "diagnostico_causa_raiz", "task_type": "tabular", "target": "eto_mm", "problem_type": "regression", "validation_strategy": "temporal", "date_column": "date", "time_limit": 15, "preset": "medium_quality"}
try:
    manager._run_tabular(frame, options, HERE / "diagnostico_modelo")
except Exception:
    results["cadeia_completa_erro_tabular"] = traceback.format_exc()
manager._executor.shutdown(wait=True)

default = load_source(next(iter(_gold_sources().values()))).head(1200).rename(columns={"date": "data"})
try:
    model = ModeloAutoGluonTabular(alvo="tmax_c", tipo_problema="regression", caminho_modelo=HERE / "diagnostico_modelo")
    train, test = model._separar_treino_teste(default)
    results["regressao_fonte_padrao_sem_normalizacao"] = {"train": len(train), "test": len(test)}
except Exception:
    results["regressao_fonte_padrao_sem_normalizacao"] = traceback.format_exc()

with sqlite3.connect((ROOT / "soilframe-dashboard" / "outputs" / "dashboard_runs.sqlite3").as_uri() + "?mode=ro", uri=True) as conn:
    conn.row_factory = sqlite3.Row
    history = []
    for row in conn.execute("SELECT run_id, task_type, target, status, duration_seconds, metrics_json, predictions_path, leaderboard_path, error FROM runs ORDER BY created_at"):
        record = dict(row)
        record["metrics"] = json.loads(record.pop("metrics_json") or "{}")
        for key in ["predictions_path", "leaderboard_path"]:
            value = record[key]
            record[key + "_existe"] = bool(value and Path(value).is_file())
        history.append(record)
    results["historico_preexistente_nao_e_treino_novo"] = history

(HERE / "achados_detalhados.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
