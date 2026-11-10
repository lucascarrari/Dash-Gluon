# SoilFrame

Framework modular de MLOps agrometeorológico para preparar dados climáticos e de solo, treinar modelos preditivos e apoiar análises relacionadas ao FAO AquaCrop.

> **Estado da integração:** SoilFrame sabe ler arquivos Parquet e SQLite locais, mas não vem conectado por padrão ao Data Lake Acquacrop de uma instalação específica. Configure os caminhos, tabelas e colunas que existem no seu ambiente.

## Visão geral

O SoilFrame organiza fontes de dados, pipelines, modelos, métricas e artefatos em componentes reutilizáveis. O projeto trabalha com variáveis de reanálise ERA5-Land, como precipitação e temperatura da superfície, e com variáveis agrometeorológicas derivadas para estudos de culturas e AquaCrop.

A estrutura é modular: pipelines preparam os dados; modelos fazem treino ou inferência; estratégias selecionam o motor de execução; rastreadores salvam métricas e resultados. Os cálculos físicos existentes continuam úteis como referência e para geração de variáveis. Modelos de machine learning podem aprender relações observadas nos dados para produzir previsões, mas precisam ser avaliados no contexto de cada variável e conjunto de dados.

## Arquitetura de dados: Data Lake Medallion

O fluxo esperado para uma integração local segue as camadas Medallion:

1. **Bronze:** dados originais ou recebidos das fontes, preservados com o mínimo de transformação.
2. **Silver:** dados limpos, tipados, deduplicados e harmonizados por localidade e data.
3. **Gold:** tabelas prontas para consumo analítico e modelagem, por exemplo dados diários ERA5-Land e variáveis AquaCrop.

O Data Lake pode persistir esses dados em arquivos **Parquet** ou tabelas **SQLite**. O SoilFrame lê ambos para Pandas. O projeto não presume nomes de tabelas: informe o caminho e a tabela ou consulta que correspondam ao seu Data Lake.

Exemplo de fonte Parquet: `data/gold/acquacrop_era5_land_diario.parquet`.

Exemplo de fonte SQLite: `data/gold/acquacrop_gold.sqlite`, com uma tabela Gold selecionada na configuração do modelo.

## Motor de Machine Learning: AutoGluon

A integração do AutoGluon é opcional e fica atrás do padrão **Strategy**, em `soilframe.core.strategy`. `AutoGluonStrategy` encapsula carregamento dos dados, criação do predictor, treinamento, inferência, leaderboard e importância de variáveis. A estratégia pode operar com:

- **TabularPredictor:** classificação e regressão sobre linhas tabulares. Por exemplo, um regressor pode aprender a prever `SWI_010` (Índice de Água no Solo) ou `eto_mm` (ET₀) a partir de dados históricos e variáveis explicativas.
- **TimeSeriesPredictor:** previsão de horizontes futuros por série, identificada por localidade e timestamp. Pode ser usado com dados sazonais ou decendiais depois que o pipeline fornece as colunas de série, tempo, alvo e covariáveis necessárias.

O AutoGluon aprende padrões dos dados e fornece previsões e métricas. Isso não significa que todo cálculo físico FAO AquaCrop seja substituído automaticamente: os pipelines sazonais e decendiais existentes preparam dados; a seleção de alvo, horizonte e validação do modelo deve ser configurada para a pergunta agrometeorológica.

`ModeloSolo` usa regressão tabular e, por padrão, prevê `SWI_010`. `ModeloAutoGluonTabular` é o adaptador genérico para outros alvos. `AutoGluonTracker` grava `leaderboard.csv`, `feature_importance.csv` e `experiment.json` no diretório de artefatos.

## Requisitos

- Windows, Linux ou macOS.
- Python 3.10 ou superior para o SoilFrame.
- Dependências descritas em `requirements.txt`.
- Arquivos Parquet requerem PyArrow.
- SQLite está incluído na biblioteca padrão do Python.

### Compatibilidade do Python com AutoGluon

O ambiente solicitado pode ser criado com Python 3.14, mas a documentação oficial atual do AutoGluon lista suporte até Python 3.13. Portanto, a instalação ou execução do AutoGluon em Python 3.14 pode falhar até que o projeto publique suporte compatível. Para treinar com AutoGluon hoje, use Python 3.13 em um ambiente separado. Consulte a [documentação oficial de instalação do AutoGluon](https://auto.gluon.ai/stable/install.html) antes de escolher a versão.

## Instalação e configuração

### Windows PowerShell

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

Se o AutoGluon não instalar em Python 3.14, crie o ambiente de treino com a versão Python atualmente suportada:

```powershell
py -3.13 -m venv .venv-autogluon
.\.venv-autogluon\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

### Bash

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

Para instalar apenas as dependências opcionais por meio do `pyproject.toml`, use `pip install -e ".[automl]"`. O `requirements.txt` inclui as dependências de AutoGluon para facilitar a configuração completa do ambiente.

## Uso básico

O exemplo usa um arquivo Parquet de Gold com as colunas `location_id`, `data` e `SWI_010`. `PipelineSazonal` carrega o histórico; `AutoGluonStrategy` ajusta um modelo temporal e prevê os próximos dez períodos.

```python
from pathlib import Path

from soilframe.core.strategy import AutoGluonStrategy
from soilframe.pipelines.pipeline_sazonal import PipelineSazonal

parquet_gold = Path("data/gold/acquacrop_era5_land_diario.parquet")

historico_dataset = PipelineSazonal().rodar(
    {"dados_entrada": str(parquet_gold)}
)
historico = historico_dataset.data

strategy = AutoGluonStrategy(
    task_type="timeseries",
    target="SWI_010",
    path="outputs/models/swi_sazonal/autogluon",
    prediction_length=10,
    item_id_column="location_id",
    timestamp_column="data",
    freq="D",
    time_limit=300,
    data_uri=parquet_gold,
)

strategy.fit(historico)
previsoes = strategy.predict(historico)
print(previsoes.head())
print(strategy.leaderboard())
```

Para regressão tabular, o adaptador `ModeloSolo` lê uma tabela SQLite Gold em Pandas, separa treino e teste temporalmente e registra métricas e diagnósticos:

```python
from soilframe import AutoGluonTracker, Registry

tracker = AutoGluonTracker("outputs/experiments")
modelo_swi = Registry().get_model(
    "modelo_solo",
    caminho_modelo="outputs/models/swi_tabular/autogluon",
    data_uri="data/gold/acquacrop_gold.sqlite",
    sqlite_table="openmeteo_era5_land_daily",
    limite_tempo=300,
    tracker=tracker,
)

modelo_swi.treinar(None)
previsoes = modelo_swi.prever_sqlite(
    sqlite_table="openmeteo_era5_land_daily"
)
print(modelo_swi.metricas_teste)
print(previsoes.data.head())
```

A tabela ou consulta SQLite precisa fornecer a variável alvo e as colunas explicativas. Para a validação temporal padrão, inclua uma coluna `data` com pelo menos duas datas distintas. `sqlite_query` aceita uma consulta `SELECT` ou `WITH ... SELECT` somente de leitura.

## Resultados e rastreamento

O caminho `artifact_dir` do `AutoGluonTracker` guarda uma pasta por execução contendo, quando disponíveis:

- `experiment.json`: configuração, métricas e metadados do modelo e da pipeline;
- `leaderboard.csv`: comparação dos modelos AutoGluon;
- `feature_importance.csv`: importância das variáveis calculada pelo predictor.

Se uma rotina de diagnóstico falhar, o erro correspondente fica registrado em `diagnostic_errors` dentro do JSON. Isso permite consultar o status do diagnóstico sem perder as métricas principais do treinamento.

## Estrutura do projeto

```text
soilframe/
├── core/
│   ├── model.py
│   ├── strategy.py
│   ├── tracking.py
│   └── ...
├── models/
│   ├── modelo_solo.py
│   └── modelo_autogluon.py
├── pipelines/
│   ├── pipeline_sazonal.py
│   ├── pipeline_decenal.py
│   └── ...
├── lakehouse/
├── download/
├── soil_analysis/
├── requirements.txt
└── pyproject.toml
```

## Limitações e validação do modelo

- O caminho, a tabela, os nomes das colunas e a frequência do Data Lake devem corresponder aos dados reais.
- `SWI_010` é o alvo padrão do `ModeloSolo`; altere-o se a camada Gold usar outro nome.
- Uma previsão estatística não substitui validação agronômica, validação temporal sem vazamento de dados ou comparação com baselines.
- `TimeSeriesPredictor` requer histórico suficiente por série e timestamps coerentes com `freq`.
- O framework não executa conexão remota ou sincronização automática com o Data Lake; a integração aqui é por arquivos e SQLite acessíveis localmente.
