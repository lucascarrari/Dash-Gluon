# Registro da refatoração e preparação para apresentação

**Data:** 9 de novembro de 2026  
**Escopo:** aplicação `soilframe-dashboard` e seu fluxo de AutoML.  
**Fora do escopo:** Data Lakes, produtos Bronze/Prata/Ouro, modelos já salvos,
histórico local de execuções e cópias paralelas do framework.

## Objetivo

Deixar o dashboard mais fácil de explicar e de depurar em uma apresentação
prévia, reduzindo escolhas inválidas no treinamento e tornando as novas
execuções mais rastreáveis.

## Alterações realizadas

1. **Regras do formulário de AutoML extraídas da página.** As recomendações de
   problema e de qualidade e a seleção de alvos agora ficam em
   `soilframe_dashboard/training_config.py`. A página
   `pages/training.py` concentra a interface e a montagem da configuração.
2. **Alvos elegíveis filtrados.** Datas e campos identificadores geográficos não
   aparecem como alvos tabulares. Variáveis numéricas com pelo menos dois
   valores continuam elegíveis para regressão. Categorias textuais com
   cardinalidade muito alta são omitidas como provável identificador ou texto
   livre. Em TimeSeries, só variáveis numéricas são apresentadas como alvo.
3. **Validação antes do envio.** O formulário exige duas datas válidas para a
   divisão temporal e duas localidades/células com alvo preenchido para a
   divisão espacial. A série temporal também precisa ter datas válidas,
   histórico mínimo e valores distintos no alvo.
4. **Explicação na interface.** A tela avisa que a coluna escolhida é o
   resultado a prever e que as demais colunas do recorte ficam disponíveis como
   preditoras.
5. **Rastreabilidade para novas execuções.** `JobManager` acrescenta às opções
   salvas um resumo do recorte usado: caminho e tabela de origem, rótulo do
   produto, linhas, nomes de colunas e `fingerprint_sha256`. O fingerprint é
   calculado sobre o DataFrame filtrado, incluindo o índice.
6. **Documentação da aula.** Foi criado
   `docs/AULA_SOILFRAME_AUTOML.md`, com a narrativa da apresentação, o fluxo de
   uso, o papel do AutoML, uma demonstração sugerida e os limites dos resultados.
7. **Navegação da documentação.** O README agora aponta para este registro e
   para a aula.

## Nomes e compatibilidade

Não foram renomeados classes, variáveis de schema, colunas do Lake ou IDs de
execução. As funções `recommend_problem_type` e `recommend_quality` continuam
com os mesmos nomes, mas foram movidas de `pages/training.py` para
`soilframe_dashboard/training_config.py`; são funções internas do formulário,
sem contrato público documentado.

As opções de novas execuções mantêm as chaves existentes. Foi adicionado o
objeto `dataset_snapshot` dentro de `options_json`; os registros antigos não
são reescritos e não terão esse campo retroativamente.

## Estrutura relevante para apresentação

```text
soilframe-dashboard/
├── app.py                         # inicialização e navegação
├── pages/                         # uma página Streamlit por fluxo
├── soilframe_dashboard/           # acesso a dados, filtros, mapas, jobs
│   └── training_config.py         # elegibilidade e sugestões de treino
├── docs/
│   ├── AULA_SOILFRAME_AUTOML.md
│   └── REFATORACAO_E_APRESENTACAO.md
├── outputs/                       # banco, modelos, previsões e experimentos locais
└── requirements*.txt / pyproject.toml
```

`outputs/`, ambientes virtuais, caches e instalações editáveis são artefatos
locais e permanecem fora da documentação versionável. Não foram removidos nem
movidos durante esta refatoração.

## Limites conhecidos que devem ser apresentados

- O dashboard usa um worker local e um treinamento simultâneo; não é serviço
  multiusuário de produção.
- AutoML é aprendizado supervisionado. Ele não preenche lacunas do Lake, não
  substitui o AquaCrop e não controla irrigação.
- Na integração atual, as colunas não escolhidas como alvo são fornecidas ao
  adaptador como preditoras. A tela não oferece exclusão manual de atributos;
  por isso, relações derivadas do alvo podem causar vazamento de informação.
- A validação temporal testa datas posteriores do mesmo recorte e pode manter
  as mesmas localidades nos dois lados. A validação por localidade mede melhor
  transferência espacial quando há pontos suficientes.
- Execuções anteriores à alteração não guardam caminho ou fingerprint dos
  dados. Suas métricas não podem ser associadas com certeza ao produto atual.
- A leitura do dashboard limita a quantidade de linhas carregadas. Registre o
  recorte efetivamente carregado ao comparar execuções.

## Verificação

Os arquivos Python alterados passaram por compilação sintática com `py_compile`.
Os testes automatizados e uma execução real de treinamento não foram executados.
Nenhum Data Lake foi alterado. A disponibilidade de AutoGluon depende do
ambiente Python e dos extras opcionais documentados no README. O ambiente
`soilframe-dashboard/.venv` não tem AutoGluon; `C:/venvs/soilframe` foi
localizado com Streamlit, o pacote do dashboard e os módulos AutoGluon Tabular
e TimeSeries disponíveis.
