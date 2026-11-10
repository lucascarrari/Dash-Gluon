"""Auditoria reproduzível: dados reais, interface e tentativas curtas de treino."""
from __future__ import annotations

import ast
import contextlib
import importlib.metadata
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import unittest
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
APP = ROOT / "soilframe-dashboard"
FRAMEWORK = ROOT / "soilframe-voronoi-master" / "soilframe"
sys.path[:0] = [str(APP), str(FRAMEWORK), str(HERE / "deps")]
os.chdir(APP)
RESULTS = {"python": sys.version, "executable": sys.executable, "checks": []}


def save():
    (HERE / "resultados.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def check(name, operation):
    start = time.perf_counter()
    record = {"name": name}
    try:
        record.update(status="ok", result=operation())
    except Exception:
        record.update(status="error", traceback=traceback.format_exc())
    record["seconds"] = round(time.perf_counter() - start, 3)
    RESULTS["checks"].append(record)
    save()
    print(json.dumps(record, ensure_ascii=False, default=str), flush=True)
    return record


def versions():
    result = {}
    for name in ["pandas", "numpy", "streamlit", "pyarrow", "scipy", "shapely", "pyproj", "python-dotenv", "scikit-learn", "autogluon.tabular", "autogluon.timeseries"]:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "ausente neste ambiente"
    return result


check("dependencias", versions)


def syntax():
    files = []
    for folder in [APP / "pages", APP / "soilframe_dashboard", FRAMEWORK / "soilframe", FRAMEWORK / "soil_analysis"]:
        files.extend(folder.rglob("*.py"))
    files.append(APP / "app.py")
    for file in files:
        ast.parse(file.read_text(encoding="utf-8-sig"), filename=str(file))
    return {"arquivos_validos": len(files)}


check("sintaxe", syntax)


def smoke():
    suite = unittest.defaultTestLoader.discover(str(APP / "tests"), pattern="test_dashboard_smoke.py")
    buffer = io.StringIO()
    result = unittest.TextTestRunner(stream=buffer, verbosity=2).run(suite)
    (HERE / "smoke_test.log").write_text(buffer.getvalue(), encoding="utf-8")
    if not result.wasSuccessful():
        raise RuntimeError(buffer.getvalue())
    return {"tests": result.testsRun, "log": buffer.getvalue()}


check("smoke_dashboard", smoke)

from soilframe_dashboard.data_access import load_source, csv_source_files, csv_separator
from soilframe_dashboard.ui import _gold_sources
import pandas as pd


def inspect_sources():
    output = []
    for label, location in _gold_sources().items():
        source = Path(location)
        frame = load_source(location)
        item = {"label": label, "path": location, "linhas_carregadas": len(frame), "colunas": list(frame.columns), "nulos": {c: int(v) for c, v in frame.isna().sum().items() if v}, "arquivos_csv": len(csv_source_files(source))}
        for name in ["data", "timestamp", "date", "time", "timestamp_utc"]:
            if name in frame:
                dates = pd.to_datetime(frame[name], errors="coerce")
                item["periodo"] = {"coluna": name, "inicio": str(dates.min()), "fim": str(dates.max()), "datas_invalidas": int(dates.isna().sum())}
                ids = next((c for c in ["location_id", "cell_id", "grid_id"] if c in frame), None)
                if ids:
                    item["ids"] = {"coluna": ids, "quantidade": int(frame[ids].nunique()), "duplicatas_id_data": int(frame.duplicated([ids, name]).sum())}
                break
        if source.is_dir():
            item["linhas_totais_csv"] = sum(len(pd.read_csv(p, sep=csv_separator(p))) for p in csv_source_files(source))
            item["ids_carregados"] = {c: frame[c].unique().tolist() for c in ["location_id", "cell_id", "grid_id"] if c in frame}
        output.append(item)
    return output


check("leitura_seis_fontes_reais", inspect_sources)


def train_attempts():
    from soilframe_dashboard.jobs import JobManager
    source = next(value for label, value in _gold_sources().items() if "ERA5-Seamless" in label)
    frame = load_source(source).head(1200).copy()
    numeric = [c for c in frame.select_dtypes(include="number") if frame[c].nunique() > 2 and c not in ["latitude", "longitude", "cell_id", "grid_id"]]
    target = "eto_mm" if "eto_mm" in frame else numeric[0]
    date_column = "data" if "data" in frame else "date"
    # Apenas no recorte da auditoria: a fonte contém separadores decimais mistos.
    frame[target] = pd.to_numeric(frame[target].astype(str).str.replace(",", ".", regex=False), errors="raise")
    # A classificação usa um rótulo explícito para exercitar o fluxo com duas classes.
    frame["classe_teste_auditoria"] = (frame[target] > frame[target].median()).astype(str)
    manager = JobManager(HERE / "treinos")
    options = {"task_type": "tabular", "target": target, "problem_type": "regression", "validation_strategy": "temporal", "time_limit": 15, "preset": "medium_quality", "date_column": date_column, "source_path": source, "random_state": 42}
    submitted = []
    submitted.append(manager.submit(frame.drop(columns="classe_teste_auditoria"), options))
    submitted.append(manager.submit(frame, {**options, "target": "classe_teste_auditoria", "problem_type": "binary"}))
    id_column = next((c for c in ["location_id", "cell_id", "grid_id"] if c in frame), None)
    ts = frame.copy()
    if id_column is None:
        ts["audit_series"] = "serie_1"
        id_column = "audit_series"
    submitted.append(manager.submit(ts, {"task_type": "timeseries", "target": target, "time_limit": 15, "preset": "fast_training", "prediction_length": 3, "item_id_column": id_column, "timestamp_column": date_column, "frequency": "D", "source_path": source}))
    for run_id in submitted:
        manager._futures[run_id].result(timeout=180)
    records = [manager.get_run(run_id) for run_id in submitted]
    manager._executor.shutdown(wait=True)
    return records


check("tres_treinos_rapidos_via_worker_real", train_attempts)


def original_app_test():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP / "app.py"), default_timeout=60).run()
    return {"exceptions": [str(e.message) for e in at.exception], "warnings": [str(w.value) for w in at.warning], "title": [str(t.value) for t in at.title]}


# Antes de adicionar a dependência pura disponível no ambiente antigo.
deps_entry = str(HERE / "deps")
sys.path.remove(deps_entry)
check("app_sem_dotenv_instalado", original_app_test)
sys.path.insert(0, deps_entry)

# Reuso apenas de código Python puro; nenhuma extensão cp311 é carregada no Python 3.12.
import shutil
dotenv_source = Path("C:/venvs/soilframe/Lib/site-packages/dotenv")
if dotenv_source.exists():
    shutil.copytree(dotenv_source, HERE / "deps" / "dotenv", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
importlib.invalidate_caches()


def app_pages():
    from streamlit.testing.v1 import AppTest
    pages = [None, "pages/data_explorer.py", "pages/gold_map.py", "pages/training.py", "pages/predictions.py", "pages/model_accuracy.py", "pages/experiments.py", "pages/pipeline_control.py"]
    output = []
    for page in pages:
        at = AppTest.from_file(str(APP / "app.py"), default_timeout=90).run()
        if page:
            at.switch_page(page).run()
        record = {"page": page or "app.py / overview", "exceptions": [str(e.message) for e in at.exception], "warnings": [str(w.value) for w in at.warning], "errors": [str(e.value) for e in at.error], "dataframes": len(at.dataframe)}
        output.append(record)
        print(json.dumps({"page_result": record}, ensure_ascii=False), flush=True)
    return output


check("oito_paginas_com_dotenv_local", app_pages)


def http_server():
    bootstrap = HERE / "servidor_validacao.py"
    bootstrap.write_text("import sys, runpy\nfrom pathlib import Path\np=Path(__file__).resolve().parent\nsys.path[:0]=[str(p/'deps'),str(p.parent/'soilframe-dashboard'),str(p.parent/'soilframe-voronoi-master'/'soilframe')]\nsys.argv=['streamlit','run',str(p.parent/'soilframe-dashboard'/'app.py'),'--server.headless=true','--server.address=127.0.0.1','--server.port=8517','--browser.gatherUsageStats=false']\nrunpy.run_module('streamlit',run_name='__main__')\n", encoding="utf-8")
    log_path = HERE / "servidor.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, str(bootstrap)], cwd=APP, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(30):
                if proc.poll() is not None:
                    raise RuntimeError(f"Servidor encerrou: {proc.returncode}")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8517/_stcore/health", timeout=1) as response:
                        health = response.read().decode()
                    with urllib.request.urlopen("http://127.0.0.1:8517", timeout=2) as response:
                        code = response.status
                    return {"health": health, "http_status": code, "port": 8517}
                except OSError:
                    time.sleep(0.5)
            raise TimeoutError("Servidor não ficou saudável em 15s")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


check("servidor_http_real", http_server)
save()
