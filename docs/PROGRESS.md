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

## Fase 3: tools, notícias e guardrail de SQL — PENDENTE
## Fase 4: agente LangGraph — PENDENTE
## Fase 5: guardrails de saída — PENDENTE
## Fase 6: relatório final — PENDENTE
## Fase 7: documentação, diagrama e CI — PENDENTE
## Fase 8: revisão final e publicação — PENDENTE
