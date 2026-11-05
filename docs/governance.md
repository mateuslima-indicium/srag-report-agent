# Governança e transparência

Tudo que o agente faz fica registrado, e o relatório carrega sua própria proveniência. Um
avaliador consegue responder, sem rodar nada: quais dados, qual modelo, quais ferramentas,
quais decisões e quais guardrails produziram cada frase.

## Trilha de auditoria (`audit/run-<timestamp>-<id>.jsonl`)

Um arquivo JSONL por execução, append-only, escrito por `srag_agent.audit.AuditLogger`. Cada
linha é um `AuditEvent` com `ts`, `run_id`, `seq`, `type`, `name` e `payload`.

| `type` | Quem emite | O que carrega |
|---|---|---|
| `run_start` | `agent/runner.py` | versão, Python, modelo, parâmetros (`reference_date`, `uf`, `include_news`), SHA-256 do Parquet, limites configurados |
| `tool_call` | tools e nó `collect_metrics` | nome, argumentos (datas em ISO), tamanho/linhas do resultado, duração; para SQL, o texto da consulta e o `purpose` declarado pelo modelo |
| `guardrail` | `sql_guard`, `tool_budget`, `token_budget`, validação de saída (um evento por check) e `max_write_attempts` | `passed`, motivo, detalhes (ex.: números sem origem, relações referenciadas) |
| `llm_call` | `agent/callbacks.py` (callback do LangChain) | modelo, hash SHA-256 do prompt, quantidade de mensagens, tokens de entrada/saída, latência, tool calls pedidas, `stop_reason` |
| `decision` | nós `analyze` e `write_report` | texto em que o modelo explica quais consultas fez e por quê, quais notícias considerou relevantes e quais descartou; notícias citadas e limitações do rascunho |
| `news_fetch` | nó `fetch_news` | consultas, itens aceitos (id, fonte, título), itens descartados com motivo, erros |
| `error` | qualquer nó | exceções de ferramenta, de parsing da saída estruturada ou da API |
| `run_end` | `agent/runner.py` | status (`ok` / `unverified` / `error`), caminho do relatório, totais de chamadas e tokens |

Exemplo real versionado: [`../audit/sample-run.jsonl`](../audit/sample-run.jsonl) (31 eventos,
inclusive uma reprovação do guardrail numérico seguida de regeneração).

Nada sensível entra na trilha: chaves ficam em `SecretStr` e nunca são serializadas; resultados
de SQL são agregados; o prompt é registrado apenas por hash.

## Registro das decisões do agente

O nó `analyze` exige que o modelo termine com um texto explicando (a) as decisões tomadas e
(b) os achados com números exatos. Esse texto vira o evento `decision/analyze` e alimenta a
redação. O nó `write_report` registra `decision/write_report` com as notícias citadas e a
justificativa de cada uma. O relatório final mostra, na tabela de notícias, quais foram citadas.

## Proveniência dentro do relatório

A seção **"Como este relatório foi produzido"** de cada Markdown lista: id da execução, versão
do software, caminho e hash do Parquet, data do último caso, modelo e tokens, número de tool
calls, consultas de notícias, caminho do JSONL, cada guardrail executado com resultado e os
checks da validação final. Se a validação não passou após as tentativas, um banner no topo
marca o texto como **não verificado** e a seção "Problemas apontados pelos guardrails" lista o
que não bateu. Os números da tabela e dos gráficos continuam válidos nesse caso, porque não
dependem do modelo.

## Reprodutibilidade

- Dados: Parquet versionado com hash registrado; `scripts/download_data.py` + `scripts/build_dataset.py` reconstroem do zero a partir das URLs do Open DATASUS; `docs/data-quality.md` documenta o build.
- Métricas: funções puras com SQL parametrizado, testadas contra um dataset sintético com valores calculados à mão (`tests/synthetic.py`).
- Modelo: nome vem de `ANTHROPIC_MODEL` e é gravado em `run_start`; sem parâmetros de amostragem. O texto gerado pode variar entre execuções, mas os números não, e o guardrail numérico impede divergência.
- Versões travadas em `uv.lock`; CI roda lint, formatação e testes a cada push.

## Papéis e responsabilidade

O agente é um assistente de análise para gestores e comunicadores. O system prompt proíbe
recomendação clínica individual e o guardrail `clinical_advice` bloqueia o que escapar. O
relatório declara em todas as métricas o que elas são e o que não são (ex.: UTI não é ocupação
de leitos, vacinação não é cobertura populacional).
