# Relatório de execução, erros e treinos — 10/11/2026

O dashboard funciona parcialmente no ambiente disponível. O servidor HTTP
respondeu com status 200 e health `ok`; as seis fontes Gold foram abertas.
O AutoML não está operacional nesta execução: as três tentativas curtas
falharam antes de ajustar modelos por ausência do AutoGluon no Python utilizável.
Não houve treino novo concluído, nem métricas novas de qualidade preditiva.

## Escopo e ambiente

Foi avaliada a cópia em `SoilFrame-Dashboard-e-Dados`, incluindo o dashboard,
a base real e o framework de `soilframe-voronoi-master/soilframe`.
Nenhum arquivo da base foi alterado. Não foram disparados downloads nacionais
ou treinos longos. Os testes de treino gravaram em `validacao/treinos`,
separadamente do histórico anterior do dashboard.

Os ambientes `C:/venvs/soilframe` e `soilframe-dashboard/.venv` usam Python
3.11.9 e apontam para um executável base ausente. O primeiro contém diretórios
de AutoGluon 1.6.3 e scikit-learn, mas isso não o torna executável.

Foi encontrado um Python funcional em
`C:/Users/User/AppData/Local/AcquaCropDashboard/venv/Scripts/python.exe`:
Python 3.12.14, pandas 3.1.0, NumPy 2.5.4, Streamlit 1.66.1,
PyArrow 24.0.0, SciPy 1.18.1, Shapely 2.2.0 e PyProj 3.8.0.
Nesse ambiente faltam AutoGluon Tabular, AutoGluon TimeSeries, scikit-learn
e python-dotenv. Portanto, os resultados não equivalem a uma instalação
completa das dependências declaradas pelo projeto.

Para testar a interface, foi reutilizado somente o pacote Python puro
`dotenv` do ambiente antigo em `validacao/deps`. O framework local foi
adicionado ao caminho de importação pelo script de auditoria. Nenhuma
extensão binária de Python 3.11 foi carregada no Python 3.12 e o código
de produção não foi modificado para contornar essas dependências.

As tentativas de baixar Python e obter dependências não tiveram acesso à
rede. A consulta ao IBGE retornou `WinError 10013`, indicando bloqueio de
socket por permissões do ambiente. A instalação completa e a validação
dos modelos permanecem pendentes.

## Resultados dos testes

| Verificação | Resultado observado |
|---|---|
| Sintaxe de 72 arquivos Python | Sem erro de sintaxe |
| Smoke test existente do dashboard | 1 teste aprovado |
| Leitura das seis fontes Gold reais | Aprovada, com problemas de tipos numéricos descritos abaixo |
| Servidor Streamlit em porta local 8517 | HTTP 200 e health `ok` |
| Dashboard principal | Executou, com tabelas; conteúdo numérico afetado pelos decimais |
| Explorar dados Gold | Executou, com tabelas |
| Mapa Gold | Erro tratado de consulta geográfica ao IBGE; mapa não validado |
| Treinar AutoML | Exibe aviso de AutoGluon ausente e bloqueia o formulário |
| Resultados preditivos | Abriu previsões preexistentes; não gerou novas |
| Acurácia e confiabilidade | Exceção `No module named 'sklearn'` |
| Histórico de execuções | Abriu e exibiu registros preexistentes |
| Ingestão ERA5-Land | Formulário abriu; ingestão externa não executada |

A interface foi exercitada por `streamlit.testing.v1.AppTest`, usando o
código real das páginas. Não foi feita inspeção visual em navegador.
O health HTTP sozinho não comprova que páginas, mapas ou AutoML funcionem;
por isso seus resultados são apresentados separadamente.

## Treinos rápidos executados pelo worker

Foram submetidos três jobs reais ao `JobManager`, com 1.200 linhas da fonte
ERA5-Seamless ETo, limite de ajuste de 15 segundos por job e worker sequencial.
O alvo `eto_mm` foi normalizado apenas na cópia em memória da auditoria,
para impedir que o defeito de decimais mascarasse a avaliação do motor.
As bibliotecas de AutoML não foram simuladas.

| ID | Tarefa | Configuração | Resultado |
|---|---|---|---|
| `c8abbb075bfc` | Regressão de `eto_mm` | `medium_quality`, separação temporal | Falhou em 0,07 s; AutoGluon Tabular ausente |
| `f62f555942c5` | Classificação binária | `medium_quality`, classe de auditoria criada por limiar da ETo | Falhou em 0,01 s; AutoGluon Tabular ausente |
| `abfa37ce4356` | Série temporal de `eto_mm` | `fast_training`, frequência diária, horizonte de 3 dias | Falhou em 0,01 s; AutoGluon TimeSeries ausente |

As durações são o tempo até a falha, não tempos de ajuste bem-sucedido.
O rótulo binário foi criado somente para exercitar a chamada de classificação;
não representa uma classificação agronômica validada.

O worker persistiu opções, fingerprint do recorte, horários, status e erro
no SQLite `validacao/treinos/dashboard_runs.sqlite3`. Nenhum desses jobs
gerou leaderboard, previsões ou modelo treinado.

Também há seis registros `completed` e um `failed` no histórico copiado
original, com durações entre aproximadamente 60 e 619 segundos para os
concluídos. Eles são evidência histórica de execuções anteriores, não prova
de funcionamento do AutoML no ambiente atual. Seus modelos não foram
recarregados nem reavaliados nesta auditoria.

## Erros e bugs confirmados

### 1. Bloqueador: ambientes de execução antigos quebrados

Os executáveis dos ambientes antigos respondem com erro de Python base
ausente. O arquivo `iniciar_dashboard.bat` do pacote também depende de uma
`.venv` local que ainda precisa ser preparada.

**Impacto:** não é possível executar diretamente a instalação documentada
nem aproveitar os pacotes de AutoML instalados para Python 3.11.

**Correção proposta:** disponibilizar o Python compatível e recriar um
ambiente dentro do pacote, instalar o dashboard e os extras de AutoML,
e repetir esta auditoria nesse ambiente. Não basta copiar a `.venv` antiga.

### 2. Alta: números com vírgula são interpretados como texto

`soilframe_dashboard/data_access.py`, na leitura de CSV, detecta o separador
de colunas, mas não trata o separador decimal. As fontes reais têm vírgula
decimal e, no caso da ETo, formatos mistos no mesmo produto.

| Coluna/fonte | Linhas | Valores aproveitados por `pd.to_numeric(..., errors='coerce')` atual | Após normalização decimal |
|---|---:|---:|---:|
| `tmax_c`, ERA5-Land diário | 48.910 | 4.871 | 48.910 |
| `tmin_c`, ERA5-Land diário | 48.910 | 4.840 | 48.910 |
| `precipitation_mm`, ERA5 diário | 19.710 | 7.625 | 19.710 |
| `eto_mm`, ERA5-Seamless | 22.630 | 17.520 | 22.630 |
| Latitude/longitude, ERA5-Land diário | 48.910 | 0 em cada coluna | 48.910 em cada coluna |

Exemplo real: `"35,4"` permanece texto, e não o número `35.4`.
Na recomendação de problema, temperaturas e ETo são sugeridas como
`multiclass`; esses alvos também ficam fora da seleção numérica de TimeSeries.
Mapas e gráficos que convertem com `errors='coerce'` perdem observações.

No teste da separação de regressão sobre 1.200 linhas da fonte padrão,
restaram apenas 87 linhas de treino e 22 de teste após conversão numérica
sem normalização: 1.091 observações foram descartadas silenciosamente.

**Correção proposta:** centralizar a leitura/normalização numérica para
as variáveis climáticas e coordenadas, com validação de schema. Aplicar
também nos leitores de mapa e geografia, que leem CSV separadamente.
Usar apenas `decimal=','` não resolve sozinho as colunas com formatos mistos.
Criar testes com vírgula, ponto e mistura no mesmo produto.

### 3. Alta: página de acurácia encerra com exceção de dependência ausente

`pages/model_accuracy.py` importa `sklearn.metrics` e
`sklearn.calibration` ao abrir os resultados de classificação, sem uma
mensagem de instalação equivalente à página de treino.

**Impacto:** o histórico e as previsões abrem, mas a página de acurácia
falha com `ModuleNotFoundError`. A instalação básica do dashboard não
declara scikit-learn diretamente; ele chega pelas dependências opcionais.

**Correção proposta:** declarar a dependência da funcionalidade ou tratar
a ausência com instrução de instalação e bloqueio controlado da página.

### 4. Média: a mensagem de falha de treino omite a causa original

`JobManager._run`, em `soilframe_dashboard/jobs.py`, usa
`traceback.format_exception_only`. Nos dois jobs tabulares, o histórico
guarda apenas `RuntimeError: Falha durante o treinamento do modelo SoilFrame.`

A execução diagnóstica direta confirmou a cadeia:
`ModuleNotFoundError: autogluon` → `ImportError: TabularPredictor não está
instalado` → `RuntimeError: Falha durante o treinamento do modelo SoilFrame.`

**Impacto:** o usuário não vê a dependência que precisa corrigir.

**Correção proposta:** preservar a cadeia completa em log por execução e
mostrar no histórico uma mensagem curta que inclua a causa raiz.

### 5. Média: mapa indisponível sem consulta externa bem-sucedida

A página de mapa retornou erro tratado ao consultar o IBGE, com
`WinError 10013`. Não houve crash do dashboard, mas o mapa não foi exibido.
O problema de coordenadas com vírgula é adicional e independente da rede.

**Correção proposta:** corrigir a normalização das coordenadas e permitir
um modo básico com coordenadas e UFs já presentes na base; manter a
identificação municipal como enriquecimento opcional ou usar cache local
distribuído junto do pacote.

## Limitações observadas, sem classificá-las como falhas de treinamento

- **Recorte antes dos filtros:** o limite intencional de 250.000 linhas é
  aplicado antes da seleção de localidade/período. Na coleção de expansão,
  existem 280.320 linhas e 16 arquivos; o recorte contém somente 15 IDs e
  exclui `BR_SP_RIBEIRAO_PRETO`. Filtrar depois não recupera essa localidade.
  Isso também afeta a representatividade dos treinos. Recomenda-se filtrar
  na fonte, paginar, ou sinalizar claramente a cobertura do recorte.
- **Avisos de API:** o Streamlit registra avisos de descontinuação de
  `use_container_width`; não impediram a execução nesta versão.
- **Cobertura dos testes:** o smoke test existente usa um CSV sintético
  com números no formato de ponto decimal. Ele passou, mas não detecta
  o defeito presente nos CSVs reais.
- **Limite de tempo:** o parâmetro de treino limita a chamada de ajuste;
  o fluxo ainda executa avaliação, leaderboard, persistência e diagnóstico
  de importância de variáveis. Portanto, não representa um teto garantido
  para todo o job. Isso foi identificado no código e não medido em um
  treino concluído nesta máquina.

## Evidências e reprodução

- `validacao/resultados.json`: dependências, fontes, páginas, servidor e jobs.
- `validacao/achados_detalhados.json`: conversões numéricas, causa raiz e histórico anterior.
- `validacao/execucao.log`, `validacao/achados.log` e `validacao/servidor.log`: logs.
- `validacao/treinos/dashboard_runs.sqlite3`: as três tentativas curtas.
- `validacao/auditar.py` e `validacao/verificar_achados.py`: scripts reproduzíveis.

No ambiente usado nesta auditoria, executar a partir da raiz do pacote:

```powershell
& 'C:/Users/User/AppData/Local/AcquaCropDashboard/venv/Scripts/python.exe' validacao/auditar.py
& 'C:/Users/User/AppData/Local/AcquaCropDashboard/venv/Scripts/python.exe' validacao/verificar_achados.py
```

O campo `status: ok` de uma verificação JSON indica que a verificação foi
executada até o fim. Para os treinos, o resultado real está no `status` de
cada job, que foi `failed` nos três casos. Para as páginas, consultar também
`exceptions`, `errors` e `warnings`.

## Próximas correções em ordem

1. Preparar um ambiente completo e executável para o dashboard e AutoML.
2. Corrigir os decimais e validar os schemas antes dos gráficos e treinos.
3. Melhorar as mensagens de dependências e preservar a causa raiz dos erros.
4. Ajustar a leitura para filtrar antes do limite e melhorar o mapa sem rede.
5. Repetir regressão, classificação e TimeSeries; exigir status `completed`,
   artefatos existentes, métricas finitas e previsão após recarregar o modelo.

Esta auditoria gerou evidências e scripts de teste; não implementou as
correções propostas no código de produção.
