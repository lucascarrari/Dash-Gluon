# Script PowerShell para execucao continua e resiliente do AutoML
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "===============================================================================" -ForegroundColor Green
Write-Host " SOILFRAME: AUTOML CONTINUO DE LONGA DURACAO (COM CHECKPOINT E AUTO-RECOVERY)" -ForegroundColor Green
Write-Host "===============================================================================" -ForegroundColor Green
Write-Host "Diretorio de Trabalho: $scriptDir"
Write-Host "Iniciando motor de treino continuo..." -ForegroundColor Cyan

while ($true) {
    try {
        & "soilframe\.venv\Scripts\python.exe" -u treinar_automl_continuo.py
    }
    catch {
        Write-Warning "Excecao capturada no processo: $_"
    }

    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$now] Processo finalizado ou reiniciado. Recuperando ultimo checkpoint em 5s..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
