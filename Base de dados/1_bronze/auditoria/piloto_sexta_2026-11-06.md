# Pilotos regionais de sexta — resultado e interrupção

Janela planejada: 2024-11-01 a 2026-10-31 (730 dias), com base no atraso documental de 5 dias para ERA5/ERA5-Land e margem conservadora. Região-alvo Norte + Centro-Oeste. Estimativa preliminar ainda sujeita ao contador/billing API; lote regional não foi iniciado.

Piloto em Cruzeiro do Sul, 2026-10-31:
- ERA5-Land hourly temperature_2m: série horária presente; Tmax/Tmin daily solicitadas vieram nulas.
- ERA5 precipitation_sum daily: 1.4 mm válido.
- ERA5-Seamless ETo daily: 3.63 mm válido.
- ERA5 daily temperature_2m_max/min: ambos nulos.

A resposta satisfaz parte das variáveis, mas Tmin/Tmax, essenciais para AquaCrop, vieram nulas para a data-limite testada. Como o prompt exige interromper diante de nulos essenciais, a coleta regional foi parada antes de lotes, e nenhum dado regional novo foi publicado. Não afirmar 2026-10-31 como última data completa para o pacote AquaCrop; é necessário encontrar a última data realmente completa para Tmax/Tmin no modelo permitido ou reportar a lacuna.

ERA5-Seamless permanece válido somente para ETo e está explicitamente separado. ERA5 para precipitação permanece explícito. Contador após 6 chamadas diagnósticas/piloto adicionais à conciliação anterior: 2.827 chamadas contabilizadas estimadas; 3.173 saldo cumulativo; 0 retries. Consumo oficial da conta é desconhecido. Lotes não iniciados.
