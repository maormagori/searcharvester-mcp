# Open Issues

Remaining work after the MCP integration into `simple_tavily_adapter/main.py`.
See `PRODUCTION_READINESS.md` for full context on each finding.

## P0

### Origin validation on `/mcp`
The FastAPI CORS middleware rejects cross-origin browser requests, but the MCP spec requires the server itself to validate the `Origin` header on the `/mcp` endpoint to prevent DNS rebinding. A small ASGI middleware that checks `Origin` against an allowlist (`MCP_ALLOWED_ORIGINS` env var) on any request to `/mcp` is the fix.

## P1

### URL scheme + SSRF in `searcharvester_extract`
`urls` accepts `file://`, `http://169.254.169.254/`, and private IP ranges at the schema level. These are forwarded to `_extract_markdown_for_url` which performs a real HTTP GET. Fix: require `http://` or `https://` scheme; resolve hostname and reject private IP ranges before calling the extractor.

### No MCP tool logging for search and extract
`searcharvester_research` logs at tool entry and completion. `searcharvester_search` and `searcharvester_extract` do not — they call `_execute_search()` and `_extract_markdown_for_url()` directly and those helpers don't log the MCP call context. Fix: add entry/exit log lines in the two MCP tool handlers.

## P2

### No tests
Zero coverage of the MCP tool handlers, output schemas, or error paths. The existing `tests/` directory covers the FastAPI routes; it needs a parallel `test_mcp_tools.py` covering at minimum: normalized search output (no `score`/envelope), extract error propagation (`failed` dict shape), all-failed extract raises `RuntimeError`, and research with `orchestrator=None` raises correctly.

### No concurrency cap on parallel extractions
`asyncio.gather` in `searcharvester_extract` fires all URLs simultaneously. With `max` 20 URLs that's 20 concurrent upstream fetches. Fix: wrap `_extract_one` calls with `asyncio.Semaphore` (default 5, configurable via `EXTRACT_MAX_CONCURRENCY` env var).

## P3

### No README / client setup docs
Nothing tells a user how to register the MCP with Claude Code or Claude Desktop. Fix: add a short section to the project README (or `mcp/README.md`) with the one-liner:
```bash
claude mcp add --transport http searcharvester http://localhost:8000/mcp
```
