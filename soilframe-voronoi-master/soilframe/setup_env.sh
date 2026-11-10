#!/bin/bash
set -e
echo "Criando ambiente virtual em .venv..."
python3 -m venv .venv

echo "Ativando ambiente virtual..."
source .venv/bin/activate

echo "Atualizando pip e instalando numpy primeiro..."
pip install --upgrade pip
pip install numpy

echo "Instalando dependências do requirements.txt..."
pip install -e .

echo "Registrando o kernel no Jupyter..."

echo ""
echo "Ambiente configurado com sucesso!"
echo "Framework instalado. Use 'soilframe --help' para consultar os comandos."
