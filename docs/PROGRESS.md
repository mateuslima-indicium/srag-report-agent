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

## Fase 1: pipeline de dados — PENDENTE
## Fase 2: métricas e gráficos — PENDENTE
## Fase 3: tools, notícias e guardrail de SQL — PENDENTE
## Fase 4: agente LangGraph — PENDENTE
## Fase 5: guardrails de saída — PENDENTE
## Fase 6: relatório final — PENDENTE
## Fase 7: documentação, diagrama e CI — PENDENTE
## Fase 8: revisão final e publicação — PENDENTE
