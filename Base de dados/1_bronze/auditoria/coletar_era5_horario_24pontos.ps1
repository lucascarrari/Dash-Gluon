$ErrorActionPreference = 'Stop'

$root = 'C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$bronze = Join-Path $root '1_bronze\era5\variables_horarias'
$rawDir = Join-Path $bronze 'raw'
$counterPath = Join-Path $root '1_bronze\auditoria\contador_chamadas.json'
$sourceManifestPath = Join-Path $root '1_bronze\era5_land\hourly_reused\run_manifest_origem.json'
$coveragePath = Join-Path $root '3_ouro\regional\era5_land\cobertura_por_localidade.csv'
$startDate = '2024-10-08'
$endDate = '2026-10-07'
$days = 730
$variables = @(
    'temperature_2m', 'dew_point_2m', 'relative_humidity_2m', 'vapour_pressure_deficit',
    'soil_moisture_0_to_7cm', 'soil_moisture_7_to_28cm', 'soil_moisture_28_to_100cm', 'soil_moisture_100_to_255cm',
    'soil_temperature_0_to_7cm', 'soil_temperature_7_to_28cm', 'soil_temperature_28_to_100cm', 'soil_temperature_100_to_255cm'
)
$expectedUnits = @{
    temperature_2m = '°C'; dew_point_2m = '°C'; relative_humidity_2m = '%'; vapour_pressure_deficit = 'kPa'
    soil_moisture_0_to_7cm = 'm³/m³'; soil_moisture_7_to_28cm = 'm³/m³'; soil_moisture_28_to_100cm = 'm³/m³'; soil_moisture_100_to_255cm = 'm³/m³'
    soil_temperature_0_to_7cm = '°C'; soil_temperature_7_to_28cm = '°C'; soil_temperature_28_to_100cm = '°C'; soil_temperature_100_to_255cm = '°C'
}
$modelVariableFactor = $variables.Count / 10.0
$costPerPoint = ($days / 14.0) * $modelVariableFactor
$batchSize = 2
$retryMarginPercent = 0.20
$hourlyParameter = $variables -join ','

New-Item -ItemType Directory -Path $rawDir -Force | Out-Null
$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
$pilotManifestPath = Join-Path $root '1_bronze\era5\variables_horarias\pilots\manifest_pilot_era5_hourly.json'
if (-not (Test-Path -LiteralPath $pilotManifestPath)) { throw 'ERA5 hourly pilot manifest missing; no full-range calls made.' }
$pilotManifest = Get-Content -LiteralPath $pilotManifestPath -Raw | ConvertFrom-Json
if ($pilotManifest.valid -ne $true -or $pilotManifest.models_parameter -ne 'era5') { throw 'ERA5 hourly pilot has not passed; no full-range calls made.' }

$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw | ConvertFrom-Json
$coverage = Import-Csv -LiteralPath $coveragePath
$regionalIds = @($coverage | Select-Object -ExpandProperty location_id -Unique)
$points = @($sourceManifest.locations | Where-Object { $regionalIds -contains $_.location_id } | Sort-Object location_id)
if ($points.Count -ne 24 -or @($points.state | Select-Object -Unique).Count -ne 11) { throw 'Expected exactly the 24 existing regional localities across 11 UFs; no calls made.' }
foreach ($point in $points) {
    if ($null -eq $point.latitude -or $null -eq $point.longitude) { throw "Missing proven source coordinates for $($point.location_id); no calls made." }
}

$fullSeriesEstimate = $points.Count * $costPerPoint
$fullSeriesReserve = $fullSeriesEstimate * $retryMarginPercent
$projectedPlan = $fullSeriesEstimate + $fullSeriesReserve
$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
if ($projectedPlan -gt [double]$counter.remaining_project_budget) { throw "Full plan plus margin ($projectedPlan) exceeds persistent balance ($($counter.remaining_project_budget)); no calls made." }
if (($batchSize * $costPerPoint) * (1 + $retryMarginPercent) -gt 200) { throw 'Batch plus retry margin exceeds 200/minute; no calls made.' }
if ($fullSeriesEstimate -gt 2000 -or $fullSeriesEstimate -gt 4000) { throw 'Estimated full-series cost exceeds hourly or daily internal limit; no calls made.' }

$pilotDir = Split-Path $pilotManifestPath -Parent
$results = [System.Collections.Generic.List[object]]::new()
$batchNumber = 0
$completedInCurrentBatch = 0
foreach ($point in $points) {
    $pointManifestPath = Join-Path $bronze "$($point.location_id)_manifest.json"
    $rawPath = Join-Path $rawDir "$($point.location_id)_${startDate}_${endDate}.json"
    if (Test-Path -LiteralPath $pointManifestPath) {
        $prior = Get-Content -LiteralPath $pointManifestPath -Raw | ConvertFrom-Json
        if ($prior.validation -eq $true -and $prior.model -eq 'era5' -and $prior.start_date -eq $startDate -and $prior.end_date -eq $endDate) {
            continue
        }
        throw "A prior ERA5 output for $($point.location_id) exists but is not a validated matching series. Inspect before overwriting; no new request made for this point."
    }

    if ($completedInCurrentBatch -eq 0) {
        $batchNumber++
        $batchResults = [System.Collections.Generic.List[object]]::new()
        $batchActualEstimate = [Math]::Min($batchSize, $points.Count - ($batchNumber - 1) * $batchSize) * $costPerPoint
        $batchPlanWithMargin = $batchActualEstimate * (1 + $retryMarginPercent)
        $counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
        if ($batchPlanWithMargin -gt [double]$counter.remaining_project_budget) { throw 'Next batch plus margin exceeds current persistent balance; stopping before request.' }
        if ($batchPlanWithMargin -gt 200) { throw 'Next batch plus margin exceeds 200/minute; stopping before request.' }
    }

    $url = "https://archive-api.open-meteo.com/v1/archive?latitude=$($point.latitude)&longitude=$($point.longitude)&start_date=$startDate&end_date=$endDate&hourly=$hourlyParameter&timezone=GMT&models=era5"
    $response = $null
    $body = ''
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 180 -UseBasicParsing
        $body = [string]$response.Content
    }
    catch {
        $statusCode = 0
        if ($_.Exception.Response) { try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {} }
        $counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
        $counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
        $counter.collection_status = if ($statusCode -eq 429) { 'stopped_429_era5_hourly' } else { 'stopped_transport_or_http_error_era5_hourly' }
        $counter.block_reason = "ERA5 hourly batch stopped at $($point.location_id), HTTP status $statusCode; no retry."
        $counter.last_updated_utc = [DateTime]::UtcNow.ToString('o')
        $counter | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $counterPath -Encoding utf8
        $failure = [ordered]@{ batch_id = ('era5_hourly_batch_{0:D3}' -f $batchNumber); model = 'era5'; models_parameter = 'era5'; endpoint = 'https://archive-api.open-meteo.com/v1/archive'; variable_api = $variables; location_id = $point.location_id; request_url = $url; http_status = $statusCode; transport_error = $_.Exception.Message; billed_calls_counted = 0; retry = $false; start_date = $startDate; end_date = $endDate }
        $failure | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $bronze "$($point.location_id)_failure_manifest.json") -Encoding utf8
        throw "Stopped at $($point.location_id), status $statusCode, no retry. Review manifests/counter before continuing."
    }

    Set-Content -LiteralPath $rawPath -Value $body -Encoding utf8
    $json = $null
    $parseError = $null
    try { $json = $body | ConvertFrom-Json -ErrorAction Stop } catch { $parseError = $_.Exception.Message }
    $times = @()
    $quality = [ordered]@{}
    $apiUnits = [ordered]@{}
    $allPresent = $true
    $allValid = $true
    if ($json) {
        $times = @($json.hourly.time)
        foreach ($variable in $variables) {
            $property = $json.hourly.PSObject.Properties[$variable]
            $values = if ($property) { @($property.Value) } else { @() }
            $unitProperty = $json.hourly_units.PSObject.Properties[$variable]
            $unit = if ($unitProperty) { [string]$unitProperty.Value } else { '' }
            $validValues = @($values | Where-Object { $null -ne $_ }).Count
            $apiUnits[$variable] = $unit
            $quality[$variable] = [ordered]@{ expected_unit = $expectedUnits[$variable]; api_unit = $unit; hours_returned = $values.Count; valid_values = $validValues; null_values = [Math]::Max(0, 17520 - $validValues); unit_match = ($unit -eq $expectedUnits[$variable]) }
            if (-not $property -or $values.Count -ne 17520 -or $unit -ne $expectedUnits[$variable]) { $allPresent = $false }
            if ($validValues -ne 17520) { $allValid = $false }
        }
    }
    $firstTime = if ($times.Count) { [string]$times[0] } else { '' }
    $lastTime = if ($times.Count) { [string]$times[-1] } else { '' }
    $timezone = if ($json) { [string]$json.timezone } else { '' }
    $isValid = ([int]$response.StatusCode -eq 200 -and $response.Headers['Content-Type'] -match 'json' -and $times.Count -eq 17520 -and $firstTime -eq '2024-10-08T00:00' -and $lastTime -eq '2026-10-07T23:00' -and $allPresent -and $allValid -and $timezone -eq 'GMT')
    $apiLatitude = if ($json) { $json.latitude } else { $null }
    $apiLongitude = if ($json) { $json.longitude } else { $null }
    $manifest = [ordered]@{
        batch_id = ('era5_hourly_batch_{0:D3}' -f $batchNumber); model = 'era5'; models_parameter = 'era5'; endpoint = 'https://archive-api.open-meteo.com/v1/archive'
        variable_api = $variables; canonical_variables = $variables; frequency = 'hourly'; timezone = 'GMT'; start_date = $startDate; end_date = $endDate; days = $days
        location_id = $point.location_id; location_name = $point.location_name; state = $point.state; macro_region = $point.macro_region
        requested_latitude = $point.latitude; requested_longitude = $point.longitude; api_latitude = $apiLatitude; api_longitude = $apiLongitude
        http_status = [int]$response.StatusCode; content_type = [string]$response.Headers['Content-Type']; hours_returned = $times.Count; first_hour = $firstTime; last_hour = $lastTime
        variable_quality = $quality; valid = $isValid; estimated_billed_calls = $costPerPoint; retry_margin_units = $costPerPoint * $retryMarginPercent
        request_url = $url; raw_file = $rawPath; parse_error = $parseError
    }
    $manifest | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $pointManifestPath -Encoding utf8

    $counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
    $counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
    $counter.completed_calls = [double]$counter.completed_calls + $costPerPoint
    $counter.remaining_project_budget = [double]$counter.budget_internal.project_total - [double]$counter.completed_calls
    if (-not ($counter.PSObject.Properties.Name -contains 'pending_era5_hourly_locations')) { $counter | Add-Member -NotePropertyName pending_era5_hourly_locations -NotePropertyValue 24 -Force }
    if ($isValid) { $counter.pending_era5_hourly_locations = [int]$counter.pending_era5_hourly_locations - 1 }
    $counter.planned_calls = [double]$counter.pending_era5_hourly_locations * $costPerPoint * (1 + $retryMarginPercent)
    $counter.collection_status = if ($isValid) { 'era5_hourly_in_progress' } else { 'era5_hourly_field_or_period_pending' }
    $counter.block_reason = if ($isValid) { "$($point.location_id) ERA5 hourly response validated." } else { "$($point.location_id) response was billed but failed validation; no retry; other independent points may continue." }
    $counter.last_updated_utc = [DateTime]::UtcNow.ToString('o')
    $counter | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $counterPath -Encoding utf8

    $batchResults.Add([pscustomobject]@{ location_id = $point.location_id; manifest = (Split-Path $pointManifestPath -Leaf); raw_file = (Split-Path $rawPath -Leaf); status = [int]$response.StatusCode; hours = $times.Count; all_fields_present = $allPresent; all_values_valid = $allValid; validation = $isValid; billed_calls = $costPerPoint })
    $batchManifest = [ordered]@{ batch_id = ('era5_hourly_batch_{0:D3}' -f $batchNumber); model = 'era5'; models_parameter = 'era5'; endpoint = 'https://archive-api.open-meteo.com/v1/archive'; variables = $variables; period_start = $startDate; period_end = $endDate; frequency = 'hourly'; timezone = 'GMT'; batch_actual_estimate = $batchActualEstimate; batch_retry_margin = $batchActualEstimate * $retryMarginPercent; points = @($batchResults); created_at_utc = [DateTime]::UtcNow.ToString('o') }
    $batchManifest | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath (Join-Path $bronze ('manifest_batch_{0:D3}.json' -f $batchNumber)) -Encoding utf8
    Write-Host "$($point.location_id): HTTP $([int]$response.StatusCode), $($times.Count) hours, valid=$isValid; billed $costPerPoint"

    $completedInCurrentBatch++
    if ($completedInCurrentBatch -ge $batchSize) {
        $completedInCurrentBatch = 0
        if ($batchNumber -lt [Math]::Ceiling($points.Count / $batchSize)) { Start-Sleep -Seconds 60 }
    }
    if (-not $isValid) { continue }
}

$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
if ([int]$counter.pending_era5_hourly_locations -eq 0) {
    $counter.collection_status = 'era5_hourly_complete_in_bronze_pending_prata_ouro'
    $counter.block_reason = 'All 24 ERA5 hourly point series validated in Bronze; Prata/Ouro materialization remains.'
    $counter.planned_calls = 0
}
$counter.last_updated_utc = [DateTime]::UtcNow.ToString('o')
$counter | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $counterPath -Encoding utf8
$results | Format-Table -AutoSize
Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json | Select-Object completed_calls, remaining_project_budget, api_requests_attempted, retries, pending_era5_hourly_locations, planned_calls, collection_status | Format-List
