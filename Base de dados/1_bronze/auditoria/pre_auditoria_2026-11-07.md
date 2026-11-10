# Pré-auditoria de sábado — expansão de precipitação (2026-11-07)

## Estado reconciliado antes das chamadas

- Contador persistente: teto 8.000; contabilizadas 4.143; saldo 3.857 (8.000 − 4.143); 105 requisições HTTP anteriores; 0 retries. Manifest/Gold mostram os produtos regionais de ETo ERA5-Seamless (24 pontos), Tmax/Tmin ERA5-Land reutilizado (24 pontos), precipitação ERA5 (11 pontos) e ERA5-Land horário (24 pontos). Consumo prévio desconhecido da conta permanece desconhecido; este número não é saldo mensal.
- Janela regional: 2024-10-08 a 2026-10-07 inclusive (730 dias). Produtos existentes conferidos em Prata/Ouro por linhas, datas, pontos e modelo; a precipitação atual tem 8.030 linhas em 11 pontos.
- Manifest antigo de ERA5-Land diário confirma 24 localidades existentes nos 11 estados regionais. Cruzamento de IDs identificou 13 pontos sem precipitação no Ouro regional. Coordenadas virão desse manifest e não de novos pontos.
- Documentação Open-Meteo consultada em 2026-11-07: `/v1/archive`; a matriz lista precipitação para ERA5 e não para ERA5-Land. `daily` requer timezone; solicitado será GMT. Faturamento fracionário: duração acima de 14 dias é contabilizada por fração; para 730 dias e uma variável, 730/14 = 52,142857 por ponto.
- Nenhum `best_match` será usado. Sem precipitação ERA5-Land, sem valores de outro modelo e sem preenchimento cruzado.

## Estimativa antes do piloto/lotes

| Etapa | Modelo/campo | Pontos × duração | Custo estimado |
|---|---|---:|---:|
| Piloto de Rio Branco | ERA5 / precipitation_sum | 1 × 1 dia | 1,00 |
| Séries completas | ERA5 / precipitation_sum | 13 × 730 dias | 677,86 |
| Reserva de retry (20%) | — | aplicada ao plano inteiro | 135,77 |
| Plano total incluindo reserva | — | — | 814,63 |

Custo real planejado sem retries: 678,86; saldo interno projetado se tudo passar: 3.178,14. Saldo após reservar 20% para planejamento: 3.042,37. A reserva não será contada como uso se não houver retry. Lotes de 3 pontos: 156,43 cada, abaixo de 200/minuto; aguardar pelo menos 60 segundos entre lotes. Projeção total fica abaixo dos limites de 2.000/hora e 4.000/dia.

## Produtos e fusos

ETo ERA5-Seamless e precipitação ERA5 usam GMT. Tmax/Tmin ERA5-Land reutilizado preserva timezone local `auto` por ponto; manter produtos separados e registrar a diferença, sem presumir fronteiras diárias iguais.

Referências atuais: [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) e [Pricing](https://open-meteo.com/en/pricing).
