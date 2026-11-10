# Execução final — 7 de novembro de 2026

Concluídas as séries regionais solicitadas para 24 localidades em 11 UFs. ERA5-Land horário: 420.480 linhas; ERA5 horário: 420.480 linhas e 5.045.760 valores válidos em 12 variáveis; Tmax/Tmin ERA5-Land: 17.520 linhas; ETo ERA5-Seamless: 17.520 valores válidos; precipitação ERA5: 17.520 valores válidos. Todas cobrem 2024-10-08 a 2026-10-07. Produtos horários e diários estão separados por modelo/fuso.

ERA5 horário: 24 respostas HTTP 200, cada uma 17.520 horas, os 12 campos presentes, unidades aprovadas, sem nulos. Bronze: 24 brutos, 24 manifests por ponto, 12 manifests por lote. Prata e Ouro materializados e schemas/qualidade/cobertura atualizados. Precipitação: expansão de 13 novos pontos concluída; bruto/manifest por ponto e consolidado.

Contador final: 6.482,2 contabilizadas, saldo 1.517,8 de 8.000; 148 tentativas, zero retries; sem chamadas planejadas. Uso prévio da conta desconhecido. Três falhas DNS do lote anterior seguem debitadas conservadoramente.

Lacunas esperadas: precipitação indisponível em ERA5-Land; `snow_depth` indisponível em ERA5; ETo ERA5-Land nula, coberta somente pelo produto ERA5-Seamless separado. Temperatura de superfície legada continua sem mapeamento por falta de evidência API/canônica. Cobertura espacial é de pontos discretos, não contínua por UF/Brasil.
