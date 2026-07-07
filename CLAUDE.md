# CLAUDE.md

Заметки для будущего Claude (или нового разработчика). Цель — быстро сориентироваться, не перечитывая всю историю.

## Что это за проект

**Searcharvester 2.2.0** — self-hosted стек из HTTP-сервисов и deep-research агента:

- `POST /search` — Tavily-совместимый поиск через SearXNG (100+ движков)
- `POST /extract` — URL → markdown через trafilatura, пресеты `s/m/l/f` + пагинация
- `POST /research` — deep research: спавнит **subprocess `hermes acp`** в адаптере, стримит типизированные ACP-события в UI, возвращает цитируемый markdown-отчёт
- `GET /research/{id}/events` — SSE поток нормализованных событий агента (spawn / thought / tool_call / tool_result / done)

**v2.2 смена архитектуры:** было — эфемерный Docker-контейнер + stdout-regex. Стало — `FROM nousresearch/hermes-agent` + `hermes acp` subprocess + typed events через Python `acp` SDK. Нет больше docker-socket-proxy, нет docker-in-docker, нет regex-парсинга stdout.

Примарно — английский README и документация (3 языка в `docs/`). Переписка со мной обычно на русском, но код-комментарии и доки англоязычные.

Pre-built образ в GHCR: `ghcr.io/vakovalskii/searcharvester:{latest,2.1.0}`.

## Устройство репозитория

| Путь | Что это |
|---|---|
| `docker-compose.yaml` | 4 сервиса: `redis`, `searxng`, `tavily-adapter` (adapter + hermes в одном образе), `frontend` |
| `config.yaml` | **gitignored**, SearXNG settings; монтируется в SearXNG + адаптер |
| `simple_tavily_adapter/` | исходники адаптера (FastAPI + trafilatura + acp) |
| `simple_tavily_adapter/Dockerfile` | `FROM nousresearch/hermes-agent` — hermes CLI внутри образа адаптера |
| `simple_tavily_adapter/docker/entrypoint-adapter.sh` | Обёртка на entrypoint'ом hermes — поднимает HERMES_HOME + exec uvicorn |
| `simple_tavily_adapter/main.py` | FastAPI: `/search`, `/extract`, `/research*`, `/health` |
| `simple_tavily_adapter/orchestrator.py` | ACP-оркестратор: spawn `hermes acp` subprocess, connect_to_agent, forward session_update → Event |
| `simple_tavily_adapter/events.py` | Нормализатор ACP events → flat `Event{ts,job_id,agent_id,parent_id,type,payload}` |
| `simple_tavily_adapter/tests/` | `test_events.py` (normalizer) + `test_research_api.py` (routes, моки) — 12 unit-тестов |
| `hermes_skills/` | три наших skill'а в `agentskills.io` формате: search, extract, deep-research |
| `hermes-data/` | HERMES_HOME. `SOUL.md` + `config.yaml` — **tracked, public, generic** (no deployment-specific values — `base_url` ships empty, filled at runtime from `CUSTOM_BASE_URL`). `skills/` — runtime-only, synced on boot, gitignored |
| `jobs/` | **gitignored**, workspace каждой research-задачи (report.md, hermes.log, **events.jsonl**) |
| `frontend/src/lib/api.ts` | `subscribeToJob()` → EventSource → типизированные `AgentEvent` |
| `frontend/src/components/LogTimeline.tsx` | Рендер timeline из типизированных событий (без regex) |
| `bench/` | SimpleQA-20 smoke-бенч и харнесс |
| `docs/{en,ru,zh}/` | документация на 3 языках + C4-диаграммы (⚠ отстали от 2.2) |

## Архитектура `/research` (v2.2 — ACP)

Поток:

1. `POST /research {query}` → адаптер генерирует `job_id`, создаёт `jobs/{job_id}/`
2. Оркестратор `asyncio.create_subprocess_exec("hermes", "acp", ...)` с `cwd=jobs/{id}`, env = `{**os.environ, **self._env}` — то есть subprocess наследует весь env адаптера (заданный в `docker-compose.yaml`'s `environment:` из корневого `.env`), включая `CUSTOM_BASE_URL`/`OPENAI_API_KEY`/`HERMES_HOME`. Никакого отдельного `.env.hermes`-файла адаптер не читает.
3. `acp.connect_to_agent(client, proc.stdin, proc.stdout)` → initialize → new_session → prompt
4. Каждый `session_update` callback-ом пролетает через `events.normalize_acp_update()` → нормализованный `Event` → append в `job.events` + `asyncio.Condition.notify_all()`
5. Клиент (UI или curl) подписан на `/research/{id}/events` (SSE) — `orchestrator.subscribe()` отдаёт replay + live stream через ту же Condition
6. `prompt` возвращается → читаем `report.md` → статус `completed` → эмитим финальный `done` event + `status` event → SSE закрывается

Ключевые моменты:

- **Один образ**: адаптер `FROM nousresearch/hermes-agent:latest` — hermes CLI лежит в PATH. `entrypoint-adapter.sh` повторяет логику upstream-ного entrypoint'а (HERMES_HOME bootstrap + gosu drop до user `hermes`) и затем `exec uvicorn`. Adapter и Hermes делят один контейнер → нет docker-in-docker, нет docker-socket-proxy.
- **ACP SDK**: `from acp import Client, connect_to_agent` — библиотека `agent-client-protocol` **уже запечена в hermes venv**, нам её не надо доустанавливать. Используем subclass `Client` с `async session_update()` callback'ом.
- **Flat Event schema** (`events.py`): `{ts, job_id, agent_id, parent_id, type, payload}`. `type` — union из `spawn|thought|message|tool_call|tool_result|plan|commands|note|done`. Транспорт-агностично — UI любого типа (React, curl -N, Python-клиент) потребляет одинаково. Если завтра уйдём с Hermes на Claude Code SDK, меняется только normalizer, не UI.
- **events.jsonl** пишется on-the-fly в `jobs/{id}/events.jsonl` — post-mortem доступ без адаптера.
- **cwd = job workspace**, без `/workspace` bind'а. Агент пишет в `./report.md`. `MANDATORY_SUFFIX` в `orchestrator.py` это говорит; SKILL.md тоже переведён на относительные пути.
- **LLM-агностик**: `provider: "custom"` зашит в `hermes-data/config.yaml` (`base_url` там **пустой** — файл публичный и генерик). Реальный бэкенд подставляется через env `CUSTOM_BASE_URL` + `OPENAI_API_KEY`, заданные в корневом `.env` и проброшенные `docker-compose.yaml`. ⚠ **`OPENAI_BASE_URL` больше не читается hermes-agent'ом для резолва endpoint'а** (проверено на `nousresearch/hermes-agent:latest`, `hermes_cli/runtime_provider.py`: "OPENAI_BASE_URL env var is no longer consulted — config.yaml is the single source of truth for endpoint URLs") — единственный env-путь для произвольного OpenAI-совместимого хоста это `CUSTOM_BASE_URL`. `provider: "vllm"` из доков на рантайме не принимается — используем "custom".

## Skills — три штуки

- `searcharvester-search/` — SKILL.md + `scripts/search.py`. Зовёт `/search` через `urllib`, возвращает компактный JSON без лишних полей.
- `searcharvester-extract/` — SKILL.md + `scripts/extract.py`. Зовёт `/extract` и `/extract/{id}/{page}`, отдаёт markdown + метаданные.
- `searcharvester-deep-research/` — **только SKILL.md, без кода**. Методология на ~200 строк: план → gather → gap-check → synthesise → verify. Скилл просто _описывает_ процесс для LLM; реальные tool-вызовы уже есть в первых двух скиллах.

Скиллы синкаются в `hermes-data/skills/` перед спавном. Формат переносимый ([agentskills.io](https://agentskills.io)) — те же скиллы работают в Claude Code, Cursor, OpenCode.

## MCP (FastMCP 3.4.2)

Три инструмента (`searcharvester_search`, `searcharvester_extract`, `searcharvester_research`) смонтированы на `/mcp/` внутри того же FastAPI-приложения на порту 8000.

**Критичные детали wiring в `main.py`:**
- `mcp.http_app(path="/")` — `path="/"` обязателен: без него sub-app маршрут `/mcp` внутри, и при монтировании получается `/mcp/mcp`.
- `app = FastAPI(..., lifespan=_mcp_app.lifespan)` — lifespan обязательно пробрасывать; без него краш при старте.
- DNS rebinding защита: `TrustedHostMiddleware` передаётся через `mcp.http_app(middleware=[...])` (не на уровне FastAPI app). Настраивается через `MCP_ALLOWED_HOSTS` (по умолчанию `localhost` + `127.0.0.1`).

**Регистрация в Claude Code:**
```bash
claude mcp add --transport http searcharvester http://localhost:8000/mcp/
```

**MCP smoke test:**
```bash
SESSION=$(curl -si -X POST http://localhost:8000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')

curl -s -X POST http://localhost:8000/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2,"params":{}}' | python3 -m json.tool
```

## Тесты

- `tests/test_events.py` — 5 unit-тестов нормализатора ACP → Event. Не требуют Docker/hermes.
- `tests/test_research_api.py` — 7 FastAPI route-тестов с моком оркестратора (AsyncMock).
- `tests/test_mcp_tools.py` — 9 тестов MCP tool handlers (search/extract/research) с моками.
- `tests/test_e2e.py` — gated `RUN_E2E=1`. Реальный Hermes + vLLM end-to-end.

Старые `test_orchestrator.py` (FakeDockerClient) удалены — оркестратор больше не использует docker-py. Реальное покрытие "ACP subprocess → events" сейчас даёт E2E (или Playwright smoke через UI).

```bash
docker compose exec tavily-adapter /opt/hermes/.venv/bin/python -m pytest -q  # 46 passed, 1 skipped (e2e) за ~12с
# (pytest не в PATH как алиас — идёт через venv-python)
```

## Известные шероховатости

- **`score` результата `/search` — фейковый** (`0.9 - i*0.05`). Не настоящая релевантность.
- **`/extract` кеш — в памяти, TTL 30 мин.** После рестарта `tavily-adapter` старые `id` инвалидны → клиент должен повторить `POST /extract`.
- **Sub-agent events через ACP не видны**: `delegate_task` — это tool_call лида, но внутренности сабов (их search/extract) в parent ACP stream не прилетают. TODO: тейлить `~/.hermes/sessions/session_*.json` для каждого спавнутого саба и мёрджить в общий поток (через `parent_id`).
- **`tavily_client.py` отстал от `main.py`** — там BeautifulSoup-скрапинг и нет `/extract` логики. Либо синхронизируй, либо удали.
- **`hermes_skills/` vs `hermes-data/skills/`** — source в первом, mount во втором. При правке скилла **надо копировать** в `hermes-data/skills/`. TODO: автоматический sync в entrypoint.
- **Изоляция agent ↔ adapter**: теперь в одном контейнере. Hermes `--yolo` terminal-команды выполняются в адаптерном user space. По сравнению с v2.1 (отдельный контейнер) — даунгрейд изоляции. Критично если кто-то скормит промпт с `rm -rf /app/…`. Пока ок для dev.
- **`Caddyfile` не подключён** к compose — если нужен HTTPS, добавь сервис вручную.
- **`limiter: false`** в `config.yaml` — SearXNG без анти-бот защиты. Ок для локалки, не ок для публичного endpoint'а.
- **Надёжность tool-calling у `/research` зависит от бэкенда/модели.** `hermes acp` всегда получает фиксированный toolset `hermes-acp` (включает `delegate_task`, `web_search`/`web_extract`, `write_file` — см. `toolsets.py` в образе `nousresearch/hermes-agent`), но не любая OpenAI-совместимая модель надёжно эмитит tool calls через ACP wire-протокол. Симптом: агент отвечает обычным чатом ("What would you like me to work on?") вместо `delegate_task`. `orchestrator.py::_finalize_success` это детектит: если `report.md` не появился, но были сообщения — статус `degraded` (не `completed`), с диагностикой "no tool calls observed" vs "ran some tools but no report". MCP-тул `searcharvester_research` на `degraded` кидает `RuntimeError`, так что вызывающий агент не спутает болтовню с cited-отчётом. Модель для `/research` настраивается через env `HERMES_INFERENCE_MODEL` (проброшен в `docker-compose.yaml` и `main.py::pass_env_keys`) — так деплой может подобрать модель понадёжнее, не трогая трекнутый `hermes-data/config.yaml`.

## Git

Репо **не** является GitHub-форком (история чистая с `17906b8 Initial commit`). Раньше унаследовал коммиты от upstream `searxng-docker`, сейчас standalone. `master` удалена, default — `main`.

## Когда пишешь код / документацию

- Доки (README, docs/) — **английский primary**, RU + ZH переводы в `docs/{ru,zh}/`.
- CLAUDE.md и переписка — на русском.
- Не плоди новые markdown-файлы без нужды — проверь `docs/` сначала.
- Секреты (`secret_key`, `OPENAI_API_KEY`) только в `config.yaml` / `.env.hermes` (оба gitignored), **никогда** в коде.
- После изменений в `main.py` / `orchestrator.py` / `events.py` / `Dockerfile` / `entrypoint-adapter.sh` — пересобрать образ: `docker compose --env-file .env.hermes up -d --build tavily-adapter`.
- **`--env-file .env.hermes` критично**: без него `OPENAI_API_KEY`/`OPENAI_BASE_URL` попадают в контейнер пустыми и `hermes acp` падает на первом же LLM-вызове.
- LLM event schema — **контракт с UI**. Если добавляешь новый `type` в `events.py`, обнови `AgentEventType` в `frontend/src/lib/api.ts` + `renderEvent` в `LogTimeline.tsx`.
