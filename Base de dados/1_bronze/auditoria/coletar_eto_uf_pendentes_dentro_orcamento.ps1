$ErrorActionPreference = 'Stop'
$base = 'C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$audit = Join-Path $base '1_bronze\auditoria'
$counterPath = Join-Path $audit 'contador_chamadas.json'
$batchPath = Join-Path $audit 'manifest_eto_uf_pendentes_batch_2026-11-09.json'
$perPoint = 730.0 / 14.0
$margin = $perPoint * 0.20
$stage = @(
    [pscustomobject]@{ State='SP'; Location='BR_SP_RIBEIRAO_PRETO'; Script='coletar_eto_seamless_sp_serie.ps1' },
    [pscustomobject]@{ State='MA'; Location='BR_MA_BALSAS'; Script='coletar_eto_seamless_ma_serie.ps1' },
    [pscustomobject]@{ State='PI'; Location='BR_PI_URUCUI'; Script='coletar_eto_seamless_pi_serie.ps1' },
    [pscustomobject]@{ State='PR'; Location='BR_PR_LONDRINA'; Script='coletar_eto_seamless_pr_serie.ps1' }
)
if (Test-Path -LiteralPath $batchPath) { throw "Este lote já foi iniciado. Audite o manifesto antes de qualquer retomada: $batchPath" }
$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
$balance = 8000.0 - [double]$counter.completed_calls
if ([math]::Abs($balance - [double]$counter.remaining_project_budget) -gt 0.01) { throw 'Contador inconsistente: saldo difere de 8000 menos completed_calls.' }
$pending = @($counter.pending_work_estimate.pending_uncovered_states)
foreach ($item in $stage) {
    if ($pending -notcontains $item.State) { throw "UF $($item.State) não consta como pendente; abortado sem chamadas." }
    if (-not (Test-Path -LiteralPath (Join-Path $audit $item.Script))) { throw "Script auxiliar ausente: $($item.Script)" }
}
$cost = $stage.Count * $perPoint
$reserve = $cost * 0.20
$required = $cost + $reserve
if ($balance -lt $required) { throw "Saldo insuficiente: lote+margem=$required; saldo=$balance. Nenhuma chamada feita." }
try {
    Resolve-DnsName archive-api.open-meteo.com -ErrorAction Stop | Out-Null
    $tcp = Test-NetConnection archive-api.open-meteo.com -Port 443 -WarningAction SilentlyContinue
    if (-not $tcp.TcpTestSucceeded) { throw 'TCP 443 não conectou.' }
} catch { throw "Pré-verificação DNS/TCP falhou; nenhuma chamada foi feita: $($_.Exception.Message)" }
$batch = [ordered]@{
    batch_id='eto_seamless_missing_ufs_2026-11-09'; endpoint='/v1/archive'; models='era5_seamless'
    variable='et0_fao_evapotranspiration'; period='2024-10-08/2026-10-07'; timezone='GMT'
    initial_calls=[double]$counter.completed_calls; initial_balance=$balance
    estimate_per_series=$perPoint; retry_margin_per_series=$margin; retry_margin_percent=20
    planned_cost=$cost; planned_retry_reserve=$reserve; planned_total_with_reserve=$required
    points=@($stage | ForEach-Object { [ordered]@{state=$_.State;location_id=$_.Location;script=$_.Script;status='pending'} })
    errors=@(); status='in_progress'; created_utc=(Get-Date).ToUniversalTime().ToString('o')
}
$batch | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $batchPath -Encoding utf8
function Save-Batch { $batch | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $batchPath -Encoding utf8 }
Write-Output ("Prévia: {0} pontos (SP, MA, PI, PR); custo {1:N4}; margem de retry 20% {2:N4}; total reservado {3:N4}; saldo inicial {4:N4}; saldo projetado após reserva {5:N4}. Intervalo entre chamadas: 25 s." -f $stage.Count,$cost,$reserve,$required,$balance,($balance-$required))
$stopReason = $null
for ($i=0; $i -lt $stage.Count; $i++) {
    $item = $stage[$i]
    if ($i -gt 0) { Start-Sleep -Seconds 25 }
    Write-Output "Executando $($item.State) / $($item.Location). Em erro, 429, cota ou validação inválida, o lote para sem retry automático."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $audit $item.Script)
    $exitCode = $LASTEXITCODE
    $counterNow = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
    $key = "eto_seamless_$($item.State.ToLower())_full"
    $record = $counterNow.PSObject.Properties[$key]
    if ($exitCode -ne 0 -or -not $record -or $record.Value.status -ne 'validated') {
        $batch.points[$i].status = if ($record) { [string]$record.Value.status } else { "child_exit_$exitCode" }
        $stopReason = "Falha ou validação não confirmada em $($item.State); lote interrompido sem retry."
        $batch.errors += $stopReason
        Save-Batch
        break
    }
    $batch.points[$i].status = 'validated'
    Save-Batch
}
$counterNow = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
$batch.status = if ($stopReason) { 'stopped_on_error_no_retry' } else { 'four_point_batch_complete' }
$batch.final_calls=[double]$counterNow.completed_calls
$batch.final_balance=[double]$counterNow.remaining_project_budget
$batch.uncovered_states=@($counterNow.pending_work_estimate.pending_uncovered_states)
$batch.completed_points=@($batch.points | Where-Object status -eq 'validated' | ForEach-Object location_id)
$batch.updated_utc=(Get-Date).ToUniversalTime().ToString('o')
Save-Batch
Write-Output ("Lote encerrado. Chamadas contabilizadas={0:N4}; saldo={1:N4}; UFs ETo pendentes={2}. Manifesto: {3}" -f $batch.final_calls,$batch.final_balance,(@($batch.uncovered_states) -join ', '),$batchPath)
if ($stopReason) { exit 4 }