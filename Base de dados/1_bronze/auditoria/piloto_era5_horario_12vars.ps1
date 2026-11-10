$ErrorActionPreference = 'Stop'

$root = 'C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$base = Join-Path $root '1_bronze\era5\variables_horarias\pilots'
$counterPath = Join-Path $root '1_bronze\auditoria\contador_chamadas.json'
New-Item -ItemType Directory -Path $base -Force | Out-Null

$locationId = 'BR_AC_RIO_BRANCO'
$latitude = '-9.9753'
$longitude = '-67.8249'
$date = '2026-10-07'
$variables = @(
    'temperature_2m', 'dew_point_2m', 'relative_humidity_2m', 'vapour_pressure_deficit',
    'soil_moisture_0_to_7cm', 'soil_moisture_7_to_28cm', 'soil_moisture_28_to_100cm', 'soil_moisture_100_to_255cm',
    'soil_temperature_0_to_7cm', 'soil_temperature_7_to_28cm', 'soil_temperature_28_to_100cm', 'soil_temperature_100_to_255cm'
)
$hourly = $variables -join ','
$url = "https://archive-api.open-meteo.com/v1/archive?latitude=$latitude&longitude=$longitude&start_date=$date&end_date=$date&hourly=$hourly&timezone=GMT&models=era5"
$pilotCost = 1.2
$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
if (($pilotCost * 1.20) -gt [double]$counter.remaining_project_budget) {
    throw 'O piloto mais a margem excede o saldo. Nenhuma chamada foi feita.'
}

$response = $null
$body = ''
$transportError = $null
try {
    $response = Invoke-WebRequest -Uri $url -TimeoutSec 120 -UseBasicParsing
    $body = [string]$response.Content
}
catch {
    $transportError = $_.Exception.Message
    $counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
    $counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
    $counter.collection_status = 'era5_hourly_pilot_transport_error'
    $counter.block_reason = 'ERA5 hourly pilot failed before an HTTP response; no retry was made.'
    $counter.last_updated_utc = [DateTime]::UtcNow.ToString('o')
    $counter | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $counterPath -Encoding utf8
    $failure = [ordered]@{ endpoint = 'https://archive-api.open-meteo.com/v1/archive'; model = 'era5'; models_parameter = 'era5'; location_id = $locationId; request_url = $url; start_date = $date; end_date = $date; variables = $variables; http_status = 0; transport_error = $transportError; billed_calls_counted = 0; retry = $false }
    $failure | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $base 'manifest_pilot_era5_hourly.json') -Encoding utf8
    throw 'Piloto interrompido antes da resposta HTTP; sem retry.'
}

$rawPath = Join-Path $base "pilot_${locationId}_${date}.json"
Set-Content -LiteralPath $rawPath -Value $body -Encoding utf8
$json = $null
$parseError = $null
try { $json = $body | ConvertFrom-Json -ErrorAction Stop } catch { $parseError = $_.Exception.Message }
$times = @()
$allVariablesPresent = $false
$allValuesValid = $false
$units = $null
if ($json) {
    $times = @($json.hourly.time)
    $allVariablesPresent = $true
    $allValuesValid = $true
    $unitMap = [ordered]@{}
    foreach ($variable in $variables) {
        $values = @($json.hourly.$variable)
        $unit = $json.hourly_units.$variable
        $unitMap[$variable] = $unit
        if ($values.Count -ne 24) { $allVariablesPresent = $false; $allValuesValid = $false }
        if (@($values | Where-Object { $null -ne $_ }).Count -ne 24) { $allValuesValid = $false }
    }
    $units = $unitMap
}
$apiLatitude = $null
$apiLongitude = $null
$returnedTimezone = ''
if ($json) {
    $apiLatitude = $json.latitude
    $apiLongitude = $json.longitude
    $returnedTimezone = $json.timezone
}
$valid = ([int]$response.StatusCode -eq 200 -and $response.Headers['Content-Type'] -match 'json' -and $times.Count -eq 24 -and $times[0] -eq '2026-10-07T00:00' -and $times[-1] -eq '2026-10-07T23:00' -and $allVariablesPresent -and $allValuesValid -and $json.timezone -eq 'GMT')

$manifest = [ordered]@{
    endpoint = 'https://archive-api.open-meteo.com/v1/archive'; model = 'era5'; models_parameter = 'era5'
    location_id = $locationId; requested_latitude = [double]$latitude; requested_longitude = [double]$longitude
    api_latitude = $apiLatitude; api_longitude = $apiLongitude
    start_date = $date; end_date = $date; timezone = 'GMT'; frequency = 'hourly'; variables = $variables; units = $units
    http_status = [int]$response.StatusCode; content_type = [string]$response.Headers['Content-Type']; hours_returned = $times.Count
    valid = $valid; estimated_billed_calls = $pilotCost; retry_margin_units = $pilotCost * 0.20
    request_url = $url; raw_file = $rawPath; parse_error = $parseError; transport_error = $transportError
}
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $base 'manifest_pilot_era5_hourly.json') -Encoding utf8

$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
$counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
$counter.completed_calls = [double]$counter.completed_calls + $pilotCost
$counter.remaining_project_budget = [double]$counter.budget_internal.project_total - [double]$counter.completed_calls
$counter.collection_status = if ($valid) { 'era5_hourly_pilot_valid_full_range_pending' } else { 'era5_hourly_pilot_invalid_stop' }
$counter.block_reason = if ($valid) { 'ERA5 hourly pilot validated; recalculate full-range batch cost before collection.' } else { 'ERA5 hourly pilot response failed validation; no full series or retry.' }
$counter.pending_era5_hourly_estimate | Add-Member -NotePropertyName pilot_completed -NotePropertyValue $valid -Force
$counter.pending_era5_hourly_estimate | Add-Member -NotePropertyName pilot_calls -NotePropertyValue $pilotCost -Force
$counter.planned_calls = if ($valid) { 24 * (730 / 14.0) * 1.2 * 1.2 } else { 0 }
$counter.pending_era5_hourly_estimate.estimate_with_margin = if ($valid) { 24 * (730 / 14.0) * 1.2 * 1.2 } else { 0 }
$counter.next_lot_estimate.planned_total = $counter.planned_calls
$counter.next_lot_estimate.projected_remaining_after_success = [double]$counter.remaining_project_budget - [double]$counter.planned_calls
$counter.next_lot_estimate.pilot_calls = 0
$counter.last_updated_utc = [DateTime]::UtcNow.ToString('o')
$counter | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $counterPath -Encoding utf8

[pscustomobject]@{
    HttpStatus = [int]$response.StatusCode; ModelsParameter = 'era5'; Location = $locationId
    Hours = $times.Count; First = $times[0]; Last = $times[-1]; Variables = $variables.Count
    AllFieldsPresent = $allVariablesPresent; AllValuesValid = $allValuesValid; Timezone = $returnedTimezone
    Validated = $valid; RawFile = $rawPath; Manifest = (Join-Path $base 'manifest_pilot_era5_hourly.json')
    CompletedCalls = $counter.completed_calls; Remaining = $counter.remaining_project_budget
} | Format-List

if (-not $valid) { throw 'Piloto inválido; não iniciar série completa.' }
