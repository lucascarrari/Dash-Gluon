"""Instala o dashboard e AutoGluon numa .venv local, sem instalação global."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--somente-tabular", action="store_true")
    args = parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] <= (3, 12):
        raise SystemExit("Execute este instalador com Python 3.11 ou 3.12.")
    app = Path(__file__).resolve().parent / "soilframe-dashboard"
    environment = app / ".venv"
    python = environment / "Scripts" / "python.exe"
    if not python.exists():
        if environment.exists():
            raise SystemExit("A .venv existe mas está incompleta. Preserve-a com outro nome antes de continuar.")
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    subprocess.run([str(python), "-c", "import sys; print(sys.version)"], check=True)
    pip = [str(python), "-m", "pip", "install", "--retries", "0", "--timeout", "15"]
    subprocess.run([*pip, "--upgrade", "pip", "setuptools", "wheel"], check=True)
    extras = "automl-tabular" if args.somente_tabular else "automl-tabular,automl-timeseries"
    subprocess.run([*pip, "-e", f"{app}[{extras}]"], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    imports = "from autogluon.tabular import TabularPredictor; import streamlit, sklearn, dotenv"
    if not args.somente_tabular:
        imports += "; from autogluon.timeseries import TimeSeriesPredictor"
    subprocess.run([str(python), "-c", imports + "; print('Importações AutoGluon e dashboard: OK')"], check=True)
    print("Instalação concluída. Os treinos reais ainda precisam ser validados.")
    print("Inicie pelo arquivo iniciar_dashboard.bat.")


if __name__ == "__main__":
    main()
