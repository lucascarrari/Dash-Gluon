# SoilFrame — dashboard, base de dados e Voronoi master

Esta pasta reúne uma cópia do dashboard ativo, a base de dados que ele usa
e o Voronoi master com os scripts de busca de dados.
Os arquivos originais foram preservados. Separação realizada em 10/11/2026.

```text
SoilFrame-Dashboard-e-Dados/
├── Base de dados/                # base completa: Bronze, Prata e Gold
├── soilframe-dashboard/          # aplicação Streamlit, páginas e recursos
│   └── outputs/                  # histórico SQLite, modelos e previsões
├── soilframe-voronoi-master/     # scripts de busca, framework e dados auxiliares
│   └── soilframe/                # projeto Python instalável do framework
├── iniciar_dashboard.bat
├── manifesto_base_de_dados.json # inventário com hashes SHA-256
└── manifesto_voronoi_master.json
```

## O que o projeto usa

O dashboard lê os produtos de `Base de dados/3_ouro` em CSV e Parquet.
Há seis opções de produtos: temperatura e solo diários ERA5-Land,
precipitação diária ERA5, ETo diária parcial ERA5-Seamless, AquaCrop horário
ERA5-Land e dois produtos horários regionais ERA5. Cada produto é selecionado
separadamente na interface; eles não são unidos automaticamente.

O caminho de descoberta foi ajustado nesta cópia para a base dentro desta
pasta. O `DataLake OpenMeteo` da raiz de Soil é legado e não é usado pelo
dashboard atual.

O framework `soilframe` é uma dependência Python instalada pelo Git, fixada
na revisão `10cd1570b4d5d031a47aa632bfdaec61b6235330` no `pyproject.toml`.
A pasta `soilframe-voronoi-master` incluída preserva os scripts de busca e
o framework local; sua inclusão não altera essa dependência do dashboard.

## Voronoi master e buscas de dados

A pasta `Soil/soilframe-voronoi-master` estava vazia. Seu conteúdo havia sido
arquivado em `archive/soilframe-voronoi-snapshot/source`; essa foi a origem da
cópia adicionada aqui. Foram copiados 97 arquivos, conferidos por SHA-256,
incluindo o framework, os dados auxiliares, os outputs e os scripts:

- `baixar_aquacrop_brasil_lakehouse.py`
- `baixar_aquacrop_brasil_3anos_lakehouse.py`
- `baixar_aquacrop_brasil_5anos_lakehouse.py`
- `baixar_aquacrop_era5_mg.py`

O projeto instalável fica em `soilframe-voronoi-master/soilframe`, com
`pyproject.toml`, `requirements.txt`, documentação e testes. Para preparar
um ambiente próprio, partindo da raiz deste pacote:

```powershell
cd soilframe-voronoi-master
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\soilframe
```

Para executar uma busca, use esse ambiente e mantenha o diretório atual em
`soilframe-voronoi-master`. Revise o período, as UFs e o destino no script
antes de executá-lo. Os scripts nacionais usam por padrão
`soilframe/data/lakehouse`, relativo a esse diretório; eles não atualizam
automaticamente `Base de dados/3_ouro`. Nenhuma busca ou treinamento foi
disparado durante esta organização.

## Preparar e executar no Windows

É necessário ter Python 3.11 e Git instalados e acesso à internet para baixar
as dependências. No PowerShell, abra esta pasta e execute:

```powershell
cd soilframe-dashboard
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-automl.txt
# Opcional: previsão temporal
.\.venv\Scripts\python.exe -m pip install -r requirements-timeseries.txt
```

Depois, abra `iniciar_dashboard.bat` nesta pasta. O endereço normalmente é
`http://localhost:8501`. A interface permite selecionar os produtos Gold.
O mapa consulta o IBGE pela internet na primeira utilização.

## Validação e limitações

A base copiada é conferida arquivo a arquivo por SHA-256; o manifesto registra
os tamanhos e os hashes. O histórico SQLite foi verificado com
`PRAGMA integrity_check`, e seus caminhos textuais foram ajustados para esta
cópia. Os artefatos de modelos foram preservados sem alterar seu conteúdo.
Metadados internos de bibliotecas podem conter referências ao local original.
Se esta pasta for movida novamente, caminhos absolutos de execuções antigas
podem exigir ajuste; novas execuções gravam no destino atual.

Ambientes virtuais, caches Python, metadados de instalação e arquivos `.env`
não foram copiados. Na análise, os ambientes virtuais existentes apontavam
para um executável Python ausente. Por isso não foi possível executar o app
ou seus testes Python nesta máquina; a instalação acima é necessária para
validar a interface e utilizar os modelos.
