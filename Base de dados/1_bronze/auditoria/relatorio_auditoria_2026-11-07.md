# Auditoria final — Data Lake AquaCrop — 2026-11-07

## Produtos concluídos

| Produto/modelo | Cobertura regional | Período e frequência | Validação |
|---|---:|---|---|
| ERA5-Land | 24 pontos, 11 UFs | 2024-10-08 a 2026-10-07, horário GMT | 420.480 linhas válidas |
| ERA5 horário | 24 pontos, 11 UFs | 2024-10-08 a 2026-10-07, horário GMT | 420.480 linhas; 5.045.760 valores válidos nos 12 campos; zero nulos/duplicatas |
| Tmax/Tmin ERA5-Land | 24 pontos, 11 UFs | 2024-10-08 a 2026-10-07, diário local por ponto | 17.520 linhas; ambas as variáveis sem nulos; reuso com proveniência |
| ETo ERA5-Seamless | 24 pontos, 11 UFs | 2024-10-08 a 2026-10-07, diário GMT | 17.520 valores válidos; produto separado |
| Precipitação ERA5 | 24 pontos, 11 UFs | 2024-10-08 a 2026-10-07, diária GMT | 17.520 valores válidos; zero nulos/duplicatas |

Os pontos são discretos: não representam cobertura contínua das UFs ou do Brasil. Tmax/Tmin tem fronteira diária local (`auto` por ponto); ETo e precipitação usam GMT. Não unir por data sem harmonizar a fronteira diária.

## ERA5 horário novo

Bronze contém 24 JSONs originais, 24 manifests por ponto e 12 manifests de lote. Cada requisição usou `/v1/archive`, `models=era5`, 12 nomes API/canônicos existentes no schema antigo, GMT e intervalo de 730 dias. Units e 17.520 timestamps por ponto foram validados antes da materialização.

Prata: `2_prata/regional/era5_horario_norte_centro_oeste.csv`, wide com proveniência por linha e schema próprio. Ouro: `3_ouro/regional/era5_hourly/era5_horario_norte_centro_oeste.csv`, schema, qualidade e cobertura por localidade; a cobertura por UF também foi atualizada.

Campos incluídos: `temperature_2m`, `dew_point_2m`, `relative_humidity_2m`, `vapour_pressure_deficit`, quatro `soil_moisture_*` e quatro `soil_temperature_*`. Unidades seguem o schema canônico: °C, %, kPa e m³/m³.

## Lacunas e itens não mapeados

- `snow_depth` em ERA5: indisponibilidade esperada; ERA5-Land contém o campo.
- Precipitação em ERA5-Land: indisponibilidade esperada; precipitação está no produto diário ERA5.
- ETo ERA5-Land: Bronze existente é nula. ETo é fornecida no produto ERA5-Seamless separado, como exceção explícita.
- Temperatura de superfície legada: não mapeada. Manifest antigo só declara tipo genérico `temperature`; não prova nome API/canônico nem permite associar a uma variável ERA5. Nenhuma chamada ou conversão foi feita para esse campo.
- Pilotos nulos anteriores de Tmax/Tmin referiam-se a datas fora do período completo escolhido; não invalidam a série reutilizada de 730 dias.

Os dados antigos que usam seleção padrão `best_match` não foram reutilizados como ERA5 e nenhuma nova chamada usou `best_match`. O Lake antigo permaneceu somente para leitura.

## Orçamento e chamadas

Contador persistente: 6.482,2 contabilizadas; saldo 1.517,8 sob o teto cumulativo de 8.000; 148 tentativas registradas, zero retries. Uso prévio da conta Open-Meteo é desconhecido. Três falhas DNS do lote de precipitação anterior foram debitadas conservadoramente, embora não tenham resposta HTTP. Custos da série ERA5 horária: 24 × 62,5714 = 1.501,714; piloto 1,2. A margem estimada de retry não foi debitada pois não houve retry. Nenhuma chamada está planejada no contador.

Os lotes horários foram de dois pontos: custo estimado por lote de 125,143 + 20% de reserva = 150,171, abaixo do limite interno de 200/minuto. A série completa custou estimados 1.501,714, abaixo dos limites de hora e dia. Não se alega saldo mensal da conta.

## Documentação e nomes

Disponibilidade e cobrança conferidas na documentação oficial em 2026-11-07: [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) e [Pricing](https://open-meteo.com/en/pricing). Nomes, unidades, frequências e proveniência estão nos schemas e manifests de Bronze/Prata/Ouro.

## Estado final

As séries climáticas canônicas solicitadas e comprovadas estão concluídas para Norte e Centro-Oeste nos pontos existentes. O único item legado sem resolução é temperatura de superfície, aguardando evidência no schema/proveniência antiga antes de qualquer mapeamento.
