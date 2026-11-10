# Investigação de ETo nula — 2026-11-06

## Testes diagnósticos

- ERA5-Land, ponto próximo a Cruzeiro do Sul, 2026-10-01, daily=et0_fao_evapotranspiration: campo e unidade mm presentes, valor nulo.
- ERA5-Land, mesma localidade, 2025-06-01: solicitação simultânea de hourly e daily para et0_fao_evapotranspiration; daily nulo e 0/24 valores horários não nulos. Isso descarta erro específico na transformação CSV e torna improvável erro no nome do parâmetro.
- ERA5-Seamless, mesma coordenada/data de 2025-06-01: campo diário válido 2.49 mm; 24/24 valores horários presentes (incluindo zero legítimo).

## Conclusão

A falha ocorre na resposta do modelo ERA5-Land para ETo, antes da normalização. Não é apenas um nome de coluna ou transformação CSV. A página oficial da API lista ETo como disponível para ERA5-Land, portanto há divergência entre a disponibilidade documentada e o retorno operacional observado para o ponto/teste. O teste Seamless mostra que a variável/parâmetro e a localização/dia funcionam no serviço, mas não prova que ERA5-Land esteja amplamente indisponível em todos os locais/datas.

## Estado e restrição

Lotes regionais continuam parados. ERA5-Seamless é permitido somente para ETo e o prompt permite considerá-lo se ETo ERA5-Land não puder ser obtida validamente; qualquer adoção deve ser explicitamente identificada e ficar em produto/modelo separado. Dados anteriores ETo ERA5-Land nulos permanecem inválidos.

Contador revisado após 3 chamadas diagnósticas de 1 dia: 2.812 chamadas contabilizadas estimadas; 3.188 de saldo interno. Estimativa ponderada, não leitura de consumo oficial da conta. Nenhum retry.
