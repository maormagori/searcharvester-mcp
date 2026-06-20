# Searcharvester MCP — Roadmap

## Phase 1 — MVP (current)

- `searcharvester_search`: web search via SearXNG, returns ranked results with snippets
- `searcharvester_extract`: URL → clean markdown, parallel multi-URL support
- Streamable HTTP transport (`POST /mcp`)
- `SEARCHARVESTER_URL` + `MCP_PORT` env configuration
- Error propagation as MCP tool errors (no silent failures)

## Phase 2 — Full API coverage

**`searcharvester_research`**
Wraps the async `POST /research` → `GET /research/{id}` polling loop. Blocks until `status=completed` and returns the full markdown report. Configurable timeout defaulting to `RESEARCH_TIMEOUT_SEC` (currently 900s in the adapter). This is the highest-value addition — no other tool in Claude's default toolset does long-form, cited deep research over self-hosted search.

**`searcharvester_extract_page`**
Exposes `GET /extract/{id}/{page}` for paginated reads of documents longer than 25k chars. Requires an `id` from a prior `searcharvester_extract` call with `size=f`. Useful when a document is too long for a single extract response.

**`engines` param on `searcharvester_search`**
Direct passthrough of the `engines` field to SearXNG (e.g. `"google,brave,duckduckgo"`). Currently hardcoded to SearXNG default. Exposing this lets callers target specific engines for different query types.

## Phase 3 — Hardening

- **Origin header validation** on `POST /mcp` — required by the MCP spec to prevent DNS rebinding attacks
- **`MCP-Protocol-Version` enforcement** — return 400 for unsupported protocol versions
- **Per-tool timeouts** — search (30s), extract (30s), and research (configurable, default 15 min) each have different SLAs; make them independently configurable via env vars
- **Startup health check** — fail fast with a clear error if `SEARCHARVESTER_URL` is unreachable at server start
- **Structured logging** — log tool calls with duration, URLs, and error codes; correlate research calls with their `job_id`

## Phase 4 — Docker integration

- Add `mcp` service to `docker-compose.yaml` alongside the existing `tavily-adapter`
- `mcp/Dockerfile`: `python:3.12-slim`, installs `requirements.txt`, runs `server.py`
- Pass `SEARCHARVESTER_URL=http://tavily-adapter:8000` inside the compose network (no host.docker.internal needed)
- Expose `MCP_PORT` (default 8080) on the host
- Health check endpoint at `GET /health` separate from `POST /mcp`

## Phase 5 — Distribution

- **MCPB packaging**: bundle the Python runtime using the `build-mcpb` skill so users can install without Python. Users run one command, no dependency management.
- **Claude Code plugin**: wrap this MCP with skills for common workflows — e.g. `/searcharvester-research <question>` as a slash command that triggers `searcharvester_research` and streams progress
- **Anthropic Directory submission**: run the pre-submission checklist (read/write split, `readOnlyHint`/`destructiveHint` annotations on all tools, name ≤64 chars, no prompt-injection in descriptions, freeform-param tools reference upstream docs)
