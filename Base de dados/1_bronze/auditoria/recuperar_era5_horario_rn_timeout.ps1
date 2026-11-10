$ErrorActionPreference='Stop'
$root='C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$counterPath=Join-Path $root '1_bronze\auditoria\contador_chamadas.json'
$timeoutPath=Join-Path $root '1_bronze\auditoria\pendencias\timeout_BR_RN_MOSSORO_2026-11-08.json'
$rawDir=Join-Path $root '1_bronze\era5\variables_horarias\raw\national_expansion'
$manifestDir=Join-Path $root '1_bronze\era5\variables_horarias\manifests\national_expansion'
$id='BR_RN_MOSSORO'
$pointCost=(730.0/14.0)*(12.0/10.0)
$reserve=$pointCost*0.20
$counter=Get-Content -LiteralPath $counterPath -Raw|ConvertFrom-Json
$timeout=Get-Content -LiteralPath $timeoutPath -Raw|ConvertFrom-Json
if($timeout.response_received -ne $false -or $timeout.status -ne 'other_points_ready_timeout_point_pending'){throw 'O registro não corresponde ao timeout pendente esperado.'}
if($timeout.PSObject.Properties['manual_followup_attempted'] -and $timeout.manual_followup_attempted){throw 'A recuperação manual já foi tentada; não repetir automaticamente.'}
if([math]::Abs(([double]$counter.completed_calls+[double]$counter.remaining_project_budget)-8000.0) -gt 0.02){throw 'Contador não reconcilia com teto 8.000.'}
if([double]$counter.remaining_project_budget -lt ($pointCost+$reserve)){throw 'Saldo insuficiente para uma tentativa de recuperação com margem.'}
if(($pointCost+$reserve) -gt 200 -or $pointCost -gt 2000 -or $pointCost -gt 4000){throw 'Recuperação excede limite interno.'}
$rawPath=Join-Path $rawDir 'BR_RN_MOSSORO_2024-10-08_2026-10-07.json'
$manifestPath=Join-Path $manifestDir 'BR_RN_MOSSORO_2024-10-08_2026-10-07.manifest.json'
$errorPath=Join-Path $manifestDir 'BR_RN_MOSSORO_recovery_http_error.txt'
if((Test-Path -LiteralPath $rawPath) -or (Test-Path -LiteralPath $manifestPath) -or (Test-Path -LiteralPath $errorPath)){throw 'Já existe resposta ou manifest para RN; não sobrescrever.'}
Resolve-DnsName archive-api.open-meteo.com -ErrorAction Stop|Out-Null
$tcp=Test-NetConnection archive-api.open-meteo.com -Port 443 -WarningAction SilentlyContinue
if(-not $tcp.TcpTestSucceeded){throw 'TCP/443 falhou; nenhum pedido API foi feito.'}
$timeout|Add-Member -MemberType NoteProperty -Name manual_followup_attempted -Value $true -Force
$timeout|Add-Member -MemberType NoteProperty -Name manual_followup_started_utc -Value (Get-Date).ToUniversalTime().ToString('o') -Force
$timeout.status='manual_recovery_in_progress_after_dns_tcp_pass'
$timeout|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $timeoutPath -Encoding utf8
$fields=@('temperature_2m','dew_point_2m','relative_humidity_2m','vapour_pressure_deficit','soil_moisture_0_to_7cm','soil_moisture_7_to_28cm','soil_moisture_28_to_100cm','soil_moisture_100_to_255cm','soil_temperature_0_to_7cm','soil_temperature_7_to_28cm','soil_temperature_28_to_100cm','soil_temperature_100_to_255cm')
$units=@{'temperature_2m'='°C';'dew_point_2m'='°C';'relative_humidity_2m'='%';'vapour_pressure_deficit'='kPa';'soil_moisture_0_to_7cm'='m³/m³';'soil_moisture_7_to_28cm'='m³/m³';'soil_moisture_28_to_100cm'='m³/m³';'soil_moisture_100_to_255cm'='m³/m³';'soil_temperature_0_to_7cm'='°C';'soil_temperature_7_to_28cm'='°C';'soil_temperature_28_to_100cm'='°C';'soil_temperature_100_to_255cm'='°C'}
$hourly=[uri]::EscapeDataString(($fields -join ','))
$url="https://archive-api.open-meteo.com/v1/archive?latitude=-5.188&longitude=-37.3441&start_date=2024-10-08&end_date=2026-10-07&hourly=$hourly&timezone=GMT&models=era5"
Write-Output "Recuperação manual única RN; models=era5; custo=$([math]::Round($pointCost,4)); margem=$([math]::Round($reserve,4)); saldo=$($counter.remaining_project_budget); saldo conservador após lote=$([math]::Round(([double]$counter.remaining_project_budget-$pointCost-$reserve),4))."
try{$response=Invoke-WebRequest -Uri $url -TimeoutSec 300 -UseBasicParsing}
catch{
    $status=$null;$body=''
    if($_.Exception.Response){try{$status=[int]$_.Exception.Response.StatusCode;$reader=New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream());$body=$reader.ReadToEnd();$reader.Dispose()}catch{}}
    if($body){$body|Set-Content -LiteralPath $errorPath -Encoding utf8}else{"HTTP status=$status; exception=$($_.Exception.Message)"|Set-Content -LiteralPath $errorPath -Encoding utf8}
    $counter.api_requests_attempted=[int]$counter.api_requests_attempted+1
    $counter.completed_calls=[double]$counter.completed_calls+$pointCost
    $counter.remaining_project_budget=8000.0-[double]$counter.completed_calls
    $counter.last_updated_utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $counter.block_reason="Manual RN recovery failed/timed out; estimated cost counted conservatively; no further retry."
    $counter.collection_status='era5_hourly_rn_recovery_failed_pending'
    $counter|ConvertTo-Json -Depth 24|Set-Content -LiteralPath $counterPath -Encoding utf8
    $timeout.status='manual_recovery_failed_or_timed_out'
    $timeout|Add-Member -MemberType NoteProperty -Name manual_followup_http_status -Value $status -Force
    $timeout|Add-Member -MemberType NoteProperty -Name manual_followup_error -Value $_.Exception.Message -Force
    $timeout|Add-Member -MemberType NoteProperty -Name manual_followup_cost_provisionally_counted -Value $pointCost -Force
    $timeout|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $timeoutPath -Encoding utf8
    if($status -eq 429){throw 'HTTP 429: tentativa debitada conservadoramente; sem novo retry.'}
    throw "Recuperação RN falhou/timeout; tentativa debitada conservadoramente; sem novo retry. $($_.Exception.Message)"
}
$response.Content|Set-Content -LiteralPath $rawPath -Encoding utf8
$counter.api_requests_attempted=[int]$counter.api_requests_attempted+1
$counter.completed_calls=[double]$counter.completed_calls+$pointCost
$counter.remaining_project_budget=8000.0-[double]$counter.completed_calls
$counter.last_updated_utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$counter|ConvertTo-Json -Depth 24|Set-Content -LiteralPath $counterPath -Encoding utf8
try{$data=$response.Content|ConvertFrom-Json}catch{
    $manifest=[ordered]@{location_id=$id;model='era5';period='2024-10-08/2026-10-07';http_status=[int]$response.StatusCode;validation_status='invalid_non_json';estimated_calls=$pointCost;retry_margin_reserved=$reserve;raw_file=$rawPath}
    $manifest|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $manifestPath -Encoding utf8
    $timeout.status='manual_recovery_received_non_json'
    $timeout|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $timeoutPath -Encoding utf8
    $counter.collection_status='era5_hourly_rn_recovery_invalid_response'
    $counter.block_reason='RN recovery returned non-JSON; no retry allowed.'
    $counter|ConvertTo-Json -Depth 24|Set-Content -LiteralPath $counterPath -Encoding utf8
    throw 'Resposta não JSON; tentativa debitada, sem novo retry.'
}
$missing=@($fields|Where-Object {$data.hourly.PSObject.Properties.Name -notcontains $_})
$wrongLength=@($fields|Where-Object {$null -eq $data.hourly.$_ -or $data.hourly.$_.Count -ne 17520})
$nullFields=@($fields|Where-Object {$field=$_;@($data.hourly.$field|Where-Object {$null -eq $_}).Count -gt 0})
$wrongUnits=@($fields|Where-Object {$data.hourly_units.$_ -ne $units[$_]})
$timeOk=($data.hourly.time.Count -eq 17520 -and $data.hourly.time[0] -eq '2024-10-08T00:00' -and $data.hourly.time[-1] -eq '2026-10-07T23:00')
$valid=($response.StatusCode -eq 200 -and $missing.Count -eq 0 -and $wrongLength.Count -eq 0 -and $nullFields.Count -eq 0 -and $wrongUnits.Count -eq 0 -and $timeOk)
$manifest=[ordered]@{endpoint='/v1/archive';models='era5';location_id=$id;location_name='Mossoró (Fruticultura Tropical)';state='RN';macro_region='Nordeste';requested_latitude=-5.188;requested_longitude=-37.3441;returned_latitude=$data.latitude;returned_longitude=$data.longitude;start_date='2024-10-08';end_date='2026-10-07';timezone='GMT';http_status=[int]$response.StatusCode;fields=$fields;hour_count=$data.hourly.time.Count;first_timestamp=$data.hourly.time[0];last_timestamp=$data.hourly.time[-1];hourly_units=$data.hourly_units;missing_fields=$missing;wrong_length_fields=$wrongLength;null_fields=$nullFields;wrong_units=$wrongUnits;validation_status=$(if($valid){'valid'}else{'incomplete_pending'});estimated_calls=$pointCost;retry_margin_reserved=$reserve;raw_file=$rawPath;context='Single manual follow-up after prior timeout without response; prior timeout cost was already provisionally counted.'}
$manifest|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $manifestPath -Encoding utf8
$timeout|Add-Member -MemberType NoteProperty -Name manual_followup_http_status -Value ([int]$response.StatusCode) -Force
$timeout|Add-Member -MemberType NoteProperty -Name manual_followup_cost_counted -Value $pointCost -Force
$timeout|Add-Member -MemberType NoteProperty -Name manual_followup_validation_status -Value $manifest.validation_status -Force
$timeout.status=$(if($valid){'recovery_validated'}else{'recovery_incomplete_pending'})
$timeout|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $timeoutPath -Encoding utf8
if($valid){
    $done=@();if($counter.PSObject.Properties['era5_hourly_national_completed_locations']){$done=@($counter.era5_hourly_national_completed_locations)}
    if($id -notin $done){$done+=@($id)}
    $counter|Add-Member -MemberType NoteProperty -Name era5_hourly_national_completed_locations -Value $done -Force
    $counter.collection_status='era5_hourly_expansion_complete_all_16_target_states'
    $counter.block_reason='No pending ERA5 hourly expansion points; RN timeout recovery validated.'
    $counter.planned_calls=0
}else{
    $counter.collection_status='era5_hourly_rn_recovery_incomplete_pending'
    $counter.block_reason='RN recovery response had missing/null/invalid fields; no retry.'
    $counter.planned_calls=0
}
$counter.last_updated_utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$counter|ConvertTo-Json -Depth 24|Set-Content -LiteralPath $counterPath -Encoding utf8
[pscustomobject]@{HttpStatus=[int]$response.StatusCode;ModelsParameter='era5';LocationId=$id;Hours=$data.hourly.time.Count;First=$data.hourly.time[0];Last=$data.hourly.time[-1];MissingFields=($missing -join ',');NullFields=($nullFields -join ',');WrongLengthFields=($wrongLength -join ',');WrongUnits=($wrongUnits -join ',');Validated=$valid;EstimatedCalls=$pointCost;RetryReserve=$reserve;CompletedCalls=$counter.completed_calls;Remaining=$counter.remaining_project_budget;RawFile=$rawPath;Manifest=$manifestPath}|Format-List
if($valid){
    $syncScript=Join-Path $root '1_bronze\auditoria\coletar_era5_horario_ufs_pendentes.ps1'
    & $syncScript
}
if(-not $valid){throw 'RN permanece incompleto; resposta preservada e não haverá retry automático.'}