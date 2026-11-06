# Guardrails

Cada guardrail é código pequeno, com teste próprio, e registra um evento `guardrail` na trilha
de auditoria com `passed` e o motivo. Nenhum depende de serviço externo.

| Guardrail | Risco mitigado | Onde | Como funciona | Teste |
|---|---|---|---|---|
| Validação de entrada | parâmetros inválidos propagarem para SQL/LLM | `cli.py` (`_parse_inputs`), `metrics/base.py` (`resolve_reference_date`, `validate_uf`), `tools/metrics_tools.py` (schemas Pydantic com `Literal`) | data em `YYYY-MM-DD`; UF só da lista de 27 siglas; janelas só em {7, 30, 60, 90}; data de referência não pode ser posterior ao último caso. A CLI rejeita antes de abrir o banco (sem evento de auditoria) | `test_cli.py`, `test_metrics.py`, `test_tools.py` |
| `sql_guard` | o modelo ler arquivos, mutar dados, exfiltrar configuração, ver registros individuais ou esgotar recursos | `guardrails/sql_guard.py`, `tools/sql_tool.py`, `data/db.py` | 7 camadas: parser do DuckDB exige 1 statement `SELECT`; blocklist (DDL/DML, `ATTACH`, `COPY`, `PRAGMA`, `INSTALL`, `LOAD`, `SET`, `read_csv*`, `read_parquet`, `glob`, `duckdb_*`, `information_schema`, …); whitelist de relações (`cases`, `daily_cases`, `monthly_cases`, `cases_by_uf`) conferida sobre o AST serializado pelo próprio DuckDB (`json_serialize_sql`), o que alcança subconsultas, CTEs, junções por vírgula e recusa qualquer função de tabela; **só agregados sobre `cases`** (o nó que produz o resultado precisa de `GROUP BY`, `DISTINCT` ou de expressões formadas só por funções de agregação; `SELECT *`, colunas soltas e funções de janela são recusados, inclusive dentro de CTEs, subconsultas e `UNION`); `LIMIT` externo forçado; conexão `read_only=True` com `enable_external_access=false`; timeout de 15 s via `interrupt()` | `test_sql_guard.py` (15 aceitas, 32 rejeitadas, 12 agregadas aceitas, 10 linha a linha recusadas), `test_tools.py` |
| `injection` | prompt injection vindo das notícias | `guardrails/injection.py`, `news/fetch.py`, `tools/news_tool.py` | 10 padrões pt/en (ignorar instruções, system prompt, troca de papel, executar comando, revelar segredo, marcadores `<system>`, dev mode, escape do delimitador) com normalização NFKC e remoção de caracteres invisíveis, aplicados a fonte, título e resumo; item descartado com motivo registrado; o que passa vai ao LLM entre `<noticia id=...>` com aviso explícito de "dado não confiável" (a fonte é escapada no atributo); o prompt proíbe seguir instruções das notícias; títulos e fontes são escapados na tabela Markdown do relatório | `test_news.py` (8 casos de injeção, 3 manchetes legítimas, fonte envenenada, escape do atributo) |
| Sanitização | HTML, textos longos, custo | `news/sanitize.py` | strip de tags, decode de entidades, 600 caracteres por item, dedup por URL/título, no máximo `max_news_items` | `test_news.py` |
| `report_structure` | relatório incompleto ou fora do idioma | `guardrails/output_validation.py` | uma seção por métrica (faltante, desconhecida ou duplicada reprova), resumo mínimo, citações `[nN]` em qualquer campo só para notícias existentes, heurística pt-BR aplicada campo a campo (um resumo em inglês não se esconde atrás das seções em português), limitações presentes | `test_output_guardrails.py`, `test_graph.py` |
| `metric_caveats` | o modelo omitir a ressalva que muda a leitura do número | `guardrails/output_validation.py` | cada seção precisa mencionar a palavra-chave da sua ressalva (preliminar/atraso; desfecho; leito/ocupação/proporção; população/cobertura/proxy) | `test_output_guardrails.py` |
| `numeric_consistency` | números inventados ou calculados pelo modelo | `guardrails/numeric_consistency.py` | extrai percentuais, decimais ("4,1") e inteiros do texto (ignorando datas, horas, ids `[nN]`, faixas etárias, semanas epidemiológicas e inteiros < 13) e exige que cada um exista em: métricas (valor, numerador, denominador, extras), definições/caveats, séries, títulos das notícias, tamanhos de janela das tools (7, 30, 60, 90), anos plausíveis (2019 até o ano seguinte à referência) ou qualquer resultado de ferramenta da execução; tolerância 0,1 p.p. / 1 unidade; percentuais comparados em módulo ("queda de 3,2%" vale para -3,2%); lista o que não bateu. Contagens que parecem anos (ex.: 2582 casos) são conferidas como qualquer outro número | `test_output_guardrails.py`, `test_graph.py` (regeneração e marcação "não verificado") |
| `clinical_advice` | recomendação clínica individual | `guardrails/output_validation.py` | 6 padrões ("tome X", "você deve", "procure um médico", "se você sentir", …) | `test_output_guardrails.py` |
| `pii` | dados pessoais no texto | `guardrails/pii.py` | CPF (com/sem máscara), e-mail, telefone BR, CNS, número de notificação | `test_output_guardrails.py` |
| Retry com feedback | saída reprovada virar relatório | `agent/graph.py` (`validate` → `write_report`) | os problemas voltam ao prompt de redação como "correções obrigatórias"; até `max_write_attempts` (3); depois o relatório sai com banner "não verificado" e a lista de problemas | `test_graph.py` |
| `tool_budget` | loop de ferramentas sem fim / custo | `agent/graph.py` (`run_tools`, `analyze`), `agent/llm.py` | `max_tool_calls` (8) por execução; chamadas além do orçamento recebem uma `ToolMessage` de recusa e, na rodada seguinte, as ferramentas continuam declaradas mas com `tool_choice: none` (a API exige as definições quando o histórico já tem chamadas), então o modelo só pode redigir | `test_graph.py`, execução real com `MAX_TOOL_CALLS=1` |
| `token_budget` | custo descontrolado | `agent/graph.py` (`analyze`) | soma de tokens da trilha de auditoria; acima de `max_total_tokens` (200k) as tools são desligadas | `test_graph.py` (indireto) |
| Limites de grafo e API | travamentos | `agent/runner.py`, `agent/llm.py` | `recursion_limit=60`; `max_retries=3` com backoff exponencial do SDK (rate limit, conexão); timeout de 120 s por chamada | smoke test real (`tests/test_live.py`, marcado `live`) |
| Segredos | vazamento de chave | `config.py` | `SecretStr`; nunca serializado em logs, relatório ou `repr` | `test_config_and_llm.py` |

## O que acontece quando um guardrail falha

- **Entrada**: a CLI devolve uma linha de erro clara e código 1, antes de abrir o banco ou chamar o modelo (nunca um traceback).
- **SQL**: a tool devolve `CONSULTA REJEITADA ... <motivo>` ao modelo (que pode reformular) e grava `guardrail/sql_guard passed=false`.
- **Notícia**: item descartado, contagem informada ao modelo, motivo na auditoria e no relatório.
- **Saída**: regeneração com feedback; esgotadas as tentativas, relatório marcado como não verificado. Os números da tabela e dos gráficos nunca dependem do modelo.

## O que os guardrails de saída não garantem

Vale dizer o que fica fora, para que ninguém leia mais do que existe:

- `numeric_consistency` confere que cada número **existe** em alguma fonte da execução, não que foi atribuído à métrica certa. "Mortalidade de 28,8%" passaria se 28,8% fosse a taxa de UTI. O prompt, a saída estruturada (uma seção por métrica, com o JSON da métrica ao lado) e a tabela determinística acima do texto reduzem esse risco; não o eliminam.
- `metric_caveats` é uma busca por palavras-chave; garante que a ressalva foi mencionada, não que foi bem interpretada.
- Números escritos por extenso ("três mil") e inteiros abaixo de 13 não são conferidos.

## Exemplos reais

- Na execução versionada (`audit/exemplo/run-20261106T000314Z-8e0cceae.jsonl`) a primeira redação passou nos 9 checks; `sql_guard` aprovou a consulta agregada por classificação final.
- Em execuções de validação anteriores, `numeric_consistency` reprovou primeiras redações que citavam um valor lido a olho na série diária ("600") e números fora das ferramentas ("1100", "1600"); a segunda redação, com o feedback, passou. O mesmo caminho é coberto por `test_graph.py` (regeneração e banner "não verificado").
