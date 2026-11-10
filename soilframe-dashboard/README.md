# Cópia reunida com a base de dados

Esta cópia usa a pasta irmã `../Base de dados`. Para instalar e executar, consulte [o README do pacote](../README.md). As referências abaixo ao caminho na Área de Trabalho e aos ambientes antigos descrevem a configuração original.

---

# SoilFrame Dashboard

Aplicação Streamlit independente para explorar dados Gold AquaCrop, visualizar previsões e iniciar execuções experimentais do SoilFrame com AutoGluon. O dashboard fica em pasta própria e instala o framework como dependência Git fixada na revisão `10cd1570b4d5d031a47aa632bfdaec61b6235330`; não altera nem armazena dados dentro do repositório SoilFrame.

## Páginas

- **Dashboard:** indicadores AquaCrop, série temporal, mapa Gold com filtros por período/região/UF/município, pontos selecionáveis, células geográficas, Voronoi, escala de valores e resumo do ponto escolhido. Os rótulos municipais e UFs vêm da malha do IBGE e são apenas de exibição.
- **Explorar dados Gold:** filtros dimensionais e de período, tabela, gráfico e exportação CSV.
- **Treinar modelo AutoML:** regressão/classificação Tabular ou previsão TimeSeries, em segundo plano.
- **Resultados preditivos:** gráficos e download de previsões concluídas.
- **Acurácia e confiabilidade do AutoML:** métricas e diagnósticos do conjunto de teste, com gráficos de classificação/regressão e comparação dos modelos candidatos.
- **Histórico de execuções:** status, duração, parâmetros, métricas e leaderboard.
- **Ingestão ERA5-Land:** dispara o pipeline AquaCrop-Lakehouse do SoilFrame com UF, ano,
  período e limite de células configuráveis.

## Documentação para apresentação

- [Aula sobre SoilFrame e AutoML](docs/AULA_SOILFRAME_AUTOML.md): narrativa de
  apresentação, explicação do fluxo AutoML, demonstração sugerida e limites.
- [Registro da refatoração](docs/REFATORACAO_E_APRESENTACAO.md): alterações,
  compatibilidade, organização e pontos de atenção conhecidos.

Os filtros geográficos compartilhados aparecem no conteúdo das páginas. Região limita a lista de UFs; a UF limita municípios e pontos do grid. A mesma seleção recorta o Dashboard, a exploração, o mapa e os dados enviados para treinamento. Na página de ingestão, a região também limita as UFs disponíveis. Os demais filtros são construídos a partir das colunas presentes; cultura/cultivar só aparece se existir na fonte.

## Separação do SoilFrame e dos dados

```text
Área de Trabalho/
├── Base de dados/               # Data Lake Gold selecionado, somente leitura
└── Soil/
    ├── soilframe-voronoi/        # checkout ativo do framework
    └── soilframe-dashboard/      # esta aplicação
```

O dashboard lê produtos Gold Parquet, CSV ou coleções locais de CSV em modo somente leitura. Ele aponta para `Área de Trabalho/Base de dados`; o Lake antigo não é uma fonte do dashboard e não foi apagado. Os produtos são selecionados separadamente por modelo e frequência, preservando sua proveniência e cobertura. Eles não são combinados automaticamente. Os bancos de histórico do app, modelos e previsões ficam em `soilframe-dashboard/outputs/`, ignorados pelo Git. A identificação de município/UF consulta as malhas simplificadas e a API de localidades do IBGE, mantém os resultados em cache e nunca grava rótulos no Data Lake. Ela depende de acesso à internet na primeira consulta. O mapa lê as colunas numéricas e geográficas da fonte Gold para agregar o período selecionado. As células geográficas e Voronoi são recortadas ao território brasileiro.

Se o ambiente já estava instalado antes desta versão do mapa, atualize as dependências geoespaciais uma vez na pasta do dashboard:

```bash
C:/venvs/soilframe/Scripts/python.exe -m pip install -e .
```

Na página **Ingestão ERA5-Land**, a execução do SoilFrame grava sua própria camada
Lakehouse em `soilframe-dashboard/outputs/lakehouse/`. O diretório do projeto
SoilFrame e o Data Lake selecionado não são usados como destino da execução.
O pipeline consulta a fonte ERA5-Land/Open-Meteo pela rede; use poucas células
e uma única UF nos primeiros ensaios.

## Instalação

O `pyproject.toml` declara Python `>=3.10` para o dashboard e extras opcionais
para AutoGluon Tabular e TimeSeries. O ambiente `soilframe-dashboard/.venv`
usa Python 3.11.9, mas não tem AutoGluon. Para a apresentação, o ambiente
`C:/venvs/soilframe` foi localizado com Python 3.11.9, Streamlit, o pacote do
dashboard e AutoGluon Tabular/TimeSeries disponíveis. Use esse ambiente no
comando de execução abaixo. A declaração do projeto não garante, sozinha,
compatibilidade de todas as dependências em qualquer versão de Python.

### Windows PowerShell: instalar em ambiente novo

```powershell
cd "C:\Users\User\OneDrive - Firjan\Área de Trabalho\Soil\soilframe-dashboard"
if (-not (Test-Path 'C:/venvs/soilframe/Scripts/python.exe')) { py -3.11 -m venv C:/venvs/soilframe }
C:/venvs/soilframe/Scripts/python.exe -m pip install --upgrade pip
C:/venvs/soilframe/Scripts/python.exe -m pip install -r requirements.txt
C:/venvs/soilframe/Scripts/python.exe -m pip install -r requirements-automl.txt
```

O extra Tabular instala `autogluon.tabular[lightgbm]`, sem o grupo `[all]`.
AutoGluon TimeSeries é separado; instale `requirements-timeseries.txt` apenas
quando for usar previsão temporal:

```bash
C:/venvs/soilframe/Scripts/python.exe -m pip install -r requirements-timeseries.txt
```

## Configurar a camada Gold

1. Inicie o dashboard.
2. Na barra lateral, escolha um produto do novo Data Lake ou informe um caminho Parquet, CSV, pasta de CSVs Gold ou SQLite.
3. Para SQLite, selecione a tabela Gold.
4. Use os filtros disponíveis para delimitar o recorte.

Opcionalmente, copie `.env.example` para `.env` e defina `SOILFRAME_GOLD_PATH` para um produto dentro de `Base de dados`. Caminhos do Lake antigo são descartados. A tabela SQLite pode ser selecionada na interface. O dashboard não cria nem modifica tabelas no Data Lake.

As páginas tabulares e de série carregam até 250.000 linhas por vez para proteger a interface. A seção do mapa lê as colunas geográficas e numéricas de toda a fonte Gold para calcular corretamente os agregados dos pontos e do período; o mapa usa cache local em memória durante a sessão.

## Executar

Na raiz desta pasta, execute pelo ambiente preparado para a apresentação:

```powershell
C:/venvs/soilframe/Scripts/python.exe -m streamlit run app.py
```

O Streamlit mostrará o endereço local no terminal, normalmente `http://localhost:8501`.

## Treinar e visualizar

Na página **Treinar modelo AutoML**, escolha o alvo, tipo de modelo, horizonte e limite de tempo. Para Tabular, o painel sugere o tipo de problema pelo tipo da coluna, pelas classes e pelo nome da variável; escolhe a separação temporal quando há data e ajusta a qualidade recomendada ao número de linhas. Essas sugestões podem ser alteradas antes de iniciar. TimeSeries é opcional e exige instalar `requirements-timeseries.txt`. O trabalho roda em um worker local para que a interface continue responsiva. O painel atualiza o estado e o cronômetro automaticamente enquanto a página permanece aberta.

Cada execução grava seu status no SQLite do dashboard e, quando concluída, salva previsões e leaderboard em `outputs/runs/<id>/`. Artefatos dos modelos vão para `outputs/models/<id>/`; o rastreamento AutoGluon Tabular usa `outputs/experiments/`. Falhas ficam no histórico para consulta.

Nas novas execuções AutoML, as opções salvas também registram o produto e o
caminho selecionados, a tabela (se SQLite), as colunas, o número de linhas e um
fingerprint SHA-256 do recorte filtrado. As execuções anteriores não recebem
esses metadados retroativamente. A tela não permite escolher datas,
identificadores ou categorias textuais quase únicas como alvo. As demais
colunas do recorte ficam disponíveis como preditoras; revise-as para evitar
vazamento de informação.

Para preparar uma nova camada Gold experimental, abra **Ingestão ERA5-Land**, escolha a
UF, o ano, o período e o número máximo de células por UF e inicie a execução.
O andamento e o relatório aparecem na mesma página; os arquivos ficam dentro
da pasta `outputs/lakehouse/` do dashboard.

## Estado experimental e limites

- Os resultados são experimentais; valide métricas, períodos e localidades antes de qualquer uso operacional.
- O schema AquaCrop Gold deste projeto inclui variáveis climáticas e indicadores como `precipitacao_mm`, `et0_mm`, `balanco_hidrico_diario` e `classe_deficit_hidrico`. `SWI_010` só pode ser selecionado se vier no dataset conectado.
- Treino tabular com validação temporal requer a coluna `data`; validação por localidade requer `location_id` ou `cell_id`.
- TimeSeries requer ID de série, timestamp, alvo numérico e histórico suficiente para o horizonte definido.
- Execuções são locais e usam um único worker; o app não é um serviço multiusuário de produção nem inicia operações de irrigação.
- A instalação da integração AutoGluon deve respeitar a compatibilidade de Python documentada pelo projeto AutoGluon.

## Smoke test

O teste de integração da fonte Gold usa CSV sintético temporário e verifica a
descoberta do caminho configurado e a leitura dos dados, sem acessar produtos
reais. Execute com `python -m unittest discover -s tests -p test_dashboard_smoke.py`.
