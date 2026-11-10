# Auditoria regional Norte + Centro-Oeste — 2026-11-06

## Estado da ingestão
Nenhuma chamada de API foi feita nesta etapa: a reconciliação do contador não fecha e existe um piloto anterior com nulos em Tmax/Tmin diários. Nenhum arquivo do Lake antigo foi alterado. O contador persistente foi preservado sem mutação.

## Contador e camadas
`1_bronze/auditoria/contador_chamadas.json` informa `completed_calls=2827`, `remaining_project_budget=3173`, `planned_calls=3372`, `api_requests_attempted=73` e 0 retries; 2.827 + 3.372 = 6.199, acima do teto de 6.000. As 73 tentativas são requisições HTTP (incluem diagnóstico/pilotos), não equivalem ao custo contabilizado. O arquivo ainda marca o status como interrompido por temperatura nula. Não é possível confirmar 3.173 como saldo reconciliado. Manifests no Bronze alvo registram 27 respostas de ETo ERA5-Land e um piloto; a série horária antiga registra 70 requisições concluídas em lotes, sem custo histórico faturado por lote. Prata/Ouro atuais no destino contêm ETo (27 localidades) e precipitação (27 localidades); os manifests não provam custo Open-Meteo em unidades faturáveis.

**Saldo operacional comprovável para novos lotes: indeterminado.** Para preservar o teto cumulativo, qualquer ingestão paga aguarda conciliação por estimativa tarifária por requisição/lote e correção auditável do contador. Não se conhece nem se presume saldo mensal da conta Open-Meteo.

## Schema antigo e reutilização comprovada
O schema horário antigo é `3_ouro/openmeteo_era5_land/schema.json`; contém 13 colunas climáticas horárias permitidas: `temperature_2m`, `dew_point_2m`, `relative_humidity_2m`, `vapour_pressure_deficit`, quatro `soil_moisture_*`, quatro `soil_temperature_*` e `snow_depth`. Unidades documentadas: °C, %, kPa, m³/m³ e m. O manifest confirma `/v1/archive`, `model=era5_land`, frequência horária e 67 pontos, 27 UFs, período 2024-10-08 a 2026-10-07.

O schema diário antigo está em `3_ouro/openmeteo_era5_land_daily/schema.json`: `tmax_c`, `tmin_c`, `eto_mm`, `soil_temp_shallow_c`, `precipitation_mm`; °C e mm/dia. Tmax/Tmin e solo superficial são ERA5-Land no manifest; precipitação existente é best match e não pode ser reutilizada como ERA5. ETo antiga também mistura proveniência best match/modelo desconhecido. O schema horária não contém esses campos legados diários. Temperatura de superfície legada não foi mapeada a campo API.

A cobertura horária antiga tem linhas completas de 2024-10-08 00:00 UTC a 2026-10-07 23:00 UTC nas localidades Norte/Centro-Oeste já cadastradas. Os pontos regionais existentes podem ser reutilizados sem nova coleta para as 13 variáveis ERA5-Land, preservando provenance e fonte. A tabela de cobertura antiga comprova pontos nas 11 UFs regionais: AC, AP, AM, PA, RO, RR, TO, DF, GO, MT e MS. São pontos discretos, não cobertura contínua.

## Datas, modelos e piloto
Documentação consultada em 2026-11-06 informa atraso de atualização de cinco dias para ERA5 e ERA5-Land; pela regra temporal, 2026-11-01 é a data-limite nominal atual. O piloto existente testou 2026-10-31: ERA5-Land horário e precipitação ERA5 retornaram valores, ETo ERA5-Seamless retornou valor, mas Tmax/Tmin diários vieram nulos em ERA5 e ERA5-Land. Assim, não foi validada uma data final comum para o pacote diário AquaCrop. ERA5-Land não oferece precipitação/radiação; ERA5 não oferece `snow_depth`. ETo ERA5-Land retornou nulo nos testes prévios; eventual ETo via ERA5-Seamless deve permanecer separado e depende de piloto válido no novo período/ponto.

Janela de 24 meses adotável sem extrapolação dos dados reaproveitados: **2024-10-08 a 2026-10-07**, inclusiva (730 dias), para as 13 variáveis horárias ERA5-Land. Não se afirma que cubra variáveis diárias distintas. A janela nominal recente 2024-11-02 a 2026-11-01 (730 dias) não foi provada completa para Tmax/Tmin, e não substitui a janela antiga.

## Custo projetado (não autorizado/executado)
Regra publicada: custo fracionário cresce com dias além de 14 e variáveis além de 10; 2 semanas com 15 variáveis = 1,5 unidades. Estimativa conservadora para 730 dias e 13 variáveis: (730/14) × (13/10) = **67,79 chamadas contabilizadas por ponto**; com 20% retry: **81,35/ponto**. Para a seleção mínima de um ponto já existente por UF nas 11 UFs regionais: 11 × 81,35 = **895 contabilizadas** para uma coleta horária completa; para reaproveitar os dados antigos, custo API novo = 0. Componentes diários independentes (precipitação ERA5 e ETo ERA5-Seamless) não estão incluídos porque carecem de piloto de completude e proveniência na janela; se ambos fossem requisitados por 730 dias e 11 pontos, estimativa adicional combinada = 2 × (730/14) × 11 × 1,2 = **1.378** contabilizadas. Total conservador com coleta repetida dos três componentes seria **2.273**, mas o saldo reconciliado é indeterminado. Não se fez lote nem retry.

Limites internos seriam aplicados antes de qualquer lote (200/min, 2.000/h, 4.000/dia e 6.000 cumulativo); não foi iniciado cronômetro/consumo novo.

## Lacunas e próximos passos
- Campo/modelo/período: Tmax/Tmin diários em ERA5-Land e ERA5, nulos no piloto de 2026-10-31; pendentes, sem substituição por outro modelo.
- `snow_depth` em ERA5 e precipitação/radiação em ERA5-Land: lacunas esperadas por incompatibilidade de produto; não requisitadas.
- ETo ERA5-Land: nula em testes anteriores; pendente. ERA5-Seamless é elegível somente para ETo após piloto válido, em produto/coluna próprios.
- Temperatura de superfície legada: sem mapeamento API comprovado, não requisitada.
- A auditoria regional demonstra pontos nas 11 UFs, mas nenhum produto regional novo foi materializado. Próxima etapa segura: reconciliar os custos contabilizados anteriores por manifest e lotes, então reutilizar Bronze antigo comprovável para o produto ERA5-Land; executar apenas os pilotos diários que caibam no saldo já corrigido.

Referências oficiais consultadas: [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) (matriz de variáveis, modelos, resolução e atraso; consulta de 2026-11-06); [Pricing](https://open-meteo.com/en/pricing) (faturamento fracionário: duração e número de variáveis).

## Aditivo — teto atualizado e tentativa de coleta (2026-11-06)

O teto cumulativo foi atualizado pelo usuário para **8.000**; teto interno por dia/hora/minuto permanece 4.000/2.000/200. A reconciliação aproximada do consumo anterior é 2.827 contabilizadas, compatível com 54 respostas diárias completas de 730 dias × (730/14 = 52,14 por resposta) + pilotos diagnósticos; uso mensal oficial segue desconhecido. A chamada inválida de URL e o piloto válido de 1 dia foram debitados conservadoramente como 2 unidades, totalizando 2.829 e saldo pré-lote 5.171.

Piloto ETo ERA5-Seamless em Cruzeiro do Sul, 2026-10-01: `et0_fao_evapotranspiration=3,39 mm`, válido. A série inteira anterior de ERA5-Land para este ponto tem 730 valores nulos, então não foi reaproveitada como ETo.

Tentativa lote `eto_seamless_001`: uma requisição explícita a `/v1/archive` com `models=era5_seamless`, 2024-10-08–2026-10-07, variável diária `et0_fao_evapotranspiration`, ponto BR_AC_CRUZEIRO_DO_SUL. O transporte retornou conteúdo não JSON (erro de parse no primeiro caractere “U”); status HTTP e corpo bruto não foram capturados, nenhum dado climático foi salvo e não houve retry. Por prudência, custo debitado como **52,14** (730/14), mais reserva de retry não consumida **10,43**. Contador após a tentativa: **2.881,14 contabilizadas; saldo interno 5.118,86** (teto 8.000). O manifest da tentativa registra a falha sem inventar valor/modelo. Sem séries regionais Seamless publicadas; ingestão está parada para não repetir sinal de resposta inválida.

## Materialização sem novas chamadas
- Reaproveitado ERA5-Land horário com proveniência explícita e cobertura validada para **24 localidades em 11 UFs** (420.480 linhas válidas na janela 2024-10-08–2026-10-07). Os arquivos Bronze originais permanecem no Lake antigo em somente leitura; o Lake novo mantém o manifest de origem e a tabela Ouro reutilizada.
- Extraído ERA5 precipitação diária Bronze já existente para **11 localidades (uma por UF), 8.030 linhas válidas**, no mesmo período de 730 dias. Prata e Ouro separados como ERA5. Custo de chamadas hoje para estas materializações: 0.
- ETo ERA5-Land está nula nas respostas existentes; ETo ERA5-Seamless tem somente um piloto válido (3,39 mm em 2026-10-01). O lote de 730 dias não foi válido e ficou pendente; não foi preenchido por outro modelo.
- Cobertura por UF e região foi publicada como arquivo separado. A lista de pontos é discreta e não representa cobertura contínua.

## Estimativa regional atualizada e saldo para sábado
Com 24 localidades existentes, uma série diária ERA5-Seamless ETo de 730 dias custaria 24 × (730/14) = **1.251,43 chamadas estimadas**, ou **1.501,71 incluindo 20% de margem**. Uma reingestão horária ERA5-Land (13 variáveis; 24 pontos) seria 24 × (730/14) × (13/10) = 1.627,43, ou 1.952,91 com margem, mas os dados horários foram reaproveitados sem chamadas. Precipitação ERA5 nas 11 UFs também foi reaproveitada e não exige lote novo. Após a tentativa inválida, contador interno = **2.881,14 / 8.000**, saldo = **5.118,86**, 0 retries. Para sábado, saldo interno projetado segue 5.118,86 se não houver outras coletas do projeto; consumo da conta Open-Meteo fora deste contador permanece desconhecido.

## Fechamento das tarefas pendentes — testes e produtos regionais

- **ETo:** os testes em um dia, 14 dias e 90 dias passaram em Cruzeiro do Sul. A validação de 730 dias também passou; a coleta foi concluída nas 24 localidades existentes de 11 UFs, em Bronze/Prata/Ouro separados como **ERA5-Seamless**. Foram 17.520 valores, 730 por ponto, todos não nulos, `et0_fao_evapotranspiration`, `mm/dia`, `timezone=GMT`. O lote extenso que antes retornou conteúdo não JSON foi resolvido com leitura de status/cabeçalhos e preservação do corpo antes do parse.
- **Tmax/Tmin:** reutilizados sem custo adicional dos Bronze originais do Lake antigo (somente leitura). O manifest identifica `temperature_2m_max/min`, `model=era5_land`, °C, diário, 2024-10-08–2026-10-07; o relatório de qualidade antigo prova cobertura total nas 67 localidades. Copiadas para o destino as respostas gzip Bronze que contêm as 24 localidades regionais; hashes de origem/destino conferidos. O recorte regional tem 17.520 linhas, sem nulos ou duplicatas.
- **Disponibilidade recente:** piloto de 2026-10-24 a 2026-10-30 em Cruzeiro do Sul passou para Tmax/Tmin em ERA5-Land e ERA5 (7/7 dias por variável). O piloto anterior de 2026-10-31 veio nulo em ambos. Assim, 2026-10-30 é a última data completa observada nesse ponto nos testes recentes; não generalizar a disponibilidade desse dia a todos os pontos. Para manter os campos completos no mesmo intervalo comprovado, o período dos produtos regionais continua 2024-10-08 a 2026-10-07, exatamente 730 dias.
- **Diferença de limites diários:** Tmax/Tmin reutilizados preservam a zona local `auto` por ponto. Precipitação ERA5 e ETo ERA5-Seamless usam GMT. Os produtos permanecem separados e identificam a zona; harmonize as fronteiras diárias antes de juntar valores por data.
- **Lacunas de modelo:** ETo ERA5-Land permanece nula nas respostas existentes; não foi usada para preencher ETo-Seamless. Precipitação em ERA5-Land e `snow_depth` em ERA5 são lacunas esperadas. Temperatura de superfície legada não foi mapeada para API.
- **Contador:** teto 8.000; contabilizadas **4.143**; saldo interno **3.857**; 105 requisições HTTP consideradas, 0 retries. O bloco ETo de 24 pontos custou estimadamente 1.251,43 unidades, com reserva teórica de retry 250,29 (não consumida). Os pilotos Tmax/Tmin custaram 2 unidades. Conta prévia Open-Meteo desconhecida; não há alegação de saldo mensal.
- Cobertura final por UF está em `3_ouro/regional/cobertura_por_uf.csv`. Pontos são discretos e não representam cobertura contínua.
