# Fontes de dados

O SoilFrame usa o contrato `FonteDados` para padronizar a extração e a
validação das entradas antes de entregá-las às pipelines.

## Contrato

```python
fonte = FonteDados(...)
dados = fonte.dataset()
```

O método `dataset()` executa `extrair()`, chama `validar_schema()` e retorna
um `Dataset` com os metadados da fonte.

- `extrair() -> pandas.DataFrame`: lê e retorna os dados.
- `validar_schema(dados=None) -> bool`: verifica as colunas obrigatórias.
- `dataset() -> Dataset`: combina extração, validação e metadados.

## Fontes disponíveis

- `INMET`: arquivo local identificado como fonte INMET.
- `ERA5`: arquivo local identificado como fonte ERA5.
- `Xavier`: arquivo local identificado como fonte Xavier.
- `S3Curado`: arquivo local ou URI `s3://`; URIs S3 são lidas como Parquet
  usando `s3fs`.
- `ArquivoFonte`: fonte genérica para CSV, Parquet, JSON e GeoJSON.

Exemplo:

```python
from soilframe import INMET

fonte = INMET(
    "data/raw/estacoes.csv",
    schema={"latitude": float, "longitude": float},
)
dados = fonte.dataset()
```

As classes INMET, ERA5 e Xavier atualmente padronizam arquivos locais; elas
não fazem download direto das APIs externas. O caminho deve existir e o
formato precisa ser suportado pelo leitor.

## Uso com pipeline

```python
pipeline = PipelinePrecipitacao(fonte=fonte)
pipeline.ajustar()
resultado = pipeline.transformar()
```

Quando uma pipeline recebe uma `FonteDados`, ela usa `fonte.dataset()` como
entrada sempre que nenhum dado explícito é fornecido.
