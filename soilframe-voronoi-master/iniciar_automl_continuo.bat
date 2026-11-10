@echo off
title SoilFrame - AutoML Continuo de Alta Disponibilidade
cd /d "%~dp0"

echo ===============================================================================
echo  SOILFRAME: AUTOML CONTINUO DE LONGA DURACAO (COM CHECKPOINT E AUTO-RECOVERY)
echo ===============================================================================
echo  Diretorio: %cd%
echo  Iniciando motor de treino continuo...
echo.

:loop
soilframe\.venv\Scripts\python.exe -u treinar_automl_continuo.py
echo.
echo [AVISO] O processo foi interrompido ou finalizado em: %date% %time%
echo Reiniciando automaticamente em 5 segundos a partir do ultimo checkpoint...
timeout /t 5 /nobreak >nul
goto loop
