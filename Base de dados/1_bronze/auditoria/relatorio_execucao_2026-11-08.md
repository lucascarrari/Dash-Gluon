# Reconciliação Data Lake AquaCrop — 2026-11-09
Destino: C:\Users\User\OneDrive - Firjan\Área de Trabalho\Base de dados
Lake antigo: somente leitura; nenhum arquivo nele foi alterado.

## Contador
7.547,1143 contabilizadas; saldo aritmético de 452,8857/8.000; 166 tentativas e 0 retries segundo o contador. Uso prévio da conta desconhecido. Nenhuma chamada à API foi feita durante esta reconciliação. Limites internos: 4.000/dia, 2.000/hora, 200/minuto.

## Cobertura auditada
- ERA5 horário, 12 campos: 40 localidades combinadas (24 Norte/Centro-Oeste + 16 expansão), 27 UFs, 5 regiões; 700.800 linhas e 8.409.600 células válidas, zero nulos; 2024-10-08 a 2026-10-07, GMT.
- ERA5 precipitação: 27 localidades/27 UFs, 19.710 dias-ponto, zero nulos e zero duplicatas; 2024-10-08 a 2026-10-07, diária GMT, mm/dia. Produto nacional validado; o relatório regional anterior era só o subconjunto de 24 localidades/11 UFs.
- ERA5-Seamless ETo: 24 localidades/11 UFs e 17.520 valores válidos; faltam 16 UFs; diária GMT, mm/dia.
- ERA5-Land diário reutilizado: Tmax, Tmin e temperatura rasa do solo em 67 localidades/27 UFs, 48.910 linhas, sem nulos; fronteira diária local, °C.
- ERA5-Land horário: schema inclui 13 variáveis, entre elas snow_depth; cobertura e número de linhas para 24 localidades/11 UFs. QA atual não discrimina valores/nulos por variável; snow_depth permanece pendente de auditoria de valores.
- Pontos são discretos, sem cobertura contínua.

## Custos e lacunas
ETo para as 16 UFs descobertas: estimativa observada de 52,1429 por série de 730 dias; base 834,2857 + reserva de 20% (166,8571) = 1.001,1429, acima do saldo. Após piloto de 1 dia, caberiam no máximo sete séries completas, com margem e custo do piloto: aproximadamente 438,0857; saldo projetado 14,8. Essa estimativa depende de piloto válido e cobrança real dentro da previsão; nenhuma série nova foi solicitada.
ETo ERA5-Land permanece lacuna esperada por respostas nulas. Precipitação não é oferecida por ERA5-Land; snow_depth não é oferecida por ERA5. Temperatura de superfície legada continua sem mapeamento por falta de evidência. Tmax/Tmin local e ETo/precipitação GMT exigem harmonização antes de junções diárias.

## Auditoria
RN/Mossoró está completa: manifest e raw válidos, 17.520 horas, 12 campos, sem campos ausentes/nulos/unidades incorretas; Prata/Ouro sincronizadas. A lista obsoleta de 4 pendências de precipitação foi removida do contador após validação do produto nacional.

Arquivos atualizados: contador_chamadas.json; relatorio_reconciliacao_2026-11-09.md; relatorio_execucao_2026-11-08.md; 3_ouro/auditoria_cobertura_por_variavel_uf.csv; 3_ouro/era5/cobertura_por_uf_nacional.csv; 3_ouro/era5/relatorio_qualidade_nacional.json.

## Piloto ETo pendente de execução local

O script de piloto ERA5-Seamless em BA foi preparado e teve sintaxe verificada. A pré-verificação DNS no ambiente de execução do Codex retornou Acesso negado; nenhum pedido HTTP ocorreu e nenhuma chamada foi debitada. O evento foi registrado em manifest_eto_pilot_preflight_2026-11-09.json. Como o teste DNS/TCP do usuário funcionou anteriormente, o próximo passo é executar o script no PowerShell local. Não repetir em caso de 429, cota ou resposta inválida.


## Atualização do piloto (após a reconciliação)

O piloto ETo ERA5-Seamless em BR_BA_BARREIRAS retornou HTTP 200. O JSON tem et0_fao_evapotranspiration=7.69 mm em 2026-10-07, GMT; coordenada retornada -12.199997, -45.0. Validado e salvo em Bronze com manifesto. Foi debitado custo estimado de 0,0714286 chamadas; reserva de 20%: 0,0142857. Contador: 7.547,185714 chamadas; saldo: 452,814286. O restante da expansão ETo ainda não começou. Script corrigido para não repetir esse piloto e para adicionar a propriedade ao contador corretamente.


## Atualização ETo BA — série completa

A coleta completa de BR_BA_BARREIRAS retornou HTTP 200 e passou a validação: 730 dias, 2024-10-08 a 2026-10-07, 730 valores sem nulos, unidade mm/dia, GMT. JSON bruto, manifesto, Prata e Ouro por ponto foram salvos. A exceção ocorreu somente ao atualizar a matriz porque faltava a coluna status; a série não foi perdida nem será repetida. Corrigi a matriz e gerei um Gold parcial consolidado com 25 localidades em 12 UFs (24 Norte/Centro-Oeste + BA).


## Atualização ETo PE — série completa

BR_PE_PETROLINA validada: HTTP 200, 730 dias, 730 valores, zero nulos, mm/dia, GMT. Raw e manifesto Bronze, Prata e Ouro por ponto conferidos. O Gold e Prata parciais agora agregam 26 localidades em 13 UFs (24 pontos Norte/Centro-Oeste + BA + PE), 18.980 linhas sem nulos nem duplicatas. Faltam 14 UFs para ETo. Saldo 348,5286; cinco séries adicionais com reserva de 20% custariam 312,8571, projetando 35,6714 de saldo.


## Atualização ETo MG — série completa

BR_MG_MONTES_CLAROS validada: HTTP 200, 730 valores sem nulos, 2024-10-08 a 2026-10-07, unidade mm/dia, GMT. Raw, manifesto, Prata e Ouro por ponto presentes. Gold/Prata parciais agora incluem 27 localidades em 14 UFs, 19.710 linhas válidas, sem nulos ou duplicatas. Faltam 13 UFs. Saldo: 296,3857; quatro séries adicionais com margem custariam 250,2857 e deixariam saldo projetado 46,1.

