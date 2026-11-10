# Cruzamento soilframe-voronoi × falha ETo / endpoint — 2026-11-06

## Código inspecionado

Arquivo `soilframe-voronoi-master/soilframe/soilframe/download/era5land.py` define `OPEN_METEO_ERA5_URL = https://archive-api.open-meteo.com/v1/era5`. O código não envia `models=era5_land`, mas classifica a fonte como ERA5-Land. Ele pede variáveis diárias de tmax/tmin/tmean, precipitation_sum, et0_fao_evapotranspiration, shortwave_radiation_sum e wind_speed_10m_max. A documentação atual da API Histórica descreve `/v1/archive` e seleção explícita via `models`.

## Comparação diagnóstica na Open-Meteo

Para Belo Horizonte, 2026-11-03, endpoint `/v1/era5` e `/v1/archive?models=best_match` retornaram os mesmos valores e coordenada ajustada: lat -19.9297, lon -43.966034; Tmax 27.9°C, chuva 5.4mm, radiação 23.1MJ/m², ETo 4.59mm. ERA5-Land explícito retornou a célula diferente (-19.900002, -43.899994) e valores nulos para essas variáveis naquele dia; ERA5-Seamless também nulo naquele dia recente.

Para Belo Horizonte, 2025-06-01, `/v1/era5` e best_match novamente coincidiram exatamente (lat -19.9297, lon -43.966034; Tmax 25.8, chuva 0.1, radiação 16.68, ETo 3.2). ERA5 explícito retornou célula distinta (-20,-44) e valores diferentes (Tmax 26.2, chuva 0.3, radiação 15.09, ETo 2.89). ERA5-Land explícito retornou Tmax 26.0 na célula (-19.900002,-43.899994), mas chuva/radiação/ETo nulos. ERA5-Seamless retornou a célula ERA5-Land, Tmax 26.0, chuva 0.3, radiação 15.09, ETo 2.93.

## Conclusão

A hipótese do projeto é bem sustentada: o caminho legado `/v1/era5` sem parâmetro de modelo comportou-se como best_match nos dois testes, e não como ERA5-Land. Assim, outputs desse código não devem ser rotulados ERA5-Land; são best_match/legado sem seleção explícita. A diferença de latitude/célula é compatível com modelos/resoluções diferentes.

A ETo nula encontrada no Lake novo é um problema separado do endpoint legado: foi reproduzida com `/v1/archive?models=era5_land` em datas históricas, tanto daily quanto hourly. A documentação lista ETo para ERA5-Land, mas este serviço respondeu nulo. O endpoint explícito `models=era5_seamless` retornou ETo válida em período histórico. Não há base para atribuir a nulidade somente ao nome de parâmetro ou à serialização.

## Uso no Data Lake sob as regras atuais

- Para dados ERA5-Land, utilizar `/v1/archive?models=era5_land` e validar campo a campo; não usar o caminho do projeto `/v1/era5` como ERA5-Land.
- Para precipitação e radiação que faltem em ERA5-Land, usar ERA5 explícito, que existe na matriz permitida. Não usar Seamless para chuva/radiação, pois a regra deste Lake só autoriza Seamless para ETo.
- Para ETo, ERA5-Seamless é o fallback admissível se a indisponibilidade de ERA5-Land for documentada por variável, data e resposta; manter produto separado e identificá-lo como ERA5-Seamless.
- Manter produtos best_match antigos identificados como best_match/proveniência legada; não reclassificá-los retroativamente como ERA5 ou ERA5-Land.

Foram feitas 9 consultas diagnósticas de um ponto/dia. Contador estimado atualizado para 2.821 chamadas contabilizadas, 3.179 de saldo interno, sem retries. A coleta regional segue parada.
