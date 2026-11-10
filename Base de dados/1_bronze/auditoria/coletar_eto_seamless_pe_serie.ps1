$ErrorActionPreference = 'Stop'
$base = 'C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$counterPath = Join-Path $base '1_bronze\auditoria\contador_chamadas.json'
$locationManifestPath = Join-Path $base '1_bronze\era5\variables_horarias\manifests\national_expansion\BR_PE_PETROLINA_2024-10-08_2026-10-07.manifest.json'
$rawDir = Join-Path $base '1_bronze\era5_seamless_eto\raw'
$manifestDir = Join-Path $base '1_bronze\era5_seamless_eto'
$silverDir = Join-Path $base '2_prata\regional'
$goldDir = Join-Path $base '3_ouro\regional\era5_seamless'
$locationId = 'BR_PE_PETROLINA'
$startDate = '2024-10-08'; $endDate = '2026-10-07'
$model = 'era5_seamless'; $variable = 'et0_fao_evapotranspiration'
$estimate = 730.0 / 14.0; $margin = $estimate * 0.20
$counter = Get-Content -LiteralPath $counterPath -Raw | ConvertFrom-Json
if ($counter.PSObject.Properties['eto_seamless_pe_full']) { throw 'A série PE já foi tentada/registrada. Não repetir automaticamente.' }
$loc = Get-Content -LiteralPath $locationManifestPath -Raw | ConvertFrom-Json
if ($loc.location_id -ne $locationId -or $loc.models -ne 'era5') { throw 'Manifesto de localização/modelo incompatível.' }
$balance = [double]$counter.remaining_project_budget
if (($estimate + $margin) -gt $balance) { throw "Saldo insuficiente: lote+margem=$($estimate+$margin); saldo=$balance" }
$rawPath = Join-Path $rawDir 'BR_PE_PETROLINA_2024-10-08_2026-10-07.json'
$manifestPath = Join-Path $manifestDir 'BR_PE_PETROLINA_2024-10-08_2026-10-07.manifest.json'
$silverPath = Join-Path $silverDir 'eto_seamless_expansao_BR_PE_PETROLINA_2024-10-08_2026-10-07.csv'
$goldPath = Join-Path $goldDir 'eto_seamless_expansao_BR_PE_PETROLINA_2024-10-08_2026-10-07.csv'
if ((Test-Path -LiteralPath $rawPath) -or (Test-Path -LiteralPath $manifestPath) -or (Test-Path -LiteralPath $goldPath)) { throw 'Artefato da série BA já existe; não sobrescrever.' }
try {
    Resolve-DnsName archive-api.open-meteo.com -ErrorAction Stop | Out-Null
    $tcp = Test-NetConnection archive-api.open-meteo.com -Port 443 -WarningAction SilentlyContinue
    if (-not $tcp.TcpTestSucceeded) { throw 'Pré-verificação TCP 443 falhou; nenhum pedido HTTP foi feito.' }
} catch { Write-Error "Pré-verificação falhou; nenhum pedido HTTP foi feito: $($_.Exception.Message)"; exit 2 }
$uri = "https://archive-api.open-meteo.com/v1/archive?latitude=$($loc.requested_latitude)&longitude=$($loc.requested_longitude)&start_date=$startDate&end_date=$endDate&daily=$variable&timezone=GMT&models=$model"
$record = [pscustomobject]@{
    model=$model; endpoint='/v1/archive'; location_id=$locationId; status='in_progress'
    estimated_calls=$estimate; retry_margin=$margin; billed_calls_counted=0
    http_status=$null; raw_file=$rawPath; manifest=$manifestPath; silver_file=$silverPath; gold_file=$goldPath
    valid_days=0; null_values=$null; error=$null
}
$counter | Add-Member -NotePropertyName eto_seamless_pe_full -Force -NotePropertyValue $record
$counter.api_requests_attempted = [int]$counter.api_requests_attempted + 1
$counter.planned_calls = $estimate
$counter.collection_status = 'eto_seamless_pe_full_in_progress'
$counter | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $counterPath -Encoding utf8
$httpStatus=$null; $contentType=$null; $json=$null; $errorText=$null; $status='transport_error'
try {
    $response=Invoke-WebRequest -Uri $uri -TimeoutSec 300 -UseBasicParsing
    $httpStatus=[int]$response.StatusCode; $contentType=[string]$response.Headers['Content-Type']
    $rawText=[string]$response.Content
    Set-Content -LiteralPath $rawPath -Value $rawText -Encoding utf8
    if ($httpStatus -eq 429) { $status='http_429_no_retry' }
    elseif ($httpStatus -ne 200) { $status='http_error_no_retry' }
    else {
        try {
            $json=$rawText|ConvertFrom-Json -ErrorAction Stop
            $times=@($json.daily.time); $values=@($json.daily.$variable)
            $nulls=@($values|Where-Object {$null -eq $_}).Count
            $status='invalid_response_no_retry'
            if ($times.Count -eq 730 -and $times[0] -eq $startDate -and $times[-1] -eq $endDate -and $values.Count -eq 730 -and $nulls -eq 0 -and $json.daily_units.$variable -eq 'mm' -and $json.timezone -eq 'GMT') { $status='validated' }
        } catch { $status='invalid_json_no_retry'; $errorText=$_.Exception.Message }
    }
} catch {
    $errorText=$_.Exception.Message
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) { $httpStatus=[int]$_.Exception.Response.StatusCode;if($httpStatus -eq 429){$status='http_429_no_retry'}else{$status='http_error_no_retry'} }
}
$counter.completed_calls=[double]$counter.completed_calls+$estimate
$counter.remaining_project_budget=8000-[double]$counter.completed_calls
$counter.planned_calls=0
$counter.last_project_api_response_utc=(Get-Date).ToUniversalTime().ToString('o')
$counter.last_updated_utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$record.status=$status;$record.http_status=$httpStatus;$record.billed_calls_counted=$estimate;$record.valid_days=$(if($json){@($json.daily.time).Count}else{0});$record.null_values=$(if($json){$nulls}else{$null});$record.error=$errorText
$counter.collection_status="eto_seamless_pe_full_$status"
$counter|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $counterPath -Encoding utf8
$manifest=[ordered]@{
    endpoint='/v1/archive';models=$model;location_id=$locationId;location_name=$loc.location_name;state=$loc.state;macro_region=$loc.macro_region
    requested_latitude=$loc.requested_latitude;requested_longitude=$loc.requested_longitude
    start_date=$startDate;end_date=$endDate;timezone='GMT';daily_variable=$variable
    http_status=$httpStatus;content_type=$contentType;validation_status=$status
    days_returned=$(if($json){@($json.daily.time).Count}else{0})
    first_date=$(if($json -and @($json.daily.time).Count){$json.daily.time[0]}else{$null})
    last_date=$(if($json -and @($json.daily.time).Count){$json.daily.time[-1]}else{$null})
    unit=$(if($json){$json.daily_units.$variable}else{$null})
    valid_values=$(if($json){@($json.daily.$variable|Where-Object {$null -ne $_}).Count}else{0})
    null_values=$(if($json){$nulls}else{$null})
    api_latitude=$(if($json){$json.latitude}else{$null});api_longitude=$(if($json){$json.longitude}else{$null})
    estimated_calls=$estimate;retry_margin_reserved=$margin;billed_calls_counted=$estimate
    raw_file=$rawPath;request_url=$uri;transport_error=$errorText
}
$manifest|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $manifestPath -Encoding utf8
if ($status -eq 'validated') {
    $outputRows=for($i=0;$i -lt 730;$i++){
        [pscustomobject]@{date=$json.daily.time[$i];location_id=$locationId;location_name=$loc.location_name;state=$loc.state;macro_region=$loc.macro_region;timezone='GMT';latitude=$loc.requested_latitude;longitude=$loc.requested_longitude;api_latitude=$json.latitude;api_longitude=$json.longitude;eto_mm=$json.daily.$variable[$i];unit='mm/day';source_model=$model;source_file=[System.IO.Path]::GetFileName($rawPath);quality_flag='valid'}
    }
    $outputRows|Export-Csv -LiteralPath $silverPath -NoTypeInformation -Delimiter ';' -Encoding utf8
    $outputRows|Export-Csv -LiteralPath $goldPath -NoTypeInformation -Delimiter ';' -Encoding utf8
    $coveragePath=Join-Path $base '3_ouro\auditoria_cobertura_por_variavel_uf.csv'
    $coverage=Import-Csv -LiteralPath $coveragePath -Delimiter ';'
    foreach($row in $coverage){if($row.model -eq 'era5_seamless' -and $row.variable -eq 'eto_mm' -and $row.state -eq 'PE'){$row.product='eto';$row.locations=1;$row.rows=730;$row.valid_values=730;$row.null_values=0;$row.frequency='daily_GMT';$row.status='validated';$row.provenance='Bronze raw/manifest; Prata and Gold point series'}}
    $coverage|Export-Csv -LiteralPath $coveragePath -NoTypeInformation -Delimiter ';' -Encoding utf8
    $counter.pending_eto_locations=[int]$counter.pending_eto_locations-1
    $counter.pending_work_estimate.pending_locations=[int]$counter.pending_eto_locations
    $counter.pending_work_estimate.locations=[int]$counter.pending_work_estimate.locations+1
    $counter.pending_work_estimate.states=[int]$counter.pending_work_estimate.states+1
    $counter.pending_work_estimate.pending_uncovered_states=@($counter.pending_work_estimate.pending_uncovered_states|Where-Object {$_ -ne 'PE'})
    $counter.pending_work_estimate.full_series_estimate=[double]$counter.pending_eto_locations*$estimate
    $counter.pending_work_estimate.estimated_calls=$counter.pending_work_estimate.full_series_estimate
    $counter.pending_work_estimate.retry_margin=$counter.pending_work_estimate.full_series_estimate*0.20
    $counter.pending_work_estimate.estimate_with_margin=$counter.pending_work_estimate.full_series_estimate*1.20
    $counter.pending_work_estimate.collection_status="partial: $($counter.pending_work_estimate.locations) localities / $($counter.pending_work_estimate.states) UFs; PE added; $($counter.pending_eto_locations) UFs uncovered"
    $counter.data_products.eto_era5_seamless="partial: $($counter.pending_work_estimate.locations) localities, $($counter.pending_work_estimate.states) UFs; $($counter.pending_eto_locations) UFs uncovered"
    $counter.collection_status='eto_seamless_pe_full_validated'
    $counter.last_updated_utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $counter|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $counterPath -Encoding utf8
}
[pscustomobject]@{HttpStatus=$httpStatus;Model=$model;Location=$locationId;Validated=($status -eq 'validated');Days=$(if($json){@($json.daily.time).Count}else{0});Nulls=$(if($json){$nulls}else{$null});EstimatedCalls=$estimate;RetryReserve=$margin;CompletedCalls=$counter.completed_calls;Remaining=$counter.remaining_project_budget;Status=$status;Raw=$rawPath;Manifest=$manifestPath;Silver=$silverPath;Gold=$goldPath;Error=$errorText}
if ($status -ne 'validated') { exit 3 }