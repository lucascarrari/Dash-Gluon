# Auditoria preliminar — Data Lake AquaCrop

Execução: 2026-11-06. Lake antigo consultado somente para leitura. Nenhum dado de coleta foi baixado; a tentativa de conectividade do piloto falhou antes de obter resposta HTTP.

## Inventário confirmado por README e manifests consultados

- ERA5-Land horário: 67 localidades, 27 UFs, cinco regiões, 2024-10-08 a 2026-10-07; 13 variáveis: temperature_2m, dew_point_2m, relative_humidity_2m, vapour_pressure_deficit, quatro soil_moisture, quatro soil_temperature e snow_depth. Unidades: °C, %, kPa, m³/m³ e m. Frequência horária. Origem ERA5-Land explícita no manifest.
- ERA5-Land diário: 67 localidades e janela 2024-10-08 a 2026-10-07. Tmax/Tmin e soil_temp_shallow_c identificados como ERA5-Land; unidade °C. ETo (mm/dia) e precipitação (mm/dia) têm trechos best match e são excluídos do reaproveitamento como produtos ERA5/ERA5-Land.
- ETo legado: 67 localidades + 192 pontos de grade, sobretudo 2024-09-01 a 2026-09-30. Modelo não registrado; proveniência não comprovada.
- Temperatura de superfície legada: mistura variáveis e populações com cobertura desigual, incluindo ETo; modelo não registrado.
- Precipitação legada: best match; não reaproveitada como modelo explicitamente escolhido.
- Tmax/Tmin em grade: 850 coordenadas, 2024-10-18 a 2026-10-08; modelo não persistido.
- Ouro unificado legado herda a proveniência não comprovada dos campos Tmax/Tmin.

## Disponibilidade da documentação Open-Meteo

A documentação atual lista temperatura do ar, umidade relativa, ponto de orvalho, VPD, umidade/temperatura do solo e ETo para ERA5 e ERA5-Land; snow_depth para ERA5-Land, não ERA5; precipitação para ERA5, não ERA5-Land. A documentação indica atraso de atualização de cinco dias para ERA5 e ERA5-Land. Janela candidata: 2024-11-01 a 2026-10-31, inclusive; última data completa por modelo precisa ser confirmada por resposta/metadata da API no dia de coleta.

## Orçamento e estado

Teto interno: 6.000 total, 4.000/dia, 2.000/hora e 200/minuto. Consumo prévio da conta desconhecido; isto não representa saldo mensal da conta. Planejamento de coleta ainda não aprovado: confirmar custo por variável/local/período para os lotes e margem de retry antes do piloto. Contador persistente está em contador_chamadas.json.

Status: bloqueado antes do piloto. O teste mínimo de conectividade HTTPS falhou sem retorno HTTP. Chamadas contabilizadas como realizadas: 0; retries: 0; saldo interno local: 6.000. Nenhum 429/cota foi recebido.

## Pendências

1. Confirmar acesso HTTPS à API e última data completa ERA5 e ERA5-Land.
2. Calcular custo com a regra oficial por duração, número de variáveis e locais; incorporar retries na estimativa.
3. Fazer piloto e conferir o custo real antes de seguir.
4. Só então gerar Bronze, Prata e Ouro. Nenhum produto coletado foi publicado nesta execução.

Referências: https://open-meteo.com/en/pricing ; https://open-meteo.com/en/docs/historical-weather-api
