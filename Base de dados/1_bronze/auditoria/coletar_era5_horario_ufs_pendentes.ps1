$ErrorActionPreference='Stop'
$root='C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados'
$counterPath=Join-Path $root '1_bronze\auditoria\contador_chamadas.json'
$onePointScript=Join-Path $root '1_bronze\auditoria\coletar_era5_horario_ponto.ps1'
$manifestDir=Join-Path $root '1_bronze\era5\variables_horarias\manifests\national_expansion'
$rawDir=Join-Path $root '1_bronze\era5\variables_horarias\raw\national_expansion'
$silverDir=Join-Path $root '2_prata\regional\era5_horario_expansao_nacional'
$goldDir=Join-Path $root '3_ouro\regional\era5_hourly_national_expansion'
$ids=@('BR_CE_FORTALEZA','BR_MA_BALSAS','BR_PB_JOAO_PESSOA','BR_PE_PETROLINA','BR_PI_URUCUI','BR_RN_MOSSORO','BR_SE_ARACAJU','BR_ES_LINHARES','BR_MG_MONTES_CLAROS','BR_RJ_CAMPOS_GOYTACAZES','BR_SP_RIBEIRAO_PRETO','BR_PR_LONDRINA','BR_RS_PASSO_FUNDO','BR_SC_CHAPECO')
$scopeIds=@('BR_AL_MACEIO','BR_BA_BARREIRAS')+$ids
$fields=@('temperature_2m','dew_point_2m','relative_humidity_2m','vapour_pressure_deficit','soil_moisture_0_to_7cm','soil_moisture_7_to_28cm','soil_moisture_28_to_100cm','soil_moisture_100_to_255cm','soil_temperature_0_to_7cm','soil_temperature_7_to_28cm','soil_temperature_28_to_100cm','soil_temperature_100_to_255cm')
$units=[ordered]@{'temperature_2m'='°C';'dew_point_2m'='°C';'relative_humidity_2m'='%';'vapour_pressure_deficit'='kPa';'soil_moisture_0_to_7cm'='m³/m³';'soil_moisture_7_to_28cm'='m³/m³';'soil_moisture_28_to_100cm'='m³/m³';'soil_moisture_100_to_255cm'='m³/m³';'soil_temperature_0_to_7cm'='°C';'soil_temperature_7_to_28cm'='°C';'soil_temperature_28_to_100cm'='°C';'soil_temperature_100_to_255cm'='°C'}
$sourceModels=[ordered]@{};foreach($f in $fields){$sourceModels[$f]='era5'}
function Sync-ValidatedProducts{
    New-Item -ItemType Directory -Path $silverDir -Force|Out-Null
    New-Item -ItemType Directory -Path $goldDir -Force|Out-Null
    foreach($id in $scopeIds){
        $mfPath=Join-Path $manifestDir ($id+'_2024-10-08_2026-10-07.manifest.json')
        if(!(Test-Path -LiteralPath $mfPath)){continue}
        $mf=Get-Content -LiteralPath $mfPath -Raw|ConvertFrom-Json
        if($mf.validation_status -ne 'valid'){continue}
        $rawPath=$mf.raw_file
        if(!(Test-Path -LiteralPath $rawPath)){throw "Manifest sem JSON bruto: $id"}
        $outName=$id+'_2024-10-08_2026-10-07.csv'
        $silverPath=Join-Path $silverDir $outName
        $goldPath=Join-Path $goldDir $outName
        if((Test-Path -LiteralPath $silverPath) -and (Test-Path -LiteralPath $goldPath)){continue}
        if((Test-Path -LiteralPath $silverPath) -or (Test-Path -LiteralPath $goldPath)){throw "Prata/Ouro desalinhados para $id; interrompi sem sobrescrever."}
        $data=Get-Content -LiteralPath $rawPath -Raw|ConvertFrom-Json
        if($data.hourly.time.Count -ne 17520){throw "Série não tem 17.520 horas: $id"}
        $rows=[System.Collections.Generic.List[object]]::new()
        for($i=0;$i -lt $data.hourly.time.Count;$i++){
            $row=[ordered]@{timestamp_utc=$data.hourly.time[$i]+'Z';location_id=$id;location_name=$mf.location_name;state=$mf.state;macro_region=$mf.macro_region;timezone='GMT';latitude=$mf.requested_latitude;longitude=$mf.requested_longitude;api_latitude=$data.latitude;api_longitude=$data.longitude;elevation_m=$data.elevation}
            foreach($f in $fields){$row[$f]=$data.hourly.$f[$i]}
            $row['source_model']='era5';$row['source_file']=(Split-Path -Leaf $rawPath);$row['quality_flag']='valid'
            $rows.Add([pscustomobject]$row)
        }
        if($rows.Count -ne 17520){throw "Normalização incompleta para $id"}
        $exportArgs=@{Delimiter=';';NoTypeInformation=$true;Encoding='utf8'}
        $rows|Export-Csv -LiteralPath $silverPath @exportArgs
        $rows|Export-Csv -LiteralPath $goldPath @exportArgs
        Write-Output "Prata/Ouro normalizados: $id ($($rows.Count) horas)"
    }
    $validManifests=@()
    foreach($id in $scopeIds){
        $mfPath=Join-Path $manifestDir ($id+'_2024-10-08_2026-10-07.manifest.json')
        if(Test-Path -LiteralPath $mfPath){$mf=Get-Content -LiteralPath $mfPath -Raw|ConvertFrom-Json;if($mf.validation_status -eq 'valid'){$validManifests+=@($mf)}}
    }
    $validIds=@($validManifests|ForEach-Object {$_.location_id})
    $pendingIds=@($scopeIds|Where-Object {$_ -notin $validIds})
    $stateCoverage=@($validManifests|ForEach-Object {[pscustomobject]@{location_id=$_.location_id;location_name=$_.location_name;state=$_.state;macro_region=$_.macro_region;rows=17520;valid_cells=210240;null_cells=0;first_timestamp='2024-10-08T00:00:00Z';last_timestamp='2026-10-07T23:00:00Z';source_model='era5';api_latitude=$_.returned_latitude;api_longitude=$_.returned_longitude;validation_status='valid'}})
    $stateCoverage|Sort-Object macro_region,state|Export-Csv -LiteralPath (Join-Path $goldDir 'coverage_by_location.csv') -Delimiter ';' -NoTypeInformation -Encoding utf8
    $regions=@($stateCoverage|Select-Object -ExpandProperty macro_region -Unique)
    $states=@($stateCoverage|Select-Object -ExpandProperty state -Unique)
    $totalRows=$validManifests.Count*17520
    $schema=[ordered]@{dataset='ERA5 hourly national expansion, individual point files';model='era5';columns=@('timestamp_utc','location_id','location_name','state','macro_region','timezone','latitude','longitude','api_latitude','api_longitude','elevation_m')+$fields+@('source_model','source_file','quality_flag');units=$units;source_model_by_variable=$sourceModels;frequency='hourly';timezone='GMT';period=[ordered]@{start='2024-10-08T00:00:00Z';end='2026-10-07T23:00:00Z';hours_per_location=17520};location_count=$validManifests.Count;state_count=$states.Count;regions=$regions;row_count=$totalRows;valid_cells=$totalRows*12;null_cells=0;pending_location_ids=$pendingIds;spatial_scope='Discrete points; no continuous state or national coverage claim.'}
    $schema|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $silverDir 'schema.json') -Encoding utf8
    $schema|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $goldDir 'schema.json') -Encoding utf8
    $quality=[ordered]@{product='era5_hourly_national_expansion';model='era5';period='2024-10-08T00:00:00Z/2026-10-07T23:00:00Z';locations=$validManifests.Count;states=$states.Count;regions=$regions;rows=$totalRows;expected_rows=$validManifests.Count*17520;variables=$fields;expected_cells=$totalRows*12;valid_cells=$totalRows*12;null_cells=0;duplicate_location_timestamps=0;validation_status=$(if($pendingIds.Count -eq 0){'complete_for_expansion_scope'}else{'complete_for_validated_points'});pending_location_ids=$pendingIds;spatial_scope='Discrete points; not continuous state or national coverage.'}
    $quality|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $goldDir 'quality_report.json') -Encoding utf8
}
if(!(Test-Path -LiteralPath $onePointScript)){throw "Coletor por ponto não encontrado: $onePointScript"}
$counter=Get-Content -LiteralPath $counterPath -Raw|ConvertFrom-Json
$done=@();if($counter.PSObject.Properties['era5_hourly_national_completed_locations']){$done=@($counter.era5_hourly_national_completed_locations)}
$attempted=@();if($counter.PSObject.Properties['era5_hourly_national_attempted_locations']){$attempted=@($counter.era5_hourly_national_attempted_locations)}
$pending=@($ids|Where-Object {$_ -notin $done -and $_ -notin $attempted})
$pointCost=(730.0/14.0)*(12.0/10.0)
$fullEstimate=$pending.Count*$pointCost
$margin=$fullEstimate*0.20
$balance=[double]$counter.remaining_project_budget
if([math]::Abs(([double]$counter.completed_calls+$balance)-8000.0) -gt 0.02){throw 'Contador não reconcilia com teto de 8.000.'}
if($balance -lt ($fullEstimate+$margin)){throw "Saldo insuficiente para os pontos pendentes com margem: saldo=$balance estimado=$($fullEstimate+$margin)"}
if($fullEstimate -gt 4000 -or $fullEstimate -gt 2000 -or ($pointCost*1.2) -gt 200){throw 'Estimativa excede algum limite interno diário/hora/minuto.'}
if($pending.Count -eq 0){Write-Output 'Não há localidades pendentes neste lote.';Sync-ValidatedProducts;return}
$plannedStates=@($pending|ForEach-Object {$_.Substring(3,2)})
Write-Output "Plano: $($pending.Count) pontos ($($plannedStates -join ',')); models=era5; 12 variáveis; 730 dias; custo estimado=$([math]::Round($fullEstimate,4)); margem 20%=$([math]::Round($margin,4)); total reservado=$([math]::Round(($fullEstimate+$margin),4)); saldo conservador projetado=$([math]::Round(($balance-$fullEstimate-$margin),4))."
Sync-ValidatedProducts
$stopReason=$null
$index=0
foreach($id in $pending){
    $index++
    Write-Output "Lote $index/$($pending.Count): $id; uma chamada; estimativa por ponto=$([math]::Round($pointCost,4)); margem=$([math]::Round(($pointCost*0.2),4))."
    try{& $onePointScript -LocationId $id}
    catch{
        $message=$_.Exception.Message
        $mfPath=Join-Path $manifestDir ($id+'_2024-10-08_2026-10-07.manifest.json')
        if(Test-Path -LiteralPath $mfPath){
            $mf=Get-Content -LiteralPath $mfPath -Raw|ConvertFrom-Json
            if($mf.validation_status -eq 'incomplete_pending'){Write-Output "Ponto $id pendente por campo/validação; preservado sem retry. Continuando localidades independentes.";continue}
            if($mf.validation_status -eq 'valid'){Sync-ValidatedProducts;Write-Output "Manifest válido apesar do erro final para $id; dados preservados. Continuando.";continue}
            if($mf.validation_status -eq 'invalid_non_json'){$stopReason="Resposta não JSON em $id. Sem retry; parei a sequência." ;break}
        }
        $stopReason="Erro em $id; parei a sequência sem retry automático. $message"
        break
    }
    $mfPath=Join-Path $manifestDir ($id+'_2024-10-08_2026-10-07.manifest.json')
    if(!(Test-Path -LiteralPath $mfPath)){$stopReason="Manifest não foi criado para $id; parei.";break}
    $mf=Get-Content -LiteralPath $mfPath -Raw|ConvertFrom-Json
    Sync-ValidatedProducts
    if($mf.validation_status -eq 'incomplete_pending'){Write-Output "Ponto $id pendente; continuando os lotes independentes.";continue}
    if($mf.validation_status -ne 'valid'){$stopReason="Manifest inválido para $id; parei.";break}
}
Sync-ValidatedProducts
$counter=Get-Content -LiteralPath $counterPath -Raw|ConvertFrom-Json
$validCount=@(Get-ChildItem -LiteralPath $manifestDir -File -Filter '*.manifest.json'|ForEach-Object {Get-Content -LiteralPath $_.FullName -Raw|ConvertFrom-Json}|Where-Object {$_.validation_status -eq 'valid' -and $_.location_id -in $scopeIds}).Count
$done=@();if($counter.PSObject.Properties['era5_hourly_national_completed_locations']){$done=@($counter.era5_hourly_national_completed_locations)}
$attempted=@();if($counter.PSObject.Properties['era5_hourly_national_attempted_locations']){$attempted=@($counter.era5_hourly_national_attempted_locations)}
$remaining=@($ids|Where-Object {$_ -notin $done -and $_ -notin $attempted})
[pscustomobject]@{ValidExpansionPoints=$validCount;CompletedCalls=$counter.completed_calls;RemainingBudget=$counter.remaining_project_budget;PlannedCalls=$counter.planned_calls;Retries=$counter.retries;RemainingUnattemptedLocations=($remaining -join ',');Status=$(if($stopReason){'stopped'}elseif($remaining.Count -eq 0){'pending points attempted or complete'}else{'sequence finished'})}|Format-List
if($stopReason){throw $stopReason}