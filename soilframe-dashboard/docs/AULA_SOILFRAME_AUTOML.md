# Aula: SoilFrame, dados agroclimáticos e AutoML

**Público:** equipe que vai conhecer a apresentação prévia do projeto.  
**Duração sugerida:** 20 a 30 minutos.  
**Objetivo:** explicar o dashboard SoilFrame, demonstrar um treinamento
supervisionado e mostrar quando o AutoML ajuda — e o que ele não resolve.

## 1. A ideia do projeto

O SoilFrame reúne fluxos para explorar dados relacionados a solo e clima,
consultar produtos Gold, visualizar valores por localidade e executar análises
ou modelos. O dashboard é a camada de interação: permite selecionar uma fonte,
filtrar região, UF, município, localidade, período e variável, visualizar os
dados e iniciar tarefas experimentais.

O projeto também inclui integração a pipelines AquaCrop/ERA5-Land. Essa ingestão
é um fluxo separado do AutoML: pode preparar dados para o Lakehouse local do
dashboard, enquanto a página de treinamento aprende a partir do recorte Gold
selecionado.

## 2. O que é AutoML neste projeto

AutoML automatiza partes do treinamento de modelos de aprendizado de máquina.
Neste dashboard, a integração usa AutoGluon para comparar e ajustar modelos a
partir de uma tabela, segundo a tarefa e os limites escolhidos. A pessoa usuária
define os dados, o alvo, o tipo de problema, a forma de validação, o preset de
qualidade e o tempo disponível.

O fluxo é **supervisionado**: cada linha precisa ter um alvo conhecido para o
modelo aprender a relação entre as demais colunas e esse alvo. Exemplos
possíveis, quando existem no produto selecionado, são prever uma variável
contínua como ET₀ ou classificar uma categoria de déficit hídrico.

O AutoML é útil aqui porque dados agroclimáticos podem ter relações não lineares
entre clima, solo, localização e período. Ele acelera a comparação de modelos
sem exigir que a pessoa escolha manualmente cada algoritmo e hiperparâmetro.
Isso o torna útil para explorar hipóteses e criar uma linha de base para
discussão, com métricas registradas para comparação.

## 3. Regressão, classificação e série temporal

- **Regressão:** prevê um valor numérico, como uma variável contínua de solo ou
  clima. O dashboard calcula MAE, RMSE e R² no conjunto de avaliação.
- **Classificação binária:** prevê uma entre duas classes. O fluxo reporta
  acurácia e F1.
- **Classificação multiclasse:** prevê uma classe entre três ou mais. O fluxo
  reporta acurácia e F1 macro.
- **TimeSeries opcional:** usa identificador da série, data, variável numérica,
  frequência e horizonte para produzir previsões futuras. Requer o extra
  `requirements-timeseries.txt`.

Os nomes das métricas e a implementação concreta estão no código da página de
treinamento, no módulo local `soilframe_dashboard/metrics.py` e no adaptador
AutoGluon do SoilFrame.

## 4. Como demonstrar no dashboard

1. Abra a página **Treinar modelo AutoML**.
2. Escolha uma fonte Gold e filtre a área e o período de interesse. Explique que
   a aplicação trabalha com o recorte carregado e exibe seu número de linhas.
3. Escolha uma variável de resultado que tenha dados suficientes e represente
   uma pergunta concreta. Datas e identificadores não são alvos elegíveis.
4. Escolha regressão/classificação e a separação de avaliação disponível.
5. Explique o limite de tempo e o preset antes de iniciar. Um preset maior pode
   consumir mais recursos e não garante melhor generalização.
6. Inicie o treino e mostre o status, a duração, as métricas, o leaderboard e as
   previsões de teste quando a execução terminar.
7. Abra **Histórico de execuções** para explicar como a configuração e o resumo
   do recorte ajudam a interpretar e comparar resultados.

Para uma apresentação ao vivo, escolha previamente um recorte pequeno e com
alvo bem preenchido. O tempo real varia conforme o ambiente e a disponibilidade
das dependências opcionais.

## 5. Como interpretar a validação

**Temporal:** o SoilFrame ordena as datas e reserva as datas finais para teste.
É uma aproximação para a pergunta “como o modelo se sai em períodos
posteriores?”. Se as localidades aparecem no período de treino e no período de
teste, isso não mede previsão em uma localidade inédita.

**Por localidade:** separa grupos geográficos entre treino e teste. É mais
apropriada para discutir transferência a pontos não vistos, desde que existam
localidades suficientes e dados representativos em cada grupo.

Uma métrica só descreve aquele alvo, aquela fonte, aquele recorte, aquela
configuração e aquela divisão. R² alto ou erro baixo no teste não provam que o
modelo será igualmente bom em outra região, cultura, período ou versão do Lake.

## 6. Por que AutoML é útil para este tipo de projeto

- **Agiliza a exploração:** compara modelos sem construir um pipeline manual
  para cada algoritmo.
- **Cria uma referência:** as métricas ajudam a comparar uma primeira solução
  com regras simples ou com futuras versões do projeto.
- **Aproveita relações conjuntas:** pode encontrar combinações de variáveis que
  uma inspeção de gráficos isolados não revela.
- **Torna hipóteses discutíveis:** o resultado ajuda a formular perguntas,
  como quais variáveis ou localidades merecem análise adicional.
- **Permite uma interface única:** seleção da fonte, treinamento, histórico e
  previsões ficam no mesmo dashboard.

Esses benefícios dependem de alvos corretos, proveniência conhecida, cobertura
adequada e validação que reflita o uso previsto.

## 7. O que o AutoML não faz

- Não coleta nem completa automaticamente dados ausentes do Data Lake.
- Não confirma a qualidade, unidade ou proveniência de uma variável.
- Não transforma métricas experimentais em validação agronômica.
- Não substitui o modelo AquaCrop, conhecimento de campo ou desenho de
  experimento.
- Não decide recomendação de plantio ou irrigação e não aciona equipamentos.
- Não garante desempenho em localidades ou condições fora dos dados usados.

## 8. Cuidados e perguntas para a equipe

- O alvo está medido de maneira consistente e tem unidades conhecidas?
- Há colunas que reproduzem ou calculam diretamente o alvo? Elas podem causar
  vazamento e fazer a métrica parecer melhor do que será na prática.
- A validação representa o uso pretendido: datas futuras, localidades novas ou
  ambos?
- O recorte contém cobertura espacial e temporal suficiente?
- A fonte e as colunas do recorte estão registradas para reproduzir a análise?

No código atual, as demais colunas do recorte são disponibilizadas ao modelo
como preditoras; ainda não existe uma seleção manual de atributos na interface.
Por isso, reveja o schema e possíveis variáveis derivadas do alvo antes de
interpretar os resultados.

## 9. Encerramento sugerido

“O SoilFrame conecta dados agroclimáticos a exploração e experimentação com
modelos. O AutoML acelera a comparação de modelos para alvos bem definidos, mas
seu valor vem de dados rastreáveis e de uma validação que represente o cenário
real. Hoje, o resultado é uma ferramenta de análise prévia, não uma decisão
operacional.”

## Arquivos para consulta

- Interface de treino: `pages/training.py`
- Regras de alvo e recomendações: `soilframe_dashboard/training_config.py`
- Execução em segundo plano e histórico: `soilframe_dashboard/jobs.py`
- Métricas exibidas: `soilframe_dashboard/metrics.py`
- Instalação e execução: `README.md`
