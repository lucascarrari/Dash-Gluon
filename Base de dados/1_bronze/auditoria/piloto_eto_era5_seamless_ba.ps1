$ErrorActionPreference = 'Stop'
$base = 'C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$counterPath = Join-Path $base '1_bronze\auditoria\contador_chamadas.json'
$rawDir = Join-Path $base '1_bronze\era5_seamless_eto\raw'
$manifestDir = Join-Path $base '1_bronze\era5_seamless_eto'

$locationId = 'BR_BA_BARREIRAS'; $lat = -12.1528; $lon = -44.99
$date = '2026-10-07'; $model = 'era5_seamless'; $variable = 'et0_fao_evapotranspiration'
$estimate = 1.0 / 14.0; $margin = $estimate * 0.20
$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
if ($counter.PSObject.Properties['eto_seamless_ba_pilot']) { throw 'Piloto BA já registrado; não repetir a chamada.' }
$balance = [double]$counter.remaining_project_budget
if (($estimate + $margin) -gt $balance) { throw "Saldo insuficiente: custo+margem=$($estimate+$margin); saldo=$balance" }
try {
    Resolve-DnsName archive-api.open-meteo.com -ErrorAction Stop | Out-Null
    $tcp = Test-NetConnection archive-api.open-meteo.com -Port 443 -WarningAction SilentlyContinue
    if (-not $tcp.TcpTestSucceeded) { throw 'Pré-verificação TCP 443 falhou; nenhum pedido HTTP foi feito.' }
} catch { Write-Error "Pré-verificação falhou; nenhum pedido HTTP foi feito: $($_.Exception.Message)"; exit 2 }
$rawPath = Join-Path $rawDir "pilot_$($locationId)_$($date).json"
$manifestPath = Join-Path $manifestDir "manifest_pilot_$($locationId)_$($date).json"
$uri = "https://archive-api.open-meteo.com/v1/archive?latitude=$lat&longitude=$lon&start_date=$date&end_date=$date&daily=$variable&timezone=GMT&models=$model"
$counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
$counter.planned_calls = $estimate
$counter.collection_status = 'eto_seamless_pilot_in_progress'
$counter | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $counterPath -Encoding utf8
$status = 'transport_error'; $httpStatus = $null; $contentType = $null; $rawText = $null; $errorText = $null; $json = $null
try {
    $response = Invoke-WebRequest -Uri $uri -TimeoutSec 60 -UseBasicParsing
    $httpStatus = [int]$response.StatusCode
    $contentType = [string]$response.Headers['Content-Type']
    $rawText = [string]$response.Content
    Set-Content -LiteralPath $rawPath -Value $rawText -Encoding utf8
    if ($httpStatus -eq 429) { $status = 'http_429_no_retry' }
    elseif ($httpStatus -ne 200) { $status = 'http_error_no_retry' }
    else {
        try {
            $json = $rawText | ConvertFrom-Json -ErrorAction Stop
            $times = @($json.daily.time); $values = @($json.daily.$variable); $unit = [string]$json.daily_units.$variable
            $valid = ($times.Count -eq 1 -and $times[0] -eq $date -and $values.Count -eq 1 -and $null -ne $values[0] -and $unit -eq 'mm')
            if ($valid) { $status = 'validated' } else { $status = 'invalid_response_no_retry' }
        } catch { $status = 'invalid_json_no_retry'; $errorText = $_.Exception.Message }
    }
} catch { $errorText = $_.Exception.Message }
$charged = $estimate
$counter.completed_calls = [double]$counter.completed_calls + $charged
$counter.remaining_project_budget = [double]$counter.remaining_project_budget - $charged
$counter.planned_calls = 0
$counter.last_project_api_response_utc = (Get-Date).ToUniversalTime().ToString('o')
$counter.last_updated_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$pilotRecord = [pscustomobject]@{
    model=$model; endpoint='/v1/archive'; location_id=$locationId; state='BA'; variable=$variable
    unit='mm'; date=$date; timezone='GMT'; http_status=$httpStatus; status=$status
    estimated_calls=$estimate; retry_margin=$margin; billed_calls_counted=$charged
    raw_file=$rawPath; manifest=$manifestPath; error=$errorText
}
$counter.collection_status = "eto_seamless_pilot_$status"
$counter | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $counterPath -Encoding utf8
$manifest = [ordered]@{
    endpoint='/v1/archive'; models=$model; location_id=$locationId; state='BA'
    requested_latitude=$lat; requested_longitude=$lon; date=$date; timezone='GMT'
    daily_variable=$variable; expected_unit='mm'; http_status=$httpStatus; content_type=$contentType
    validation_status=$status; estimated_calls=$estimate; retry_margin_reserved=$margin
    billed_calls_counted=$charged; raw_file=$rawPath; request_url=$uri; transport_error=$errorText
    api_latitude=$(if($json){$json.latitude}else{$null}); api_longitude=$(if($json){$json.longitude}else{$null})
    returned_time=$(if($json){$json.daily.time[0]}else{$null})
    returned_value=$(if($json){$json.daily.$variable[0]}else{$null})
    returned_unit=$(if($json){$json.daily_units.$variable}else{$null})
}
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding utf8
[pscustomobject]@{
    HttpStatus=$httpStatus; ModelsParameter=$model; LocationId=$locationId; Date=$date
    Variable=$variable; Unit=$(if($json){$json.daily_units.$variable}else{$null})
    Value=$(if($json){$json.daily.$variable[0]}else{$null}); Status=$status
    EstimatedCalls=$estimate; RetryReserve=$margin
    CompletedCalls=$counter.completed_calls; Remaining=$counter.remaining_project_budget
    RawFile=$rawPath; Manifest=$manifestPath; Error=$errorText
}
if ($status -ne 'validated') { exit 3 }


