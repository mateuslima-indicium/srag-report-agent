# Guardrails

Cada guardrail é código pequeno, com teste próprio, e registra um evento `guardrail` na trilha
de auditoria com `passed` e o motivo. Nenhum depende de serviço externo.

| Guardrail | Risco mitigado | Onde | Como funciona | Teste |
|---|---|---|---|---|
| Validação de entrada | parâmetros inválidos propagarem para SQL/LLM | `metrics/base.py` (`resolve_reference_date`, `validate_uf`), `tools/metrics_tools.py` (schemas Pydantic com `Literal`) | UF só da lista de 27 siglas; janelas só em {7, 30, 60, 90}; data de referência não pode ser posterior ao último caso | `test_metrics.py`, `test_tools.py` |
| `sql_guard` | o modelo ler arquivos, mutar dados, exfiltrar configuração ou esgotar recursos | `guardrails/sql_guard.py`, `tools/sql_tool.py`, `data/db.py` | 6 camadas: parser do DuckDB exige 1 statement `SELECT`; blocklist (DDL/DML, `ATTACH`, `COPY`, `PRAGMA`, `INSTALL`, `LOAD`, `SET`, `read_csv*`, `read_parquet`, `glob`, `duckdb_*`, `information_schema`, …); whitelist de relações (`cases`, `daily_cases`, `monthly_cases`, `cases_by_uf`); `LIMIT` externo forçado; conexão `read_only=True` com `enable_external_access=false`; timeout de 15 s via `interrupt()` | `test_sql_guard.py` (14 aceitas, 26 rejeitadas), `test_tools.py` |
| `injection` | prompt injection vindo das notícias | `guardrails/injection.py`, `news/fetch.py`, `tools/news_tool.py` | 10 padrões pt/en (ignorar instruções, system prompt, troca de papel, executar comando, revelar segredo, marcadores `<system>`, dev mode, escape do delimitador) com normalização NFKC e remoção de caracteres invisíveis; item descartado com motivo registrado; o que passa vai ao LLM entre `<noticia id=...>` com aviso explícito de "dado não confiável"; o prompt proíbe seguir instruções das notícias | `test_news.py` (8 casos de injeção, 3 manchetes legítimas) |
| Sanitização | HTML, textos longos, custo | `news/sanitize.py` | strip de tags, decode de entidades, 600 caracteres por item, dedup por URL/título, no máximo `max_news_items` | `test_news.py` |
| `report_structure` | relatório incompleto ou fora do idioma | `guardrails/output_validation.py` | uma seção por métrica (nem mais nem menos), resumo mínimo, citações `[nN]` só para notícias existentes, heurística pt-BR, limitações presentes | `test_output_guardrails.py`, `test_graph.py` |
| `metric_caveats` | o modelo omitir a ressalva que muda a leitura do número | `guardrails/output_validation.py` | cada seção precisa mencionar a palavra-chave da sua ressalva (preliminar/atraso; desfecho; leito/ocupação/proporção; população/cobertura/proxy) | `test_output_guardrails.py` |
| `numeric_consistency` | números inventados ou calculados pelo modelo | `guardrails/numeric_consistency.py` | extrai percentuais e inteiros do texto (ignorando datas, anos, ids, faixas etárias e inteiros < 13) e exige que cada um exista em: métricas (valor, numerador, denominador, extras), definições/caveats, séries, títulos das notícias ou qualquer resultado de ferramenta da execução; tolerância 0,1 p.p. / 1 unidade; lista o que não bateu | `test_output_guardrails.py`, `test_graph.py` (regeneração e marcação "não verificado") |
| `clinical_advice` | recomendação clínica individual | `guardrails/output_validation.py` | 6 padrões ("tome X", "você deve", "procure um médico", "se você sentir", …) | `test_output_guardrails.py` |
| `pii` | dados pessoais no texto | `guardrails/pii.py` | CPF (com/sem máscara), e-mail, telefone BR, CNS, número de notificação | `test_output_guardrails.py` |
| Retry com feedback | saída reprovada virar relatório | `agent/graph.py` (`validate` → `write_report`) | os problemas voltam ao prompt de redação como "correções obrigatórias"; até `max_write_attempts` (3); depois o relatório sai com banner "não verificado" e a lista de problemas | `test_graph.py` |
| `tool_budget` | loop de ferramentas sem fim / custo | `agent/graph.py` (`run_tools`) | `max_tool_calls` (8) por execução; chamadas além do orçamento recebem uma `ToolMessage` de recusa e o modelo é instruído a redigir | `test_graph.py` |
| `token_budget` | custo descontrolado | `agent/graph.py` (`analyze`) | soma de tokens da trilha de auditoria; acima de `max_total_tokens` (200k) as tools são desligadas | `test_graph.py` (indireto) |
| Limites de grafo e API | travamentos | `agent/runner.py`, `agent/llm.py` | `recursion_limit=60`; `max_retries=3` com backoff exponencial do SDK (rate limit, conexão); timeout de 120 s por chamada | smoke test real (`tests/test_live.py`, marcado `live`) |
| Segredos | vazamento de chave | `config.py` | `SecretStr`; nunca serializado em logs, relatório ou `repr` | `test_config_and_llm.py` |

## O que acontece quando um guardrail falha

- **Entrada**: a CLI devolve erro claro e código 1, antes de abrir o banco ou chamar o modelo.
- **SQL**: a tool devolve `CONSULTA REJEITADA ... <motivo>` ao modelo (que pode reformular) e grava `guardrail/sql_guard passed=false`.
- **Notícia**: item descartado, contagem informada ao modelo, motivo na auditoria e no relatório.
- **Saída**: regeneração com feedback; esgotadas as tentativas, relatório marcado como não verificado. Os números da tabela e dos gráficos nunca dependem do modelo.

## Exemplo real

Na execução `a8d908d9` (ver `audit/sample-run.jsonl`), a primeira redação citou "600" ao
descrever a série diária (um valor lido a olho). `numeric_consistency` conferiu 149 números,
apontou esse único sem origem, e a segunda redação passou nos 9 checks.
