# MCP Production Readiness Review

## 1. Executive Summary

**Overall readiness rating: Prototype**

The MCP server is a clean, minimal wrapper around the Searcharvester HTTP API with two tools. The code is readable, error handling covers the obvious network cases, and tool annotations are partially correct. However, it is not ready for use with real users or automated agents. The critical blockers are: DNS rebinding vulnerability (the HTTP transport binds to `0.0.0.0` with no Origin validation, which is a documented MCP spec requirement), silent data loss in `searcharvester_extract` (extraction failures return `None` with no error reason forwarded to the caller), unpinned dependencies that allow silent regressions, no tests of any kind, and the tool output shapes are passed through raw from the upstream without normalization — making them unreliable for agents.

**Top 5 risks:**

1. DNS rebinding attack on the HTTP transport (`0.0.0.0` + no Origin validation) — a known SSRF vector for HTTP-based MCP servers, explicitly called out in the MCP spec.
2. Silent failure in `searcharvester_extract`: when one or more URLs fail, the error is swallowed and the failure reason is never surfaced to the agent. The agent gets back a bare URL in `failed_results` with no actionable information.
3. Raw passthrough of the upstream `searcharvester_search` response gives the agent a Tavily-shaped blob full of noise fields (`follow_up_questions`, `answer`, `images`, `response_time`, `request_id`, fake `score`) that are either null, empty, or misleading — wasting context and risking hallucinated reasoning on the fake score.
4. No input validation beyond Pydantic schema: `query` can be an empty string, `urls` can be an empty list, and there is no URL format validation for `searcharvester_extract`.
5. Unpinned dependencies (`fastmcp>=2.0`, `httpx` with no version pin) mean any `pip install` can pull a breaking release.

**Top 5 recommended fixes:**

1. Add Origin header validation to the HTTP transport, or document clearly that this MCP must only be run behind a trusted proxy and never exposed on `0.0.0.0` in production.
2. Fix `searcharvester_extract`: propagate per-URL error reasons (HTTP status, network error message) into `failed_results` instead of returning bare URLs; raise a top-level MCP error when all URLs fail.
3. Normalize the search response: strip Tavily envelope fields that are not useful (`follow_up_questions`, `answer`, `images`, `response_time`, `request_id`) and rename fields to clean, stable names in the MCP layer. Never let fake `score` values reach the agent without a disclaimer.
4. Pin all dependencies with exact or constrained versions in `requirements.txt`.
5. Add a non-empty query validator and URL format validator, and raise a structured MCP error (not a bare `RuntimeError`) for all error paths.

**Should this MCP be used with real users yet? No.** It can be used by the author on a trusted local machine for personal experimentation. It should not be exposed to other users, automated agents in CI, or any networked environment until at minimum the DNS rebinding issue and silent failure issues are resolved.

---

## 2. Scope Reviewed

**Files reviewed:**
- `mcp/server.py` — full implementation
- `mcp/requirements.txt` — dependencies
- `mcp/ROADMAP.md` — future work plan
- `simple_tavily_adapter/main.py` — upstream HTTP API being wrapped
- `docs/en/api.md` — upstream API documentation

**Tools reviewed:** `searcharvester_search`, `searcharvester_extract`

**Tests reviewed:** None exist in the `mcp/` directory.

**Docs reviewed:** `ROADMAP.md` (future intent), upstream `api.md` (contract reference), `CLAUDE.md` (internal notes).

**Not reviewed:**
- `orchestrator.py`, `events.py`, `tavily_client.py` — upstream internals, not directly part of the MCP layer but referenced where the MCP passes their output through.
- `hermes_skills/` — not relevant to the MCP server.
- `frontend/` — not relevant to the MCP server.

---

## 3. Standards Baseline

- **Model Context Protocol specification** (2024-11, 2025-03 drafts) — tool schema format, tool annotations (`readOnlyHint`, `openWorldHint`, `destructiveHint`), error handling protocol (MCP errors vs tool errors), HTTP transport security requirements (Origin header validation to prevent DNS rebinding), and server metadata format.
- **MCP security best practices** — DNS rebinding prevention for HTTP transport, input validation, output sanitization to prevent prompt injection, least-privilege tool design.
- **FastMCP 2.x behavior** — how `FastMCP` maps Python exceptions to MCP error responses, how `@mcp.tool` annotations are surfaced to clients, and how tool return types affect the serialized response.
- **Agent usability standards** — output shape predictability, error message actionability, parameter descriptions that reduce hallucination, tool descriptions that correctly scope when to use each tool.

---

## 4. Readiness Scorecard

| Area | Rating | Evidence | Production Impact | Required Action |
|---|---|---|---|---|
| MCP protocol correctness | Partial | Annotations present and correctly typed. Errors raised as bare `RuntimeError` rather than structured MCP tool errors. | Medium | Convert errors to structured MCP error responses. |
| Tool schema quality | Partial | Pydantic `Field` descriptions present. `query` has no min-length, `urls` has no min-items, URL strings have no format validation. | Medium | Add `min_length=1` to `query`, `min_items=1` to `urls`, URL format validation. |
| Tool descriptions | Partial | Docstrings exist and cross-reference each other. Neither describes output shape, which fields to trust, or that `score` is fake. | Low–Medium | Extend descriptions to include output shape hints and caveats. |
| Input validation | Fail | `query=""` accepted. `urls=[]` accepted (silent empty result). URL strings not validated — file paths and internal hostnames pass. | High | Add validators. |
| Output consistency | Fail | `searcharvester_search` passes full upstream Tavily envelope through raw including fake `score` and null fields. `searcharvester_extract` `failed_results` contains only URLs with no failure reason. | High | Normalize outputs in the MCP layer. |
| Error handling | Partial | Network errors caught and converted to `RuntimeError`. Per-URL errors in extract silently caught (`except Exception: return url, None`). Total failure returns HTTP 200 with no MCP error. | High | Propagate error reasons into `failed_results`; raise tool error when all extractions fail. |
| Security | Fail | HTTP transport bound to `0.0.0.0` with no Origin header validation. No authentication. `SEARCHARVESTER_URL` accepts any URL. | Critical | Implement Origin header validation; document authentication requirements. |
| Permissions model | Partial | `readOnlyHint: true` and `openWorldHint: true` correctly set on both tools. No `destructiveHint` needed and none set. | Low | Add deployment docs clarifying network access requirements. |
| Reliability | Fail | No retry logic. No circuit breaking. No concurrency cap on parallel extractions. No startup health check. `httpx.AsyncClient` created per-call with no connection pooling. | Medium–High | Add per-request timeouts, retry for transient errors, startup check. |
| Observability | Fail | No logging of any kind. No request tracing. No metrics. | Medium | Add structured logging at tool entry/exit. |
| Testing | Fail | Zero tests. | High | Write unit tests for output normalization and error paths. |
| Documentation | Partial | `ROADMAP.md` is detailed. No `README.md` for `mcp/`. No documented output contract or error taxonomy. | Medium | Add README; document installation, configuration, and tool output shapes. |
| Client compatibility | Partial | Streamable HTTP transport is correct. No `stdio` transport option for Claude Desktop / Claude Code. | Medium | Add a `stdio` launch path for local clients. |
| Deployment readiness | Fail | No Dockerfile. No `docker-compose` integration. No `GET /health` endpoint. `host="0.0.0.0"` hardcoded with no localhost restriction. | High | Add Dockerfile, health endpoint, localhost-only option. |

---

## 5. Tool-by-Tool Review

### Tool: `searcharvester_search`

**Current purpose:** Execute a web search via the Searcharvester upstream and return ranked results with titles, URLs, and snippets.

**Current input schema:**
- `query: str` — search keywords or question (no min-length constraint)
- `max_results: int` — 1–20, default 5
- `topic: Literal["general", "news"]` — search category, default "general"
- `search_depth: Literal["basic", "advanced"]` — depth preset, default "basic"
- `include_raw_content: bool` — fetch full page markdown, default False

**Current output shape:** The raw upstream response from `POST /search` — a Tavily-shaped dict:
```json
{
  "query": "...",
  "follow_up_questions": null,
  "answer": null,
  "images": [],
  "results": [{"url": "...", "title": "...", "content": "...", "score": 0.9, "raw_content": null}],
  "response_time": 1.42,
  "request_id": "uuid"
}
```

**Problems found:**

1. **Fake `score` field reaches the agent unwarned.** The upstream API docs explicitly state: "`score` is fake (0.9 - i*0.05). Don't use it for ranking." An agent that reads the score field may use it for ranking decisions and produce incorrect results.
2. **Noise fields in output.** `follow_up_questions: null`, `answer: null`, `images: []`, `response_time`, and `request_id` consume context window tokens and may confuse agents.
3. **`search_depth` silently overrides `include_raw_content`.** When `search_depth="advanced"`, the code forces `include_raw_content=True` even if the caller passed `include_raw_content=False`. This side effect is not described in either field description.
4. **`query` has no minimum-length constraint.** An empty string is a valid query at the schema level.
5. **`topic` maps to `categories` but the upstream supports many more values** (`images`, `videos`, `map`, `music`, `it`, `science`, `files`, `social`) — the two-value constraint is undocumented.

**Agent usability concerns:**
- No guidance on when to trust `content` (SearXNG snippet, often truncated) vs `raw_content` (full page markdown).
- The fake `score` is particularly harmful for agents reasoning about result relevance.

**Reliability concerns:**
- No retry on transient upstream failures (e.g. SearXNG 504 timeout).
- No distinction between "no results found" and "search succeeded" — both return the same shape.

**Security concerns:** Low. `query` is passed to upstream as-is but not interpolated into any prompt. No prompt-injection risk in the search path.

**Recommended changes:**
- Normalize output: strip `follow_up_questions`, `answer`, `images`, `response_time`, `request_id`. Return only `query`, `results` (with `url`, `title`, `content`, optional `raw_content`), and `result_count`.
- Remove or rename `score` — either strip it, or rename to `rank` (integer 1-N) to accurately describe what it represents.
- Add `min_length=1` to `query`.
- Document the `search_depth` / `include_raw_content` interaction explicitly in both field descriptions.

**Proposed output schema:**
```json
{
  "query": "string",
  "results": [{"url": "string", "title": "string", "content": "string", "raw_content": "string|null"}],
  "result_count": "int"
}
```

**Better description:** "Search the web and return titles, URLs, and snippets for the query. Results include a brief `content` snippet from the search engine. Set `include_raw_content=true` to also fetch the full page markdown for each result (slower). Results are ranked by position, not by a relevance score."

**Production-ready: No**
**Priority: P0** (output normalization), **P1** (input validation, description)

---

### Tool: `searcharvester_extract`

**Current purpose:** Fetch one or more URLs and return their main content as clean markdown.

**Current input schema:**
- `urls: list[str]` — one or more URLs (no min-items, no URL format validation)
- `extract_depth: Literal["basic", "advanced"]` — maps to `size="m"` (10k chars) or `size="l"` (25k chars), default "basic"

**Current output shape:**
```json
{
  "results": [{"url": "string", "raw_content": "string"}],
  "failed_results": ["url1", "url2"]
}
```

**Problems found:**

1. **Silent failure with no error reason.** `_extract_one` catches all exceptions and returns `(url, None)`. No error message, HTTP status, or exception type is preserved. The agent receives a list of failed URLs but has no idea why they failed.
2. **Total failure indistinguishable from partial failure.** If all URLs fail, the tool returns `{"results": [], "failed_results": [...]}` with HTTP 200 and no MCP error. An agent checking `len(results) == 0` has no signal this is an error state.
3. **`urls` can be an empty list.** Returns `{"results": [], "failed_results": []}` silently.
4. **URL format not validated.** `urls=["file:///etc/passwd"]` or `urls=["http://169.254.169.254"]` are accepted at the schema level and forwarded to the upstream, which will attempt to fetch them.
5. **`size="f"` (full/paginated) not exposed.** The upstream supports documents longer than 25k chars via pagination. The MCP only surfaces `m` (10k) and `l` (25k). Agents cannot retrieve long documents.
6. **`title`, `chars`, and `total_chars` are dropped.** The upstream response includes all three; the MCP reads only `content`. Agents cannot know if content was truncated.

**Agent usability concerns:**
- An agent doing multi-URL research gets failures with no information on whether to retry.
- An agent cannot know if content was truncated at 25k chars from a 100k-char document.
- No `title` means the agent must re-derive the document title from the body.

**Reliability concerns:**
- `asyncio.gather` fires all URL extractions simultaneously with no concurrency cap. 20 parallel requests are possible.
- No rate limiting on concurrent upstream calls.

**Security concerns:**
- **SSRF via cloud metadata endpoints:** `http://169.254.169.254/latest/meta-data/` is a valid schema-level input in AWS/GCP/Azure environments. A prompt injection attack can redirect the agent to extract internal metadata.
- `file://` URLs will fail at the upstream but only after an attempt, with the error landing silently in `failed_results`.

**Recommended changes:**
- Refactor `_extract_one` to return `{"url": str, "content": str | None, "error": str | None}`. Capture exception message or HTTP status in `error`.
- Surface as `{"url": "...", "error": "HTTP 403: Forbidden"}` in the `failed` list (rename from `failed_results` for clarity).
- Raise a top-level MCP tool error when all extractions fail.
- Add `min_items=1` to `urls` and require `http://` or `https://` scheme.
- Add private-IP blocklist for production deployments.
- Include `title`, `truncated: bool`, `chars`, and `total_chars` in each result.
- Consider adding `"full"` as a third `extract_depth` value mapping to `size="f"`.
- Cap concurrent extractions with `asyncio.Semaphore` (default 5, configurable).

**Proposed output schema:**
```json
{
  "results": [
    {"url": "string", "title": "string", "content": "string", "truncated": true, "chars": 10000, "total_chars": 67000}
  ],
  "failed": [
    {"url": "string", "error": "string"}
  ]
}
```

**Better description:** "Fetch one or more web pages and return their main content as clean markdown. Navigation, ads, and boilerplate are stripped. Each result includes the page title, content, and whether it was truncated. Failed URLs include an error reason. To discover URLs first, use searcharvester_search."

**Production-ready: No**
**Priority: P0** (silent failure), **P1** (missing fields, SSRF validation), **P2** (full-size support)

---

## 6. Security Findings

### Finding: DNS Rebinding Attack on HTTP Transport

- **Severity: Critical**
- **Affected code path:** `server.py` — `mcp.run(transport="http", host="0.0.0.0", ...)`
- **Evidence from the code:** The server binds to `0.0.0.0` (all interfaces). There is no Origin header check. The ROADMAP explicitly lists Origin header validation as Phase 3, acknowledging the gap.
- **Why this matters:** HTTP-based MCP servers that accept requests without validating the `Origin` header are vulnerable to DNS rebinding. A malicious web page loaded in any browser on the same machine can send requests to the MCP server via DNS rebinding, bypassing same-origin policy.
- **Exploit scenario:** User visits a malicious page while the MCP server is running. The page's JS sends `POST` to `http://evil.rebind.example.com:8080/mcp` (which resolves to `127.0.0.1:8080`). The MCP server processes the request and the attacker can call any tool, extract any URL including internal services, and exfiltrate content.
- **Recommended mitigation:** Restrict to `host="127.0.0.1"` for local deployments. For networked deployments, add Origin header validation middleware that rejects `Origin` values not in an explicit allowlist (`MCP_ALLOWED_ORIGINS` env var).
- **Priority: P0**
- **Blocks production: Yes**

---

### Finding: SSRF via Unvalidated URLs in `searcharvester_extract`

- **Severity: High**
- **Affected code path:** `server.py` — `urls` parameter of `searcharvester_extract`, forwarded to upstream `_fetch_html`.
- **Evidence from the code:** `urls` is typed as `list[str]` with no scheme or IP validation. Values are passed directly to `client.post(f"{SEARCHARVESTER_URL}/extract", json={"url": url, ...})`. The upstream performs a real HTTP GET.
- **Why this matters:** In AWS/GCP/Azure, the instance metadata endpoint (`http://169.254.169.254/`) is accessible from any process. A prompt injection attack from scraped web content can cause the agent to call `searcharvester_extract` with a metadata endpoint URL, and the upstream will fetch and return it — potentially including IAM credentials.
- **Exploit scenario:** Prompt injection in a search result causes agent to call `searcharvester_extract(urls=["http://169.254.169.254/latest/meta-data/iam/security-credentials/"])`. Content is returned to the agent.
- **Recommended mitigation:** Validate URLs in the MCP layer before forwarding: require `http://` or `https://` scheme; resolve hostname and reject private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`); reject `localhost` and `127.0.0.1`.
- **Priority: P1**
- **Blocks production: Yes for any networked deployment**

---

### Finding: No Authentication on MCP Server

- **Severity: Medium**
- **Affected code path:** `server.py` overall — `mcp.run(transport="http", host="0.0.0.0", ...)`
- **Evidence from the code:** No API key, bearer token, or any authentication mechanism is implemented or referenced.
- **Why this matters:** Anyone on the same network (or the internet if port-forwarded) can call any MCP tool — arbitrary web scraping via the upstream, potential SSRF if URL validation is absent.
- **Exploit scenario:** Port 8080 is accidentally exposed. Any internet user can call `searcharvester_extract` to use the upstream as a free web scraper.
- **Recommended mitigation:** For local use, `host="127.0.0.1"` is sufficient. For networked use, implement bearer token authentication via FastMCP middleware or deploy behind a reverse proxy (Caddy, nginx) that handles authentication.
- **Priority: P1**
- **Blocks production: Yes for networked deployments**

---

### Finding: `SEARCHARVESTER_URL` Accepts Arbitrary Hosts

- **Severity: Medium**
- **Affected code path:** `server.py` line 9 — `SEARCHARVESTER_URL` environment variable.
- **Evidence from the code:** `SEARCHARVESTER_URL = os.getenv("SEARCHARVESTER_URL", "http://localhost:8000").rstrip("/")`. No validation. All upstream requests are constructed as `f"{SEARCHARVESTER_URL}/search"` etc.
- **Why this matters:** If an attacker can control environment variables, they can redirect all MCP upstream calls to an attacker-controlled server returning malicious content designed to cause prompt injection.
- **Recommended mitigation:** Validate `SEARCHARVESTER_URL` at startup: require HTTP/HTTPS scheme, optionally require a hostname allowlist. Log the resolved URL at startup.
- **Priority: P2**

---

### Finding: Error Messages May Leak Internal Details

- **Severity: Low**
- **Affected code path:** `server.py` — `HTTPStatusError` handler in `searcharvester_search`.
- **Evidence from the code:** `raise RuntimeError(f"Searcharvester /search returned {exc.response.status_code}: {exc.response.text[:200]}")` — first 200 chars of upstream error body forwarded to agent.
- **Why this matters:** If the upstream returns an error including internal hostnames, IP addresses, or stack traces, those are forwarded to the agent and potentially logged by the MCP host.
- **Recommended mitigation:** Log full upstream error server-side; surface only `"Search service returned an error (HTTP {status}). Check server logs for details."` to the agent.
- **Priority: P3**

---

## 7. Reliability and Error Handling Findings

### Silent Per-URL Failure in `searcharvester_extract`

`_extract_one` catches `Exception` broadly and returns `(url, None)`. No error message is preserved. The `failed_results` list contains only URLs with no failure reasons. An agent calling this tool to extract 5 URLs gets back 3 successes and 2 bare URLs in `failed_results` with zero diagnostic information.

**Required production behavior:** Return `{"url": str, "error": str}` in `failed`. Capture HTTP status or exception message in `error`. Raise a top-level MCP error when all URLs fail.

---

### Total Failure Returns HTTP 200 With No MCP Error

When all URLs in `searcharvester_extract` fail, the tool returns `{"results": [], "failed_results": [...]}` with a successful MCP response. An agent that does not explicitly check `len(results) == 0` will silently proceed with empty data.

**Required production behavior:** Raise a structured MCP tool error when `results` is empty and `failed` is non-empty.

---

### No Retry Logic for Transient Upstream Failures

Neither tool retries on transient errors (connection reset, 502, 503, 504). A single SearXNG timeout immediately surfaces as a tool error. One retry with exponential backoff would recover most transient failures.

**Required production behavior:** One retry with short delay for `httpx.RequestError` and HTTP 5xx in `searcharvester_search`. In `_extract_one`, one retry for connection errors (not 4xx, which are permanent).

---

### Unbounded Concurrent Extractions

`asyncio.gather(*[_extract_one(client, url) for url in urls])` fires all URL extractions simultaneously. With 20 URLs this creates 20 concurrent upstream requests.

**Required production behavior:** Cap concurrency using `asyncio.Semaphore`. Default 5, configurable via `EXTRACT_MAX_CONCURRENCY`.

---

### No Startup Health Check

The MCP server starts successfully even if `SEARCHARVESTER_URL` is unreachable. The first tool call fails with `RuntimeError`. Operators have no signal at deploy time.

**Required production behavior:** On startup, send `GET {SEARCHARVESTER_URL}/health`. Log a clear warning if it fails (do not crash — upstream may start after MCP in docker-compose).

---

### `httpx.AsyncClient` Created Per Request, No Connection Pooling

Both tools create a new `httpx.AsyncClient()` per tool invocation inside an `async with` block. New TCP + TLS handshake on every call. For concurrent agents this adds significant latency.

**Required production behavior:** Module-level singleton `httpx.AsyncClient` with connection pooling.

---

### Unpinned Dependencies

`fastmcp>=2.0` and `httpx` with no upper bound or exact version. A breaking release of either can silently break the server.

**Required production behavior:** Pin exact versions. Use a lockfile (`pip-tools` or `uv lock`).

---

## 8. Agent Usability Findings

### Fake Score Field Reaches Agents Without Warning

`score: 0.9 - i*0.05` (position-based, not semantic) reaches the agent with no disclaimer. Upstream docs explicitly warn "Don't use it for ranking." Strip or rename to `rank` (integer 1-N).

---

### No Signal That Content Was Truncated

Content is truncated at 10k/25k chars. The upstream returns `total_chars`. The MCP drops it. Agents reading long documents have no idea they're seeing 30% of the content. Include `truncated: bool` and `total_chars: int` in each extract result.

---

### No Tool for Full/Paginated Documents

The upstream supports `size="f"` for documents >25k chars with `GET /extract/{id}/{page}` pagination. The MCP exposes no equivalent. Long documents are silently capped. Prioritize Phase 2 `searcharvester_extract_page`.

---

### No `stdio` Transport for Local Clients

Claude Desktop and Claude Code prefer `stdio` for local MCP servers. The current server requires running a persistent HTTP process. Add `MCP_TRANSPORT` env var: when `stdio`, call `mcp.run(transport="stdio")`.

---

### Tool Names Are Verbose

Within an MCP server named `searcharvester`, the `searcharvester_` prefix is redundant. Consider `web_search` and `fetch_pages` aligned with Anthropic Directory naming conventions.

---

### Server-Level `instructions` Too Minimal

The FastMCP `instructions` field doesn't tell agents: what the output shape looks like, that search scores are positional not semantic, that extract may truncate, that failed URLs report reasons in `failed` not as an error. Expand with these two caveats in under 150 words.

---

## 9. Documentation Gaps

1. **No README in `mcp/`.** No installation guide, no configuration reference, no "how to connect to Claude" instructions.
2. **No documented output contract.** No definition of which fields agents can rely on, which are informational/unstable, and which are synthetic (like `score`).
3. **No documented error taxonomy.** Agents need to know what a non-empty `failed_results` means and when to retry vs. give up.
4. **No client configuration examples.** No Claude Desktop JSON snippet, no Claude Code `.mcp.json` example, no env var documentation.
5. **ROADMAP treats security as optional.** Origin header validation and other MCP spec requirements are listed as Phase 3 "hardening" — they are pre-production blockers, not enhancements.
6. **No MCP-specific docs.** `docs/en/api.md` covers the upstream HTTP API only. No MCP layer documentation exists.

---

## 10. Test Plan

### Unit Tests

- `test_search_normalizes_output` — mock upstream returning Tavily envelope; assert no `follow_up_questions`, `answer`, `images`, `score`; assert `result_count` present.
- `test_search_empty_results` — upstream returns `results: []`; assert tool returns `{query, results: [], result_count: 0}` without error.
- `test_search_upstream_500` — mock upstream returning HTTP 500; assert structured MCP error.
- `test_search_upstream_unreachable` — mock `httpx.RequestError`; assert MCP error with informative message.
- `test_search_advanced_depth_forces_raw_content` — call with `search_depth="advanced", include_raw_content=False`; assert upstream receives `include_raw_content: true`.
- `test_search_empty_query_rejected` — call with `query=""`; assert Pydantic validation error before upstream call.
- `test_extract_returns_title_and_truncation_signal` — mock upstream returning `{content, title, total_chars: 50000, chars: 10000}`; assert result includes `title`, `truncated=True`, `total_chars=50000`.
- `test_extract_failed_url_returns_error_reason` — mock one URL returning HTTP 403; assert `failed` contains `{"url": "...", "error": "HTTP 403"}`.
- `test_extract_all_failed_raises_mcp_error` — mock all URLs failing; assert top-level MCP error, not empty result.
- `test_extract_empty_urls_rejected` — call with `urls=[]`; assert validation error.
- `test_extract_invalid_url_rejected` — call with `urls=["not-a-url"]`; assert validation error before upstream call.
- `test_extract_private_ip_rejected` — call with `urls=["http://169.254.169.254/"]`; assert validation error.

### Integration Tests

Require a running Searcharvester upstream at `localhost:8000`:

- `test_search_real_query` — real search for a known term; assert result count > 0, all results have `url` and `title`.
- `test_extract_real_url` — extract `https://example.com`; assert `content` non-empty, `title` present.
- `test_extract_multi_url_partial_failure` — one valid and one invalid URL; assert 1 result, 1 failed entry with error reason.
- `test_search_news_topic` — search with `topic="news"`; assert no error.

### Security Tests

- `test_origin_header_validation` — send `POST /mcp` with `Origin: http://evil.example.com`; assert 403.
- `test_extract_metadata_endpoint_rejected` — call with `urls=["http://169.254.169.254/"]`; assert validation error.
- `test_extract_file_url_rejected` — call with `urls=["file:///etc/passwd"]`; assert validation error.
- `test_searcharvester_url_startup_warning` — set `SEARCHARVESTER_URL=http://nonexistent.internal`; assert server logs warning at startup.

### MCP Inspector Manual Checklist

- [ ] Connect to `http://localhost:8080/mcp`. Verify server name `searcharvester` and both tools listed with correct annotations.
- [ ] Call `searcharvester_search` with valid query. Inspect raw JSON response — no `score`, no `follow_up_questions`, `result_count` present.
- [ ] Call `searcharvester_search` with `query=""`. Verify informative validation error.
- [ ] Call `searcharvester_extract` with one valid URL. Verify `title`, `content`, `truncated`, `total_chars` present.
- [ ] Call `searcharvester_extract` with one valid and one invalid URL. Verify `failed` contains `{"url": "...", "error": "..."}`.
- [ ] Call `searcharvester_extract` with only invalid URLs. Verify top-level MCP error raised, not empty result.
- [ ] Call `searcharvester_extract` with `urls=[]`. Verify validation error, not crash.
- [ ] Shut down upstream. Call any tool. Verify error message is informative.
- [ ] Send request with `Origin: http://evil.example.com`. Verify 403 (after Origin validation is implemented).

### Client Compatibility Tests

- [ ] Claude Desktop (macOS): configure via `stdio` mode; verify both tools appear and return results.
- [ ] Claude Code CLI: configure via `.mcp.json`; verify both tools callable from a session.
- [ ] MCP Inspector (HTTP mode): verify all tool calls succeed and return expected shapes.

---

## 11. Production Readiness Roadmap

### P0: DNS Rebinding / Origin Validation

- **Reason:** MCP spec requirement; Critical security vulnerability; exploitable with zero user interaction.
- **Affected files:** `server.py` (transport configuration).
- **Approach:** Change `host="0.0.0.0"` to `host="127.0.0.1"` for local deployments. For networked deployments, add ASGI middleware that reads `Origin` header and rejects requests where `Origin` is present and not in `MCP_ALLOWED_ORIGINS` allowlist.
- **Acceptance criteria:** Request with `Origin: http://evil.example.com` returns HTTP 403. Request with no `Origin` header succeeds. Request with allowlisted origin succeeds.
- **Tests:** `test_origin_header_rejected`, `test_no_origin_allowed`, `test_allowlisted_origin_allowed`.

---

### P0: Fix Silent Failure in `searcharvester_extract`

- **Reason:** Agents cannot handle failures they cannot see. Affects every multi-URL extraction call.
- **Affected files:** `server.py`, `searcharvester_extract`.
- **Approach:** Refactor `_extract_one` to return `{"url": str, "content": str | None, "error": str | None}`. Catch `httpx.HTTPStatusError` to capture status code; catch `httpx.RequestError` for network errors. If `results` is empty and `failed` is non-empty, raise MCP tool error.
- **Acceptance criteria:** Calling extract on a 404 URL returns `{"url": "...", "error": "HTTP 404"}` in `failed`. All-failed call raises top-level MCP error.
- **Tests:** `test_extract_failed_url_returns_error_reason`, `test_extract_all_failed_raises_mcp_error`.

---

### P0: Pin Dependencies

- **Reason:** Unpinned deps allow silent regressions on any `pip install` or deploy.
- **Affected files:** `mcp/requirements.txt`.
- **Approach:** Run `pip freeze` in a clean virtualenv, record exact versions. Add `pyproject.toml` for proper packaging. Use `uv` with a lockfile.
- **Acceptance criteria:** `pip install -r requirements.txt` in a fresh environment installs exactly the same versions as the development environment.

---

### P1: Normalize `searcharvester_search` Output

- **Reason:** Fake `score`, null fields, and internal metadata waste agent context and mislead reasoning.
- **Affected files:** `server.py`, `searcharvester_search`.
- **Approach:** After receiving upstream response, build a new dict: `query`, `results` (with `url`, `title`, `content`, optional `raw_content`), `result_count`. Strip `score`/rename to `rank`. Remove `follow_up_questions`, `answer`, `images`, `response_time`, `request_id`.
- **Acceptance criteria:** Return value contains no `score`, `follow_up_questions`, `answer`, `images`, `response_time`, `request_id`. Each result has `url`, `title`, `content`, optional `raw_content`, and `rank`.
- **Tests:** `test_search_normalizes_output`.

---

### P1: Add Input Validators

- **Reason:** Empty queries, empty URL lists, and non-HTTP URLs should be caught before hitting the upstream.
- **Affected files:** `server.py`, both tools.
- **Approach:** Add `min_length=1` to `query`. Add `min_items=1` to `urls`. Add `min_length=1` to each URL string. Add custom validator requiring `http://` or `https://` scheme.
- **Acceptance criteria:** `searcharvester_search(query="")` raises validation error. `searcharvester_extract(urls=[])` raises validation error. `searcharvester_extract(urls=["ftp://bad"])` raises validation error.
- **Tests:** `test_search_empty_query_rejected`, `test_extract_empty_urls_rejected`, `test_extract_invalid_url_rejected`.

---

### P1: Add Truncation Signals to `searcharvester_extract` Output

- **Reason:** Agents reading truncated content need to know content was cut off.
- **Affected files:** `server.py`, `searcharvester_extract`.
- **Approach:** Read `total_chars`, `chars`, and `title` from upstream response. Add `truncated: bool` (true if `chars < total_chars`), `total_chars: int`, and `title: str` to each result.
- **Acceptance criteria:** Each result includes `title`, `truncated`, `chars`, `total_chars`.
- **Tests:** `test_extract_returns_title_and_truncation_signal`.

---

### P1: Add Structured Logging

- **Reason:** Zero observability. No diagnostic trail for production failures.
- **Affected files:** `server.py`.
- **Approach:** Add `logging` call at start and end of each tool: log tool name, input summary (query text, URL count), duration, and outcome. Use structured logging (JSON formatter). Log upstream HTTP errors with status code and truncated body.
- **Acceptance criteria:** A search call produces two log lines (entry with query, exit with result count and duration). An error produces a log line with error type and message.
- **Tests:** Assert log output in unit tests using `caplog`.

---

### P1: Add SSRF Protection for URLs

- **Reason:** Cloud metadata endpoints accessible in many deployment environments. Prompt injection can redirect agents to internal URLs.
- **Affected files:** `server.py`, `searcharvester_extract`.
- **Approach:** Before forwarding any URL to upstream, validate: scheme is `http` or `https`; resolve hostname and check not in private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`). Raise validation error for violations.
- **Acceptance criteria:** `searcharvester_extract(urls=["http://169.254.169.254/"])` raises validation error with clear message.
- **Tests:** `test_extract_private_ip_rejected`, `test_extract_metadata_endpoint_rejected`.

---

### P2: Add `stdio` Transport Support

- **Reason:** Claude Desktop and Claude Code prefer stdio for local MCP servers.
- **Affected files:** `server.py`.
- **Approach:** Add `MCP_TRANSPORT` env var. When `MCP_TRANSPORT=stdio`, call `mcp.run(transport="stdio")`. Document Claude Desktop / Claude Code JSON configuration snippet in README.
- **Acceptance criteria:** `python server.py` with `MCP_TRANSPORT=stdio` works with Claude Desktop.

---

### P2: Add Dockerfile and Health Endpoint

- **Reason:** No deployment path. No liveness checking.
- **Affected files:** `mcp/` directory, `docker-compose.yaml`.
- **Approach:** Create `mcp/Dockerfile` from `python:3.12-slim`. Add `GET /health` route checking upstream reachability. Add `mcp` service to `docker-compose.yaml` with `SEARCHARVESTER_URL=http://tavily-adapter:8000`.
- **Acceptance criteria:** `docker compose up` starts MCP server. `curl localhost:8080/health` returns 200 with upstream status.

---

### P2: Add Concurrency Cap for Parallel Extractions

- **Reason:** Unbounded `asyncio.gather` on 20 URLs can overwhelm the upstream and downstream sites.
- **Affected files:** `server.py`, `searcharvester_extract`.
- **Approach:** Add `asyncio.Semaphore(n)` where `n` defaults to 5, configurable via `EXTRACT_MAX_CONCURRENCY`. Wrap each `_extract_one` call.
- **Acceptance criteria:** With 20 URLs, at most 5 upstream requests in flight simultaneously.

---

### P2: Write Tests

- **Reason:** Zero tests. Any change to `server.py` can silently break tool behavior.
- **Affected files:** `mcp/tests/` (create).
- **Approach:** Use `pytest` + `pytest-asyncio`. Mock `httpx.AsyncClient` with `respx`. Cover all unit test cases in Section 10.
- **Acceptance criteria:** `pytest mcp/tests/` passes with ≥90% coverage of `server.py`. All error handling paths have at least one test.

---

### P3: Add Full-Page Extraction Tool

- **Reason:** Long documents silently truncated at 25k chars. Research workflows need full document access.
- **Affected files:** `server.py`.
- **Approach:** Implement `searcharvester_extract_page` accepting `id` (from prior extract call) and `page` (integer ≥ 1). Forward to `GET {SEARCHARVESTER_URL}/extract/{id}/{page}`. Handle 404 (expired cache, invalid page) as structured error.
- **Acceptance criteria:** Agent can retrieve all pages of a long document. Clear error when cache has expired.

---

### P3: Add README for `mcp/`

- **Reason:** No installation or configuration documentation.
- **Affected files:** `mcp/README.md` (create).
- **Approach:** Cover prerequisites, installation, configuration (env vars: `SEARCHARVESTER_URL`, `MCP_PORT`, `MCP_TRANSPORT`), running in HTTP mode, running in stdio mode, Claude Desktop / Claude Code JSON configuration snippet, and tool output contracts.
- **Acceptance criteria:** A developer unfamiliar with the project can get the MCP running and connected to Claude in under 10 minutes from the README alone.

---

## 12. Definition of Done for Production

- [ ] Origin header validation implemented and tested (P0)
- [ ] `searcharvester_extract` propagates per-URL error reasons (P0)
- [ ] All dependencies pinned with exact versions (P0)
- [ ] `searcharvester_search` output normalized — no fake score, no null envelope fields (P1)
- [ ] Input validators in place: empty query, empty URL list, non-HTTP URL schemes (P1)
- [ ] `searcharvester_extract` output includes `title`, `truncated`, `total_chars` per result (P1)
- [ ] Structured logging in place for all tool calls (P1)
- [ ] SSRF protection in place for URL inputs (P1)
- [ ] Unit tests pass with ≥90% coverage of `server.py` (P2)
- [ ] Integration tests pass against a real upstream (P2)
- [ ] `stdio` transport mode documented and tested (P2)
- [ ] Dockerfile exists and `docker compose up` works end-to-end (P2)
- [ ] Health endpoint returns upstream reachability status (P2)
- [ ] Concurrency cap in place for parallel extractions (P2)
- [ ] README covers installation, configuration, and client connection (P3)
- [ ] MCP Inspector manual checklist complete — all items pass
- [ ] No Critical or High security findings open

---

## 13. Final Recommendation

**Should this MCP be used now?**
Only by the author, on a trusted local machine, with the MCP server bound to `127.0.0.1` (not `0.0.0.0`), for personal experimentation. It should not be shared with other users, run in CI, or deployed on any server accessible to others.

**Minimum work before safe personal use:**
1. Change `host="0.0.0.0"` to `host="127.0.0.1"` in `server.py` — one-line change that eliminates DNS rebinding risk.
2. Pin dependency versions in `requirements.txt`.

**Minimum work before production use:**
- All P0: Origin validation, silent failure fix in extract, pinned dependencies.
- All P1: Output normalization, input validators, truncation signals, logging, SSRF protection.
- P2 testing: a passing test suite before any change can be trusted.

**What to do first:**
The highest-leverage first action is fixing `searcharvester_extract`'s silent failure. It is the most painful user-facing bug, it is easy to fix, and fixing it reveals what the actual error shapes look like — which informs the output normalization work for P1. Do this alongside the `host="127.0.0.1"` change. Then pin dependencies. Then write tests for the normalized output shapes before implementing the P1 normalizations, so the tests serve as the specification.
