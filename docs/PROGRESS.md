# Progresso do workflow

Registro por fase do `WORKFLOW.md`. Releia este arquivo ao iniciar qualquer fase.

## Fase 0: bootstrap e smoke test — CONCLUÍDA (2026-11-05)

**Feito**
- `git init`, identidade local do git configurada (nome do autor e e-mail corporativo).
- `pyproject.toml` com hatchling (src layout), script `srag-agent`, ruff (line-length 100, `E,F,I,UP,B,SIM`) e pytest (`testpaths=tests`, marker `live`).
- Dependências via `uv add` (versões travadas em `uv.lock`): langchain 1.4.9, langgraph 1.2.20, langchain-anthropic 1.7.10, anthropic 2.6.0, duckdb 2.0.0, pandas 3.1.1, pyarrow 26, pydantic 2.14, pydantic-settings 2.16, feedparser 6.0.14, httpx 0.28, matplotlib 3.11, typer 0.27. Dev: pytest 9.2, pytest-cov, ruff 0.17, respx 0.23.
- `src/srag_agent/config.py`: `Settings(BaseSettings)` lendo `.env` com `SecretStr` para chaves, caminhos derivados (`parquet_path`, `db_path`), limites (`max_tool_calls=8`, `max_news_items=8`, `sql_row_limit=200`, `max_output_tokens=8000`, `max_write_attempts=3`).
- `src/srag_agent/agent/llm.py`: `build_chat_model()` devolve `ChatAnthropic(model, api_key, max_tokens, timeout, max_retries=3)` quando há chave, senão `GenericFakeChatModel`. Nenhum parâmetro de amostragem é passado.
- `src/srag_agent/cli.py`: comando `version` (mostra config não sensível).
- Testes: `tests/test_config_and_llm.py` (5 testes) + `tests/conftest.py` com fixture `settings` isolada do `.env`.

**Smoke test real** (script temporário fora do repo): `invoke("Responda só: ok")` em `claude-sonnet-5-5` respondeu `ok`, 15 tokens de entrada / 4 de saída, 2,3 s. A API aceita o modelo sem ajustes.

**Decisões**
- Build backend hatchling (uv default para src layout); README placeholder criado porque o build exige o arquivo.
- `GenericFakeChatModel` escolhido como fake (aceita iterador de `AIMessage`, o que permite simular tool calls na fase 5).
- Timeout do LLM 120 s e 3 retries no cliente da Anthropic (cobre `RateLimitError`/`APIConnectionError` com backoff do SDK).

**Validar**
```
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run srag-agent version
```

## Fase 1: pipeline de dados — CONCLUÍDA (2026-11-05)

**Feito**
- `src/srag_agent/data/schema.py`: contrato de colunas (lidas, mantidas, descartadas por privacidade), dicionários de códigos em português, UFs, faixas etárias, janelas plausíveis de datas.
- `src/srag_agent/data/cleaning.py`: funções puras vetorizadas (`parse_mixed_date` ISO + dd/mm/yyyy, `nullify_outside`, `to_code`, `age_in_years`, `age_band`, `hash_identifier`, `clean_cases`, `drop_duplicate_notifications`) com `CleaningStats`.
- `src/srag_agent/data/pipeline.py`: `read_raw_csv` (DuckDB `read_csv`, só as colunas do contrato, `all_varchar`), `build_processed_frame`, `write_parquet` (zstd), `build_dataset`, `render_quality_report` (pt-BR). Data de extração derivada do nome do arquivo (`*-dd-mm-yyyy.csv`).
- `src/srag_agent/data/db.py`: `build_database` (tabela `cases` com datas em DATE + views `daily_cases`, `monthly_cases`, `cases_by_uf`), `ensure_database` (reconstrói o `.duckdb` a partir do Parquet quando ausente ou desatualizado, para o clone limpo funcionar), `open_readonly`, `fetch_all`/`fetch_one` parametrizados, `file_sha256`.
- `scripts/download_data.py` (streaming httpx, pula existentes, confere content-length) e `scripts/build_dataset.py`.
- Testes: `tests/test_cleaning.py` (7) e `tests/test_pipeline.py` (8) sobre `tests/fixtures/srag_sample_02-11-2026.csv` (dois formatos de data, ano 8202, ano 2029, código inválido, duplicata, notificação sem número, idade 150). Teste afirma que o Parquet tem exatamente `PROCESSED_COLUMNS` e nenhuma coluna da lista de privacidade.

**Build real**: 577.038 linhas (336.432 + 240.606, 0 duplicatas), Parquet 12,1 MB em `data/processed/srag.parquet` (versionado), `data/srag.duckdb` (ignorado). Contagens mensais idênticas ao perfil da seção 2.4 do doc de decisões. `docs/data-quality.md` gerado.

**Decisões e correções**
- Os CSVs de 2026 são **UTF-8**, não latin-1 como dizia o doc de decisões (medido: 0 erros de decode UTF-8 nos dois arquivos; DuckDB rejeita `encoding='latin-1'`). O leitor tenta UTF-8 e depois latin-1; `data/raw/README.md` corrigido.
- Colunas do Parquet mantêm os nomes do dicionário DATASUS em minúsculas (rastreabilidade) + derivadas `age_years`, `age_band`, `notif_hash`, `source_file`.
- `NU_IDADE_N` entra na lista de descarte (só a idade em anos arredondada e a faixa ficam).
- Janela de datas de vacinação começa em 2020-12-01 (a de episódio em 2024-12-01).
- Datas são gravadas como timestamp no Parquet e convertidas para `DATE` ao carregar no DuckDB.

**Validar**
```
uv run pytest
uv run python scripts/build_dataset.py
```

## Fase 2: métricas e gráficos — CONCLUÍDA (2026-11-05)

**Feito**
- `metrics/models.py`: `MetricResult` (value, unit, numerator, denominator, janela, reference_date, uf, definition, caveats, extra), `SeriesPoint`/`SeriesResult` (flag `preliminary` + `preliminary_cutoff`), `MetricsBundle`.
- `metrics/base.py`: `Window`, `resolve_reference_date` (default = max `dt_sin_pri`; rejeita datas futuras), `validate_uf`, `count_cases` parametrizado, `PRELIMINARY_DAYS = 14`.
- `metrics/cases.py` (crescimento 7 e 30 dias), `mortality.py`, `icu.py`, `vaccination.py` (covid e gripe), `series.py` (diária 30 dias zero-filled, mensal 12 meses completos), `collect.py` (`collect_metrics`).
- `report/charts.py`: dois PNG 1600x900 @150 dpi, uma cor para a série, cinza para preliminar, faixa sombreada no diário, rótulos pt-BR com separador de milhar, fonte no rodapé.
- CLI: `srag-agent metrics [--reference-date] [--uf]` e `srag-agent charts [--output]`.
- Testes: `tests/synthetic.py` (dataset construído à mão: crescimento 97/60 e 28/21, mortalidade 10/85, UTI 20/90, vacinação 30/90 e 40/90), `tests/test_metrics.py` (8), `tests/test_charts.py` (1).

**Valores reais (referência 2026-11-01, Brasil)**: crescimento 7d -75,5% (633/2582) e 30d -35,5% (10.788/16.734), ambos dominados pela subnotificação; mortalidade 4,1% (191/4.636); UTI 28,8% (2.625/9.114); vacinação covid 39,1%, gripe 39,6%.

**Decisões**
- Além do valor na janela pedida, `case_growth` traz em `extra`/caveat o crescimento "consolidado" (mesma janela terminando no corte preliminar, `latest - 14 dias`) para o LLM contextualizar a queda artificial sem reabrir a decisão do default de `reference_date`.
- A flag `preliminary` é relativa à data máxima dos dados, não à `reference_date` pedida: um relatório retroativo não marca nada como preliminar.
- Vacinação vira duas métricas (`vaccination_covid`, `vaccination_flu`), as duas proxies declaradas.

**Validar**
```
uv run pytest
uv run srag-agent metrics
uv run srag-agent charts
```

## Fase 3: tools, notícias e guardrail de SQL — CONCLUÍDA (2026-11-05)

**Feito**
- `audit/events.py` (`AuditEvent`: ts, run_id, seq, type, name, payload) e `audit/logger.py` (`AuditLogger` JSONL append-only em `audit/run-<ts>-<id>.jsonl`, com `count`/`of_type` para os guardrails e o relatório). Antecipado da fase 4 porque as tools já registram eventos.
- `guardrails/sql_guard.py`: `guard_sql` em 5 camadas: parser do DuckDB (`extract_statements`, exatamente 1 statement do tipo SELECT), blocklist regex (DDL/DML, ATTACH/COPY/PRAGMA/INSTALL/LOAD/SET/CALL, `read_csv*`, `read_parquet`, `glob`, `duckdb_*`, `information_schema`, `current_setting`...), whitelist de relações (`cases`, `daily_cases`, `monthly_cases`, `cases_by_uf`, ignorando nomes de CTE), wrapper `SELECT * FROM (...) LIMIT n`. Comentários são removidos antes da análise.
- `data/db.open_readonly` agora abre com `enable_external_access=false` (DuckDB bloqueia qualquer acesso a arquivo no nível do motor; verificado com `read_csv` em `win.ini`).
- `tools/sql_tool.py`: `run_readonly_sql(sql, purpose)` com timeout por `con.interrupt()` (15 s), serialização JSON limitada a 6 kB, rejeições e execuções viram eventos `guardrail`/`tool_call`.
- `guardrails/injection.py`: 10 padrões pt/en (ignorar instruções, system prompt, troca de papel, executar comando, revelar segredos, marcadores `<system>`, dev mode, escape do delimitador `<noticia>`), com normalização NFKC e remoção de zero-width para evitar evasão.
- `news/`: `models.py` (`NewsItem`, `DiscardedItem`, `NewsBatch`), `sanitize.py` (strip HTML, 600 chars, remove sufixo " - Fonte"), `google_news_rss.py` (3 queries, httpx + feedparser, user-agent próprio), `tavily.py` (só com chave), `fetch.py` (dedup por URL/título, screening de injeção com motivo registrado, ordenação por data, ids `n1..nN`).
- `tools/metrics_tools.py` (6 tools: crescimento, mortalidade, UTI, vacinação, série diária, série mensal; argumentos validados por Pydantic com `Literal` de UFs e janelas), `tools/news_tool.py` (`get_recent_news` + `format_news_for_llm` com delimitadores `<noticia id=...>` e aviso de "dados não confiáveis"), `tools/__init__.build_tools`.
- Testes: `test_sql_guard.py` (14 aceitas + 26 rejeitadas + CTE), `test_news.py` (fixture real `tests/fixtures/google_news_srag.xml` com 50 itens, respx para 200 e 503, 8 casos de injeção incl. full-width e zero-width, 3 manchetes legítimas), `test_tools.py` (6). Total: 98 testes.

**Smoke test real**: Google News RSS devolveu 8 itens (G1, CNN Brasil, UOL...) sem descartes nem erros.

**Decisões**
- O resumo do Google News é só o título com link; `summary` fica vazio nesse caso (sem texto inventado).
- Comentário SQL contendo palavras bloqueadas é aceito porque o comentário é removido antes (inerte).
- A tool de notícias não busca por conta própria: o grafo busca uma vez por execução e a tool só reexpõe o lote (evita múltiplas chamadas de rede e garante o mesmo conjunto auditado).

**Validar**
```
uv run pytest tests/test_sql_guard.py tests/test_news.py tests/test_tools.py
```

## Fase 4: agente LangGraph — CONCLUÍDA (2026-11-05)

**Feito**
- `agent/state.py` (`AgentState` TypedDict), `agent/prompts.py` (system prompt pt-BR com as 6 regras; instruções de análise e de redação; feedback de correção), `agent/callbacks.py` (`AuditCallbackHandler`: hash do prompt, tokens, latência, tool calls pedidas, stop_reason), `agent/llm.py` (`with_tools`, `invoke_structured`), `agent/graph.py`, `agent/runner.py` (`run_report` → `RunResult`).
- Grafo: `collect_metrics` → `fetch_news` → `analyze` ⇄ `run_tools` (loop com orçamento `max_tool_calls`) → `write_report` (saída estruturada `ReportContent`) → `validate` → (`write_report` até `max_write_attempts`, senão) `render`. Os dois nós determinísticos nunca chamam o LLM.
- `report/models.py` (`ReportContent`: resumo, uma seção por métrica, aprofundamento, contexto de notícias com citações `[nN]`, limitações) e `report/render.py` (Markdown completo já com a seção "Como este relatório foi produzido": run id, hash do Parquet, modelo, tokens, tool calls, guardrails e resultado da validação; banner "não verificado" quando a validação falha).
- `guardrails/output_validation.py`: `check_structure` (todas as métricas comentadas, resumo mínimo, citações válidas, idioma pt-BR, limitações presentes) e `validate_report` (ponto único que a fase 5 estende).
- CLI `srag-agent report [--reference-date] [--uf] [--no-news] [--output]`.
- Testes `tests/test_graph.py` (4): execução completa com fake model (tool calls scriptadas + RSS mockado), rascunho inválido → 3 tentativas → relatório marcado como não verificado, orçamento de tools, recorte por UF. Total: 102 testes.

**Execuções reais** (claude-sonnet-5-5): 1ª: 5 tool calls (crescimento por UF para SE e MS, SQL por classificação, faixa etária e panorama por UF), 2 tentativas de redação, aprovada, 31,6k tokens de entrada / 10,4k de saída. A primeira tentativa falhou porque `with_structured_output` padrão usa tool call forçado, não suportado em Sonnet 5.5 (tool call veio malformado). 2ª execução com `method="json_schema"`: 4 tool calls, 1 tentativa, aprovada.

**Decisões**
- Saída estruturada via `method="json_schema"` (recurso nativo), não `function_calling`.
- Loop de tools como nós explícitos (`analyze`/`run_tools`) em vez de `create_react_agent`, para o orçamento e a auditoria ficarem visíveis no grafo.
- Percentuais em pt-BR (vírgula decimal) via `MetricResult.formatted`/`pt_percent`, usados no relatório, na CLI e nos caveats.
- Falha de parsing da saída estruturada é tratada como rascunho inválido (entra no mesmo ciclo de retry com feedback).

**Validar**
```
uv run pytest tests/test_graph.py
uv run srag-agent report --no-news --output /tmp/x
```

## Fase 5: guardrails de saída e endurecimento — CONCLUÍDA (2026-11-05)

**Feito**
- `guardrails/numeric_consistency.py`: extrai percentuais e inteiros do texto gerado (ignorando datas, anos, ids `nN`, faixas etárias, inteiros < 13) e confere contra o conjunto permitido: numeradores/denominadores/extras/valores das métricas (como ratio e como percentual), rótulos/definições/caveats, pontos e totais das séries, tamanhos de janela, títulos das notícias e todos os números dos resultados de ferramentas (JSON parseado). Tolerância 0,1 p.p. e 1 unidade. Devolve a lista do que não bateu para o feedback de regeneração.
- `guardrails/pii.py`: CPF (com e sem máscara), e-mail, telefone BR, CNS, número de notificação (12 a 14 dígitos).
- `guardrails/output_validation.py`: além da estrutura, `check_caveats` (cada métrica precisa mencionar sua ressalva: preliminar/atraso, desfecho, leito/ocupação/proporção, população/cobertura/proxy), `check_clinical_advice` (6 padrões de recomendação individual), `check_pii`; `validate_report` audita cada guardrail separadamente e mescla.
- Orçamentos: `max_tool_calls` (nó `run_tools`), `max_write_attempts` (aresta condicional), `max_total_tokens=200k` (nó `analyze` desliga as tools e registra `token_budget`), `recursion_limit=60` no grafo, `max_retries=3` com backoff exponencial do SDK da Anthropic (cobre `RateLimitError`/`APIConnectionError`), timeout de 120 s por chamada e 15 s por SQL.
- Prompt endurecido: "não some, subtraia ou calcule percentuais por conta própria".
- Testes: `tests/test_output_guardrails.py` (17) e mais 2 testes de integração no grafo: número inventado → regeneração → aprovado; número inventado persistente → 3 tentativas → relatório com banner "não verificado" listando os números sem origem. Total: 122 testes.

**Execução real**: na 1ª redação o modelo escreveu "600" (leitura a olho da série diária); `numeric_consistency` reprovou (149 números conferidos, 1 sem origem), a 2ª redação passou em todos os 9 checks.

**Decisões**
- Tolerância do guardrail numérico também aceita um número que esteja a 0,1 p.p. de qualquer razão derivável dos caveats (ex.: "% sem desfecho"), porque esses textos são determinísticos.
- Números que aparecem em títulos de notícias são permitidos (o modelo pode citá-los como "segundo o título"), mas não números derivados deles.
- Orçamento de tokens medido pela própria trilha de auditoria (sem estado extra).

**Validar**
```
uv run pytest tests/test_output_guardrails.py tests/test_graph.py
```

## Fase 6: relatório final — CONCLUÍDA (2026-11-05)

**Feito**
- `report/render.py` já entregue na fase 4 com todas as seções pedidas: título com escopo e data de referência, resumo executivo, tabela das 6 métricas (valor, numerador/denominador, janela), os dois gráficos embutidos, interpretação por métrica (texto do modelo + definição + ressalvas determinísticas), aprofundamento, contexto de notícias com tabela (id, data, fonte, link, citada), limitações e "Como este relatório foi produzido" (execução, hash SHA-256 do Parquet, modelo e tokens, tool calls, consultas de notícias, caminho da auditoria, lista de guardrails com resultado e checks da validação final).
- Exemplo versionado: `reports/exemplo-2026-11-01.md` + `exemplo-2026-11-01-casos-diarios.png` + `exemplo-2026-11-01-casos-mensais.png` (execução real `a8d908d9`, claude-sonnet-5-5, 5 tool calls, 2 redações) e `audit/sample-run.jsonl` correspondente (31 eventos). Conferido que a amostra não contém chave nem dados individuais.

**Validar**
```
uv run srag-agent report
```

## Fase 7: documentação, diagrama e CI — CONCLUÍDA (2026-11-05)

**Feito**
- `docs/architecture.md`: diagrama Mermaid (CLI → orquestrador com os 7 nós → LLM, tools, fontes de dados, guardrails, saída) + tabela de componentes + fluxo passo a passo + justificativas.
- `scripts/render_architecture.py`: extrai o bloco Mermaid e gera `docs/architecture.pdf` via `mermaid.ink/pdf` (funcionou, 371 kB), com fallback para PNG→PDF (Pillow) e para um diagrama de caixas em matplotlib offline.
- `docs/governance.md` (tabela de eventos da auditoria, decisões, proveniência, reprodutibilidade), `docs/guardrails.md` (tabela guardrail × risco × local × mecanismo × teste, comportamento em falha, exemplo real), `docs/data-privacy.md` (quatro camadas: colunas descartadas, LLM só vê agregados, segredos, notícias; nota sobre LGPD).
- `README.md` completo em português: o que é, arquitetura (Mermaid resumido + link para o PDF), como rodar em 3 + 2 comandos, dados e fatos medidos, métricas com definições e ressalvas, governança, guardrails, dados sensíveis, testes (128, cobertura 92%), limitações e trabalho futuro, estrutura do repo, licença.
- `.github/workflows/ci.yml`: `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest --cov`.
- `tests/test_live.py` (marcado `live`, `skipif` sem chave) e `tests/test_cli.py` (5 testes via `CliRunner`, incluindo `report` com modelo fake). O fake padrão agora cicla "ok" para nunca esgotar.

**Validar**
```
uv run python scripts/render_architecture.py
uv run pytest
```

## Fase 8: revisão final e publicação — CONCLUÍDA (2026-11-05)

**Publicado**: após `gh auth refresh -s workflow`, `git push -u origin main` enviou os 10 commits; o repositório foi tornado **público** a pedido do autor e a CI (`.github/workflows/ci.yml`) passou no primeiro run (lint, formatação, 129 testes).


**Checklist do enunciado**
- 4 métricas (aumento de casos em 7 e 30 dias, mortalidade, UTI, vacinação covid e gripe): `srag-agent metrics` e tabela do relatório. ✔
- 2 gráficos (diário 30 dias, mensal 12 meses): `report/charts.py`, embutidos no Markdown. ✔
- Agente consulta banco de dados: tools determinísticas + `run_readonly_sql` sobre DuckDB. ✔
- Notícias em tempo real: Google News RSS (+ Tavily opcional), com triagem de injeção. ✔
- Explicações/comentários sobre o cenário: nós `analyze` e `write_report`, com citações `[nN]`. ✔
- README com toda a documentação; PDF do diagrama em `docs/architecture.pdf`. ✔
- Critérios: arquitetura (`docs/architecture.md`), governança (`docs/governance.md` + `audit/`), guardrails (`docs/guardrails.md`), dados sensíveis (`docs/data-privacy.md`), clean code (ruff limpo, 129 testes, 97% de cobertura, módulos pequenos). ✔

**Passe de clean code**: removidos campo de estado sem uso, regex morto no sanitizador e rótulos não usados; descrição da tool de SQL passou a ser gerada do contrato de dados (`schema.PROCESSED_COLUMNS` + `CODE_LABELS`); teste do provedor Tavily adicionado.

**Verificações finais**: `git ls-files` não contém `.env`, CSVs nem `.duckdb`; `.coverage` ignorado; branch renomeada para `main`.

**Publicação**
- `gh repo create srag-report-agent --private --source . --remote origin --description ... --push` criou o repositório `https://github.com/mateuslima-indicium/srag-report-agent` e configurou `origin`.
- O push foi **recusado pelo GitHub**: o token do `gh` tem escopos `delete_repo, gist, read:org, repo`, mas enviar `.github/workflows/ci.yml` exige o escopo `workflow`. Nada foi enviado ainda.
- Para concluir (interativo, precisa do navegador): `gh auth refresh -h github.com -s workflow` e depois `git push -u origin main`.

**Lembretes para o autor**
- Tornar o repositório público antes de 30/11/2026: `gh repo edit mateuslima-indicium/srag-report-agent --visibility public --accept-visibility-change-consequences`.
- Opcional: adicionar o link do repositório no topo do README.

