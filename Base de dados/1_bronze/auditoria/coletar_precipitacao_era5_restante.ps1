$ErrorActionPreference = 'Stop'

$root = 'C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$base = Join-Path $root '1_bronze\era5\precipitacao\regional'
$rawDir = Join-Path $base 'raw'
$counterPath = Join-Path $root '1_bronze\auditoria\contador_chamadas.json'
$batchId = 'precip_era5_regional_batch_006'
$startDate = '2024-10-08'
$endDate = '2026-10-07'
$days = 730
$costPerPoint = $days / 14.0

$points = @(
    [pscustomobject]@{ id = 'BR_PA_SANTAREM'; name = 'Santarém'; state = 'PA'; region = 'Norte'; lat = -2.4431; lon = -54.7083 },
    [pscustomobject]@{ id = 'BR_RO_VILHENA'; name = 'Vilhena (Polo Agro)'; state = 'RO'; region = 'Norte'; lat = -12.7406; lon = -60.1458 },
    [pscustomobject]@{ id = 'BR_TO_PALMAS'; name = 'Palmas'; state = 'TO'; region = 'Norte'; lat = -10.2491; lon = -48.3243 }
)

$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
$actualEstimate = $points.Count * $costPerPoint
$retryReserve = $actualEstimate * 0.20
$plannedTotal = $actualEstimate + $retryReserve
if ($plannedTotal -gt [double]$counter.remaining_project_budget) {
    throw "Custo planejado ($plannedTotal) excede saldo persistente ($($counter.remaining_project_budget)). Nenhuma chamada foi feita."
}
if ($actualEstimate -gt 200) {
    throw "Lote excede limite de 200 chamadas contabilizadas/minuto. Nenhuma chamada foi feita."
}

$results = [System.Collections.Generic.List[object]]::new()
foreach ($point in $points) {
    $url = "https://archive-api.open-meteo.com/v1/archive?latitude=$($point.lat)&longitude=$($point.lon)&start_date=$startDate&end_date=$endDate&daily=precipitation_sum&timezone=GMT&models=era5"
    $response = $null
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 120 -UseBasicParsing
    }
    catch {
        $statusCode = 0
        $body = ''
        if ($_.Exception.Response) {
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {}
            try {
                $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
                $body = $reader.ReadToEnd()
                $reader.Dispose()
            } catch {}
        }
        if ($body) {
            $raw = Join-Path $rawDir "$($point.id)_${startDate}_${endDate}.json"
            Set-Content -LiteralPath $raw -Value $body -Encoding utf8
        }
        $counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
        $counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
        $counter.collection_status = if ($statusCode -eq 429) { 'stopped_429' } else { 'stopped_transport_or_http_error' }
        $counter.block_reason = "Batch 006 stopped at $($point.id); HTTP status $statusCode; no retry."
        $counter.last_updated_utc = [DateTime]::UtcNow.ToString('o')
        $counter | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $counterPath -Encoding utf8
        $results.Add([pscustomobject]@{ location_id = $point.id; http_status = $statusCode; validation = $false; error = $_.Exception.Message })
        $results | Format-Table -AutoSize
        throw "Lote interrompido em $($point.id), sem retry. Revise contador e resposta antes de qualquer nova chamada."
    }

    $raw = Join-Path $rawDir "$($point.id)_${startDate}_${endDate}.json"
    $body = [string]$response.Content
    Set-Content -LiteralPath $raw -Value $body -Encoding utf8
    $json = $null
    $parseError = $null
    try { $json = $body | ConvertFrom-Json -ErrorAction Stop } catch { $parseError = $_.Exception.Message }
    $dates = @()
    $values = @()
    $unit = $null
    if ($json) {
        $dates = @($json.daily.time)
        $values = @($json.daily.precipitation_sum)
        $unit = $json.daily_units.precipitation_sum
    }
    $validValues = @($values | Where-Object { $null -ne $_ }).Count
    $isValid = ([int]$response.StatusCode -eq 200 -and $response.Headers['Content-Type'] -match 'json' -and $dates.Count -eq 730 -and $dates[0] -eq $startDate -and $dates[-1] -eq $endDate -and $validValues -eq 730 -and $unit -eq 'mm' -and $json.timezone -eq 'GMT')

    $manifest = [ordered]@{
        batch_id = $batchId; model = 'era5'; models_parameter = 'era5'; endpoint = 'https://archive-api.open-meteo.com/v1/archive'
        variable_api = 'precipitation_sum'; canonical = 'precipitation_mm'; units = $unit; frequency = 'daily'; timezone = 'GMT'
        start_date = $startDate; end_date = $endDate; location_id = $point.id; location_name = $point.name; state = $point.state; macro_region = $point.region
        requested_latitude = $point.lat; requested_longitude = $point.lon; api_latitude = if ($json) { $json.latitude } else { $null }; api_longitude = if ($json) { $json.longitude } else { $null }
        http_status = [int]$response.StatusCode; content_type = [string]$response.Headers['Content-Type']; days_returned = $dates.Count
        valid_values = $validValues; null_values = $days - $validValues; estimated_billed_calls = $costPerPoint; retry_margin_units = $costPerPoint * 0.20
        raw_file = $raw; request_url = $url; validation = $isValid; parse_error = $parseError
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $base "$($point.id)_manifest.json") -Encoding utf8

    $counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
    $counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
    $counter.completed_calls = [double]$counter.completed_calls + $costPerPoint
    $counter.remaining_project_budget = [double]$counter.budget_internal.project_total - [double]$counter.completed_calls
    if ($isValid) { $counter.pending_precipitation_locations = [int]$counter.pending_precipitation_locations - 1 }
    $counter.planned_calls = [int]$counter.pending_precipitation_locations * $costPerPoint * 1.20
    $counter.collection_status = if ($isValid) { 'regional_precipitation_in_progress' } else { 'regional_precipitation_point_pending_validation' }
    $counter.block_reason = if ($isValid) { "$($point.id) validado; próximo ponto independente pode seguir." } else { "$($point.id) recebeu resposta, mas falhou validação; sem retry automático." }
    $counter.last_updated_utc = [DateTime]::UtcNow.ToString('o')
    $counter | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $counterPath -Encoding utf8
    $results.Add([pscustomobject]@{ location_id = $point.id; http_status = [int]$response.StatusCode; days = $dates.Count; valid = $validValues; nulls = $days - $validValues; units = $unit; validation = $isValid })
    if (-not $isValid) { continue }
}

$results | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $base 'manifest_batch_006.json') -Encoding utf8
$results | Format-Table -AutoSize
Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json | Select-Object completed_calls, remaining_project_budget, api_requests_attempted, retries, pending_precipitation_locations, planned_calls, collection_status | Format-List
