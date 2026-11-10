param(
 [Parameter(Mandatory=$true)]
 [ValidateSet('BR_AL_MACEIO','BR_BA_BARREIRAS','BR_CE_FORTALEZA','BR_MA_BALSAS','BR_PB_JOAO_PESSOA','BR_PE_PETROLINA','BR_PI_URUCUI','BR_RN_MOSSORO','BR_SE_ARACAJU','BR_ES_LINHARES','BR_MG_MONTES_CLAROS','BR_RJ_CAMPOS_GOYTACAZES','BR_SP_RIBEIRAO_PRETO','BR_PR_LONDRINA','BR_RS_PASSO_FUNDO','BR_SC_CHAPECO')]
 [string]$LocationId
)
$ErrorActionPreference='Stop'
$root='C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$counterPath=Join-Path $root '1_bronze\auditoria\contador_chamadas.json'
$rawDir=Join-Path $root '1_bronze\era5\variables_horarias\raw\national_expansion'
$manifestDir=Join-Path $root '1_bronze\era5\variables_horarias\manifests\national_expansion'
$locations=@{
 'BR_AL_MACEIO'=@{name='Maceió';state='AL';region='Nordeste';lat=-9.6658;lon=-35.7351}
 'BR_BA_BARREIRAS'=@{name='Barreiras (MATOPIBA)';state='BA';region='Nordeste';lat=-12.1528;lon=-44.9961}
 'BR_CE_FORTALEZA'=@{name='Fortaleza';state='CE';region='Nordeste';lat=-3.7327;lon=-38.527}
 'BR_MA_BALSAS'=@{name='Balsas (MATOPIBA)';state='MA';region='Nordeste';lat=-7.5322;lon=-46.0356}
 'BR_PB_JOAO_PESSOA'=@{name='João Pessoa';state='PB';region='Nordeste';lat=-7.1195;lon=-34.845}
 'BR_PE_PETROLINA'=@{name='Petrolina (Irrigação São Francisco)';state='PE';region='Nordeste';lat=-9.3891;lon=-40.5027}
 'BR_PI_URUCUI'=@{name='Uruçuí (MATOPIBA)';state='PI';region='Nordeste';lat=-7.2289;lon=-44.5561}
 'BR_RN_MOSSORO'=@{name='Mossoró (Fruticultura Tropical)';state='RN';region='Nordeste';lat=-5.188;lon=-37.3441}
 'BR_SE_ARACAJU'=@{name='Aracaju';state='SE';region='Nordeste';lat=-10.9472;lon=-37.0731}
 'BR_ES_LINHARES'=@{name='Linhares (Norte do ES)';state='ES';region='Sudeste';lat=-19.3967;lon=-40.0639}
 'BR_MG_MONTES_CLAROS'=@{name='Montes Claros (Norte de MG)';state='MG';region='Sudeste';lat=-16.7281;lon=-43.8617}
 'BR_RJ_CAMPOS_GOYTACAZES'=@{name='Campos dos Goytacazes';state='RJ';region='Sudeste';lat=-21.7544;lon=-41.3244}
 'BR_SP_RIBEIRAO_PRETO'=@{name='Ribeirão Preto (Polo Canavieiro)';state='SP';region='Sudeste';lat=-21.1775;lon=-47.8103}
 'BR_PR_LONDRINA'=@{name='Londrina (Norte Pioneiro)';state='PR';region='Sul';lat=-23.3045;lon=-51.1696}
 'BR_RS_PASSO_FUNDO'=@{name='Passo Fundo (Planalto Médio RS)';state='RS';region='Sul';lat=-28.2612;lon=-52.4083}
 'BR_SC_CHAPECO'=@{name='Chapecó (Oeste Catarinense / Agro)';state='SC';region='Sul';lat=-27.1004;lon=-52.6152}
}
$fields=@('temperature_2m','dew_point_2m','relative_humidity_2m','vapour_pressure_deficit','soil_moisture_0_to_7cm','soil_moisture_7_to_28cm','soil_moisture_28_to_100cm','soil_moisture_100_to_255cm','soil_temperature_0_to_7cm','soil_temperature_7_to_28cm','soil_temperature_28_to_100cm','soil_temperature_100_to_255cm')
$expectedUnits=@{'temperature_2m'='°C';'dew_point_2m'='°C';'relative_humidity_2m'='%';'vapour_pressure_deficit'='kPa';'soil_moisture_0_to_7cm'='m³/m³';'soil_moisture_7_to_28cm'='m³/m³';'soil_moisture_28_to_100cm'='m³/m³';'soil_moisture_100_to_255cm'='m³/m³';'soil_temperature_0_to_7cm'='°C';'soil_temperature_7_to_28cm'='°C';'soil_temperature_28_to_100cm'='°C';'soil_temperature_100_to_255cm'='°C'}
function Set-CounterProperty([string]$Name,[object]$Value){
 if($counter.PSObject.Properties[$Name]){$counter.$Name=$Value}
 else{$counter|Add-Member -MemberType NoteProperty -Name $Name -Value $Value -Force}
}
$counter=Get-Content -LiteralPath $counterPath -Raw|ConvertFrom-Json
$pointCost=(730.0/14.0)*(12.0/10.0)
$pointReserve=$pointCost*0.20
$balance=[double]$counter.remaining_project_budget
if([math]::Abs(([double]$counter.completed_calls+$balance)-8000.0) -gt 0.02){throw 'Contador não reconcilia com teto 8.000.'}
$done=@();if($counter.PSObject.Properties['era5_hourly_national_completed_locations']){$done=@($counter.era5_hourly_national_completed_locations)}
$attempted=@();if($counter.PSObject.Properties['era5_hourly_national_attempted_locations']){$attempted=@($counter.era5_hourly_national_attempted_locations)}
if($LocationId -in $done -or $LocationId -in $attempted){throw "Localidade já coletada/tentada; não repetir: $LocationId"}
$remainingIds=@($locations.Keys|Where-Object {$_ -notin $done -and $_ -notin $attempted})
$projectedReserve=$remainingIds.Count*$pointCost*1.20
if($balance -lt $projectedReserve){throw "Saldo não cobre todas as séries restantes com margem: saldo=$balance projeção=$projectedReserve"}
if(($pointCost+$pointReserve) -gt 200 -or $pointCost -gt 2000 -or ($remainingIds.Count*$pointCost) -gt 4000){throw 'Estimativa excede limite interno por minuto/hora/dia.'}
$location=$locations[$LocationId]
Resolve-DnsName archive-api.open-meteo.com -ErrorAction Stop|Out-Null
$tcp=Test-NetConnection archive-api.open-meteo.com -Port 443 -WarningAction SilentlyContinue
if(-not $tcp.TcpTestSucceeded){throw 'TCP/443 falhou; nenhum pedido API foi feito.'}
New-Item -ItemType Directory -Path $rawDir -Force|Out-Null
New-Item -ItemType Directory -Path $manifestDir -Force|Out-Null
$rawPath=Join-Path $rawDir ($LocationId+'_2024-10-08_2026-10-07.json')
$manifestPath=Join-Path $manifestDir ($LocationId+'_2024-10-08_2026-10-07.manifest.json')
$errorPath=Join-Path $manifestDir ($LocationId+'_2024-10-08_2026-10-07.http_error.txt')
if((Test-Path -LiteralPath $rawPath) -or (Test-Path -LiteralPath $manifestPath) -or (Test-Path -LiteralPath $errorPath)){throw "Arquivo de saída já existe; não sobrescrever: $LocationId"}
$hourly=[uri]::EscapeDataString(($fields -join ','))
$url="https://archive-api.open-meteo.com/v1/archive?latitude=$($location.lat)&longitude=$($location.lon)&start_date=2024-10-08&end_date=2026-10-07&hourly=$hourly&timezone=GMT&models=era5"
Write-Output "Prévia: $LocationId; 730 dias; 12 campos; custo estimado=$([math]::Round($pointCost,4)); margem=$([math]::Round($pointReserve,4)); saldo=$balance; reserva das $($remainingIds.Count) séries pendentes=$([math]::Round($projectedReserve,4)); saldo conservador após completar=$([math]::Round(($balance-$projectedReserve),4))"
$lastProperty=$counter.PSObject.Properties['last_project_api_response_utc']
if($lastProperty){$lastTime=[datetime]::Parse($lastProperty.Value).ToUniversalTime();$elapsed=((Get-Date).ToUniversalTime()-$lastTime).TotalSeconds;$waitSeconds=[math]::Ceiling(30-$elapsed);if($waitSeconds -gt 0){Write-Output "Aguardando $waitSeconds segundos para respeitar o limite por minuto.";Start-Sleep -Seconds $waitSeconds}}
try{$response=Invoke-WebRequest -Uri $url -TimeoutSec 300 -UseBasicParsing}
catch{
 $httpStatus=$null
 if($_.Exception.Response){try{$httpStatus=[int]$_.Exception.Response.StatusCode}catch{}}
 if($httpStatus){
   $body=''
   try{$reader=New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream());$body=$reader.ReadToEnd();$reader.Dispose()}catch{}
   $body|Set-Content -LiteralPath $errorPath -Encoding utf8
   $attempted+=@($LocationId)
   Set-CounterProperty 'api_requests_attempted' ([int]$counter.api_requests_attempted+1)
   Set-CounterProperty 'completed_calls' ([double]$counter.completed_calls+$pointCost)
   Set-CounterProperty 'remaining_project_budget' (8000.0-[double]$counter.completed_calls)
   Set-CounterProperty 'era5_hourly_national_attempted_locations' $attempted
   Set-CounterProperty 'last_project_api_response_utc' (Get-Date).ToUniversalTime().ToString('o')
   Set-CounterProperty 'block_reason' "HTTP $httpStatus; estimated cost conservatively counted; no retry"
   Set-CounterProperty 'last_updated_utc' (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
   $counter|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $counterPath -Encoding utf8
   if($httpStatus -eq 429){throw 'HTTP 429: lote parado, custo estimado debitado conservadoramente, sem retry automático.'}
 }
 throw "Pedido falhou (HTTP $httpStatus); sem retry automático. $($_.Exception.Message)"
}
$response.Content|Set-Content -LiteralPath $rawPath -Encoding utf8
Set-CounterProperty 'api_requests_attempted' ([int]$counter.api_requests_attempted+1)
Set-CounterProperty 'completed_calls' ([double]$counter.completed_calls+$pointCost)
Set-CounterProperty 'remaining_project_budget' (8000.0-[double]$counter.completed_calls)
Set-CounterProperty 'last_updated_utc' (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$attempted+=@($LocationId)
Set-CounterProperty 'era5_hourly_national_attempted_locations' $attempted
Set-CounterProperty 'last_project_api_response_utc' (Get-Date).ToUniversalTime().ToString('o')
$counter|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $counterPath -Encoding utf8
try{$data=$response.Content|ConvertFrom-Json}
catch{
 $manifest=[ordered]@{location_id=$LocationId;model='era5';period='2024-10-08/2026-10-07';http_status=[int]$response.StatusCode;validation_status='invalid_non_json';estimated_calls=$pointCost;retry_margin_reserved=$pointReserve;raw_file=$rawPath}
 $manifest|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $manifestPath -Encoding utf8
 throw 'Resposta não JSON; custo estimado registrado, sem retry automático.'
}
$missing=@($fields|Where-Object {$data.hourly.PSObject.Properties.Name -notcontains $_})
$wrongLength=@($fields|Where-Object {$null -eq $data.hourly.$_ -or $data.hourly.$_.Count -ne 17520})
$nullFields=@($fields|Where-Object {$field=$_;@($data.hourly.$field|Where-Object {$null -eq $_}).Count -gt 0})
$wrongUnits=@($fields|Where-Object {$data.hourly_units.$_ -ne $expectedUnits[$_]})
$timeOk=($data.hourly.time.Count -eq 17520 -and $data.hourly.time[0] -eq '2024-10-08T00:00' -and $data.hourly.time[-1] -eq '2026-10-07T23:00')
$valid=($response.StatusCode -eq 200 -and $missing.Count -eq 0 -and $wrongLength.Count -eq 0 -and $nullFields.Count -eq 0 -and $wrongUnits.Count -eq 0 -and $timeOk)
$manifest=[ordered]@{endpoint='/v1/archive';models='era5';location_id=$LocationId;location_name=$location.name;state=$location.state;macro_region=$location.region;requested_latitude=$location.lat;requested_longitude=$location.lon;returned_latitude=$data.latitude;returned_longitude=$data.longitude;start_date='2024-10-08';end_date='2026-10-07';timezone='GMT';http_status=[int]$response.StatusCode;fields=$fields;hour_count=$data.hourly.time.Count;first_timestamp=$data.hourly.time[0];last_timestamp=$data.hourly.time[-1];hourly_units=$data.hourly_units;missing_fields=$missing;wrong_length_fields=$wrongLength;null_fields=$nullFields;wrong_units=$wrongUnits;validation_status=$(if($valid){'valid'}else{'incomplete_pending'});estimated_calls=$pointCost;retry_margin_reserved=$pointReserve;raw_file=$rawPath}
$manifest|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $manifestPath -Encoding utf8
if($valid){$done+=@($LocationId);Set-CounterProperty 'era5_hourly_national_completed_locations' $done;Set-CounterProperty 'collection_status' 'era5_hourly_national_expansion_in_progress'}
else{Set-CounterProperty 'collection_status' 'era5_hourly_national_expansion_has_pending_point'}
$nextRemaining=@($locations.Keys|Where-Object {$_ -notin $done -and $_ -notin $attempted})
Set-CounterProperty 'planned_calls' ($nextRemaining.Count*$pointCost)
Set-CounterProperty 'last_updated_utc' (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$counter|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $counterPath -Encoding utf8
[pscustomobject]@{HttpStatus=[int]$response.StatusCode;ModelsParameter='era5';LocationId=$LocationId;State=$location.state;Region=$location.region;Hours=$data.hourly.time.Count;First=$data.hourly.time[0];Last=$data.hourly.time[-1];MissingFields=($missing -join ',');NullFields=($nullFields -join ',');WrongLengthFields=($wrongLength -join ',');WrongUnits=($wrongUnits -join ',');Validated=$valid;EstimatedCalls=$pointCost;RetryReserve=$pointReserve;CompletedCalls=$counter.completed_calls;Remaining=$counter.remaining_project_budget;RawFile=$rawPath;Manifest=$manifestPath}|Format-List
if(-not $valid){throw 'Ponto incompleto marcado no manifest; sem retry automático. Continue localidades independentes.'}