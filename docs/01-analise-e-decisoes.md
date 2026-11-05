# Análise do desafio e decisões de projeto

> Produzido em 2026-11-05 a partir do enunciado (`docs/ENUNCIADO-DESAFIO.md`), do perfil
> completo dos CSVs em `data/raw/` e de uma sessão de decisões com o autor do projeto.
> Este documento foi a fonte de verdade durante o desenvolvimento.

## 1. O que o desafio pede, lido com cuidado

| Exigência do enunciado | Implicação concreta |
|---|---|
| Agente GenAI que consulta **banco de dados** e traz as métricas | O LLM não calcula; ele chama *tools* que executam SQL determinístico sobre um banco. |
| Agente consulta **notícias em tempo real** sobre SRAG para embasar as métricas | Tool de notícias ao vivo, com conteúdo tratado como dado não confiável. |
| 4 métricas: aumento de casos, mortalidade, ocupação de UTI, vacinação | Duas delas (UTI e vacinação) não existem diretamente no SRAG; precisam de proxy declarado. |
| 2 gráficos: casos diários (30 dias) e mensais (12 meses) | Gerados por código (matplotlib), nunca pelo LLM. |
| Avaliação: arquitetura, governança/transparência, guardrails, dados sensíveis, clean code | Cada critério vira um módulo com testes e uma seção do README. |
| Entrega: repo público no GitHub + README + PDF com diagrama (orquestrador, tools, LLM, banco, notícias) | Diagrama em Mermaid no README e PDF versionado em `docs/`. |

O enunciado descreve o CSV como "~100 colunas e 165 mil linhas" do dataset 2021 a 2024. O
dataset migrou de portal e hoje tem 194 colunas, um arquivo por ano. Isso é oportunidade de
mostrar robustez: o pipeline aceita qualquer ano e o README explica a migração.

## 2. Perfil dos dados (fatos medidos, não suposições)

Fonte: `INFLUD25-02-11-2026.csv` (336.432 linhas) e `INFLUD26-02-11-2026.csv` (240.606 linhas),
extração de 02/11/2026, 194 colunas idênticas, separador `;`, latin-1.

### 2.1 Formato de datas
- Todas as colunas `DT_*` vêm como ISO `yyyy-mm-ddT00:00:00.000Z`, apesar de o dicionário dizer DD/MM/AAAA.
- Exceção: `DOSE_1_COV`, `DOSE_2_COV`, `DOSE_REF`, `DOSE_2REF`, `DOSE_ADIC` vêm em `dd/mm/yyyy`.
- Há anos absurdos (8202, 2502, 2055, 2029) em `DT_INTERNA` e `DT_ENTUTI`, menos de 10 por coluna. Filtrar faixa plausível (2024-12-01 até data de extração).

### 2.2 Partição e sobreposição
- Arquivos particionados por **ano epidemiológico de `DT_SIN_PRI`** (SE01/2025 começa 29/12/2024; SE01/2026 começa 04/01/2026). Sem sobreposição. Concatenar é seguro.
- `INFLUD25` contém `DT_NOTIFIC` até 31/10/2026 (notificações tardias de casos de 2025).
- `NU_NOTIFIC` serve para checagem de duplicidade.

### 2.3 Preenchimento das colunas-chave (2026 | 2025)
| Coluna | Fill | Códigos (dicionário) |
|---|---|---|
| `DT_SIN_PRI`, `DT_NOTIFIC`, `SEM_PRI` | 100% | data dos primeiros sintomas é a referência temporal do caso |
| `HOSPITAL` | 97,8% / 98,0% | 1=Sim, 2=Não, 9=Ignorado (97% são 1: a base é de internados) |
| `EVOLUCAO` | 88,4% / 95,5% | 1=Cura, 2=Óbito, 3=Óbito por outras causas, 9=Ignorado |
| `DT_EVOLUCA` | 79,3% / 86,4% | data de alta ou óbito |
| `UTI` | 89,9% / 90,5% | 1=Sim, 2=Não, 9=Ignorado |
| `DT_ENTUTI` / `DT_SAIDUTI` | 24% / 14% | só quando UTI=1 |
| `SUPORT_VEN` | 89,7% | 1=invasivo, 2=não invasivo, 3=Não, 9=Ignorado |
| `VACINA` (gripe) | 95,7% / 93,8% | 1=Sim, 2=Não, 9=Ignorado |
| `VACINA_COV` | 100% | 1=Sim, 2=Não, 9=Ignorado |
| `CLASSI_FIN` | 92,6% / 97,4% | 1=influenza, 2=outro vírus, 3=outro agente, 4=não especificado, 5=covid-19 |
| `SG_UF_NOT`, `SG_UF`, `CS_SEXO`, `NU_IDADE_N` | 100% | idade usa `TP_IDADE` (1=dia, 2=mês, 3=ano) |

Taxas brutas observadas: óbito (EVOLUCAO=2 sobre 1+2+3) 5,4% em 2026 e 7,3% em 2025; UTI (1 sobre 1+2) 27,9% e 29,3%.

### 2.4 Sazonalidade e atraso de notificação
Casos por mês de `DT_SIN_PRI` (dois arquivos somados):

```
2025-09 24.347 | 2025-10 24.034 | 2025-11 21.019 | 2025-12 16.355
2026-01 12.788 | 2026-02 15.858 | 2026-03 27.081 | 2026-04 31.544
2026-05 39.493 | 2026-06 37.935 | 2026-07 28.041 | 2026-08 20.604
2026-09 16.931 | 2026-10 11.977 | 2026-11 2
```
Semanas ISO 2026: W37 3.899 | W38 3.971 | W39 3.875 | W40 3.754 | W41 3.360 | W42 3.251 | W43 2.582 | W44 633 (parcial).

Conclusões obrigatórias para o relatório:
- Pico sazonal em maio/junho nos dois anos.
- As 2 a 3 últimas semanas antes da extração estão **subnotificadas**. Qualquer "queda" ali é artefato. O gráfico diário deve sombrear os últimos 14 dias como preliminares e o texto deve dizer isso.
- 21% dos casos de 2026 ainda sem desfecho: a mortalidade recente é subestimada. Calcular sobre casos com desfecho conhecido e declarar o denominador.

### 2.5 Colunas a descartar por privacidade (nunca chegam ao Parquet tratado nem ao LLM)
- Quase-identificadores: `DT_NASC`, `TEM_CPF`, `ESTRANG`, `CS_ETINIA`, `CS_RACA`, `PAC_COCBO`, `PAC_DSCBO`, `CS_GESTANT`, `OBES_IMC`.
- Texto livre (pode conter nomes): `MORB_DESC`, `OUTRO_DES`, `OUT_ANTIV`, `OUT_TRAT`, `OUT_AMOST`, `OUT_SOR`, `CLASSI_OUT`, `RAIOX_OUT`, `TOMO_OUT`, `DS_PCR_OUT`, `DS_AN_OUT`, `VG_OMSOUT`, `VG_METOUT`.
- Localização fina: `ID_MUNICIP`, `CO_MUN_NOT`, `ID_MN_RESI`, `CO_MUN_RES`, `ID_REGIONA`, `CO_REGIONA`, `ID_RG_RESI`, `CO_RG_RESI`, `CS_ZONA`, `ID_MN_INTE`, `CO_MU_INTE`, `ID_RG_INTE`, `CO_RG_INTE`, `NM_UN_INTE`, `SG_UF_INTE`, `LO_PS_VGM`, `CO_PS_VGM`, `PAIS_VGM`.
- Lotes de vacina: `LOTE_1_COV`, `LOTE_2_COV`, `LOTE_REF`, `LOTE_REF2`, `LOTE_ADIC`, `LOT_RE_BI`, `VG_CODEST`.
- `NU_NOTIFIC` vira hash SHA-256 truncado (só para dedup), nunca o número original.
- Idade é convertida para anos e **agrupada em faixas de 10 anos**. Localização fica só na UF.

Não há nome, CPF, telefone ou endereço no CSV público. Mesmo assim o LLM só recebe agregados.

### 2.6 Colunas mantidas no Parquet tratado
`DT_SIN_PRI`, `DT_NOTIFIC`, `SEM_PRI`, `DT_INTERNA`, `DT_EVOLUCA`, `DT_ENTUTI`, `DT_SAIDUTI`,
`SG_UF_NOT`, `SG_UF`, `CS_SEXO`, idade em anos e faixa etária, `HOSPITAL`, `UTI`, `SUPORT_VEN`,
`EVOLUCAO`, `CLASSI_FIN`, `VACINA`, `DT_UT_DOSE`, `VACINA_COV`, `DOSE_1_COV`, `DOSE_2_COV`,
`DOSE_REF`, `DOSE_2REF`, `DOSE_ADIC`, `FATOR_RISC`, `notif_hash`, `source_file`.

## 3. Definição das métricas (determinísticas, testáveis)

Todas usam `DT_SIN_PRI` como data do caso e uma `reference_date` parametrizável, cujo default é a
data máxima de `DT_SIN_PRI` no banco (não "hoje", para não ler subnotificação como queda).

| Métrica | Definição | Caveat obrigatório no relatório |
|---|---|---|
| Taxa de aumento de casos | `(casos nos últimos N dias / casos nos N dias anteriores) - 1`, para N=7 e N=30 | Últimos 14 dias são preliminares por atraso de notificação |
| Taxa de mortalidade | `EVOLUCAO=2 / (EVOLUCAO in 1,2,3)` nos casos com `DT_SIN_PRI` na janela (default 30 dias) | Exclui casos sem desfecho; informar % sem desfecho |
| Taxa de ocupação de UTI (proxy) | `UTI=1 / (UTI in 1,2)` entre hospitalizados (`HOSPITAL=1`) na janela | Não é ocupação de leitos (não há capacidade no dataset); é proporção de internados que foram para UTI |
| Taxa de vacinação (proxy) | `VACINA_COV=1 / (VACINA_COV in 1,2)` e `VACINA=1 / (VACINA in 1,2)` na janela | É cobertura entre pacientes SRAG, não da população geral; viés declarado; cobertura populacional fica como trabalho futuro |
| Série diária | casos por dia nos últimos 30 dias até `reference_date` | sombreado preliminar |
| Série mensal | casos por mês nos últimos 12 meses completos | idem para o mês corrente |

Toda métrica retorna numerador, denominador, janela e data de referência, para que o guardrail
de consistência numérica confira o texto do LLM contra os valores das tools.

## 4. Decisões de arquitetura (fechadas com o autor)

| Tema | Decisão | Motivo |
|---|---|---|
| LLM | Anthropic via `langchain-anthropic`, `ANTHROPIC_API_KEY` em `.env`, modelo em `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`) | Caminho oficial; o avaliador usa a própria chave |
| Orquestração | LangGraph, um grafo com nós: coletar métricas (tools) -> buscar notícias (tool) -> redigir (LLM com saída estruturada) -> validar (guardrails) -> renderizar | Stack citado no enunciado; cada nó é auditável |
| Acesso a dados | Tools fixas para as 4 métricas e séries + `run_readonly_sql` restrita (só SELECT, tabelas/views whitelist, LIMIT forçado, timeout, conexão read-only) | Métricas determinísticas e testáveis; SQL livre mostra guardrail em ação |
| Banco | DuckDB em arquivo local, construído a partir de Parquet tratado | Zero infra; o avaliador roda em um comando |
| Dados no repo | Parquet tratado e reduzido versionado em `data/processed/`; CSVs brutos ignorados; script de download e build para reproduzir do zero | 650 MB não cabem no GitHub |
| Notícias | RSS do Google News (`news.google.com/rss/search?q=...&hl=pt-BR&gl=BR&ceid=BR:pt-150`) sem chave; Tavily opcional se `TAVILY_API_KEY` existir | Mínimo de chaves |
| Saída | Markdown + 2 PNG em `reports/`, via CLI (`srag-agent report`) | Sem UI; não pontua |
| Auditoria | JSONL por execução em `audit/` com todos os passos (chamadas LLM, tools, guardrails, decisões), mais seção "Fontes e auditoria" no relatório | É o que o avaliador abre |
| Guardrails | Hand-rolled com Pydantic; cada um com teste | Explicável no README |
| Idioma | Código e identificadores em inglês; docs, prompts e relatório em português | Avaliadores brasileiros, dados em português |
| Diagrama | Mermaid no README + PDF em `docs/architecture.pdf` gerado por script | Exigência da entrega |
| Repositório | `srag-report-agent` na conta GitHub `mateuslima-indicium`, privado durante o desenvolvimento, público na entrega (prazo 30/11/2026) | Decisão do autor |
| Execução | Construção autônoma, commit por fase, sem perguntas ao autor salvo bloqueio real | Pedido do autor |

## 5. Guardrails planejados

1. **Entrada**: validação de argumentos da CLI (datas, UF, janelas); escopo restrito a SRAG.
2. **SQL**: parser que aceita apenas um `SELECT`; bloqueia `ATTACH`, `COPY`, `PRAGMA`, `INSTALL`, `LOAD`, DDL/DML, subconsultas para tabelas fora da whitelist; só consultas agregadas sobre a tabela de casos; força `LIMIT <= 200`; timeout; conexão `read_only=True`.
3. **Notícias (prompt injection)**: strip de HTML, limite de tamanho, lista de padrões de injeção (ex.: "ignore as instruções", "system prompt") que descarta o item e registra no audit; conteúdo entregue ao LLM entre delimitadores com instrução explícita de tratar como dado.
4. **Saída**: saída estruturada (Pydantic) com campos fixos; verificação de que todo número/percentual citado no texto bate com os valores retornados pelas tools (tolerância de arredondamento), senão o nó pede regeneração (até 3 tentativas no total) e, falhando, marca o relatório como "não verificado"; bloqueio de PII (regex CPF, e-mail, telefone); bloqueio de recomendação médica individual; idioma pt-BR.
5. **Orçamento**: limite de iterações do agente, de chamadas de tool e de tokens por execução; retries com backoff na API.

## 6. Transparência e auditoria

- `audit/run-<timestamp>-<id>.jsonl`: eventos `run_start` (parâmetros, versões, hash do Parquet), `llm_call` (modelo, hash do prompt, tokens, latência), `tool_call` (nome, argumentos, resultado, duração), `guardrail` (nome, resultado, detalhes), `decision` (justificativa do agente: quais notícias usou e por quê, quais descartou; rascunhos), `run_end` (status, tokens, chamadas).
- O relatório termina com a seção "Como este relatório foi produzido": id da execução, hash do Parquet, modelo e tokens, ferramentas, notícias e guardrails; a tabela de notícias traz URL, data e quais foram citadas.
- `docs/data-quality.md` gerado pelo build do dataset: linhas lidas, descartadas, nulos por coluna, datas inválidas.

## 7. Riscos conhecidos

- API da Anthropic muda rápido: há um smoke test real (`uv run pytest -m live`) e o cliente não passa `temperature`/`top_p`.
- Google News RSS pode mudar formato ou bloquear: o parser tem fixture de teste e o agente degrada para "sem notícias disponíveis" sem quebrar o relatório.
- DuckDB pode não ler latin-1 diretamente dependendo da versão: fallback em pandas com `encoding="latin-1"` em chunks.
