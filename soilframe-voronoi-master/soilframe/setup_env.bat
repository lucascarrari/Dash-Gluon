@echo off
echo Criando ambiente virtual em .venv...
python -m venv .venv

echo Ativando ambiente virtual...
call .\.venv\Scripts\activate.bat

echo Atualizando pip e instalando numpy primeiro...
python -m pip install --upgrade pip
pip install numpy

echo Instalando o SoilFrame e dependencias...
pip install -e .

echo.
echo Ambiente configurado com sucesso!
echo Framework instalado. Use "soilframe --help" para consultar os comandos.
pause
