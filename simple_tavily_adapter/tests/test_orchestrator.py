"""Unit tests for orchestrator prompt building and job finalization.

No Docker/hermes required — `_build_prompt` and `_finalize_success` are
pure/self-contained enough to exercise directly.
"""
from __future__ import annotations

import asyncio

from events import Event
from orchestrator import DirectResearchFallback, Job, JobStatus, Orchestrator, _build_prompt


def _make_orchestrator(tmp_path) -> Orchestrator:
    return Orchestrator(
        hermes_bin="hermes",
        skills=["searcharvester-deep-research"],
        jobs_dir=tmp_path,
        env={},
    )


def _make_job(tmp_path) -> Job:
    job = Job(id="job-1", query="test query", status=JobStatus.running, workspace_path=tmp_path)
    job._cond = asyncio.Condition()
    return job


class SearchResult:
    def __init__(self, *, url, title, content, raw_content=None):
        self.url = url
        self.title = title
        self.content = content
        self.raw_content = raw_content


# ---------- _build_prompt ----------

def test_build_prompt_includes_research_directive():
    prompt = _build_prompt("what is RAG", ["searcharvester-deep-research"])
    assert "what is RAG" in prompt
    assert "searcharvester-deep-research" in prompt
    assert "delegate_task" in prompt
    assert "FIRST MESSAGE" in prompt


def test_build_prompt_lists_all_skills():
    prompt = _build_prompt("q", ["skill-a", "skill-b"])
    assert "skill-a" in prompt
    assert "skill-b" in prompt


# ---------- _finalize_success ----------

async def test_finalize_completed_when_report_exists(tmp_path):
    orch = _make_orchestrator(tmp_path)
    job = _make_job(tmp_path)
    (tmp_path / "report.md").write_text("# Report\n\n[1] https://example.com\n")

    await orch._finalize_success(job)

    assert job.status == JobStatus.completed
    assert job.report.startswith("# Report")
    assert job.error is None


async def test_finalize_degraded_when_no_report_but_chat_text(tmp_path):
    orch = _make_orchestrator(tmp_path)
    job = _make_job(tmp_path)
    job.events.append(Event.now(
        job_id=job.id, agent_id="lead", type="message",
        payload={"text": "What would you like me to work on?"},
    ))

    await orch._finalize_success(job)

    assert job.status == JobStatus.degraded
    assert job.report == "What would you like me to work on?"
    assert "no tool calls observed" in job.error


async def test_finalize_uses_fallback_when_agent_prints_tool_json(tmp_path):
    class Fallback:
        def __init__(self):
            self.calls = []

        async def run(self, *, query, workspace_path, lead_text):
            self.calls.append((query, workspace_path, lead_text))
            return "# Report\n\nA sourced finding [1].\n\n## References\n[1] Source - https://example.com\n"

    fallback = Fallback()
    orch = Orchestrator(
        hermes_bin="hermes",
        skills=["searcharvester-deep-research"],
        jobs_dir=tmp_path,
        env={},
        research_fallback=fallback,
    )
    job = _make_job(tmp_path)
    job.events.append(Event.now(
        job_id=job.id, agent_id="lead", type="message",
        payload={"text": '{"name":"searcharvester-deep-research","arguments":{"query":"test query"}}'},
    ))

    await orch._finalize_success(job)

    assert job.status == JobStatus.completed
    assert job.report.startswith("# Report")
    assert job.error is None
    assert (tmp_path / "report.md").read_text() == job.report
    assert fallback.calls == [
        (
            "test query",
            tmp_path,
            '{"name":"searcharvester-deep-research","arguments":{"query":"test query"}}',
        )
    ]


async def test_direct_research_fallback_uses_search_extract_and_model(tmp_path):
    calls = []

    async def search_func(*, query, max_results, include_raw_content, engines, categories):
        calls.append(("search", query, max_results, include_raw_content, engines, categories))
        return [
            SearchResult(
                url="https://example.com/alpha",
                title="Alpha source",
                content="Alpha snippet",
            ),
            SearchResult(
                url="https://example.com/beta",
                title="Beta source",
                content="Beta snippet",
            ),
        ]

    async def extract_func(url):
        calls.append(("extract", url))
        return (f"Title for {url}", f"Detailed extracted content from {url}.")

    async def complete_func(messages):
        calls.append(("complete", messages))
        assert "https://example.com/alpha" in messages[-1]["content"]
        assert "fallback" not in messages[-1]["content"].lower()
        assert "tool-shaped" not in messages[-1]["content"].lower()
        return (
            "# Example report\n\n"
            "Alpha and beta are both relevant [1][2].\n\n"
            "## References\n"
            "[1] Alpha source - https://example.com/alpha\n"
            "[2] Beta source - https://example.com/beta\n"
        )

    fallback = DirectResearchFallback(
        search_func=search_func,
        extract_func=extract_func,
        complete_func=complete_func,
        max_results=2,
        max_extracts=2,
    )

    report = await fallback.run(
        query="research alpha beta",
        workspace_path=tmp_path,
        lead_text='{"name":"searcharvester-deep-research"}',
    )

    assert report.startswith("# Example report")
    assert "[1] Alpha source" in report
    assert (tmp_path / "report.md").read_text() == report
    assert [call[0] for call in calls] == ["search", "extract", "extract", "complete"]


async def test_direct_research_fallback_repairs_uncited_model_output_with_synthesis(tmp_path):
    async def search_func(*, query, max_results, include_raw_content, engines, categories):
        return [
            SearchResult(
                url="https://docs.docker.com/compose/",
                title="Docker Compose overview",
                content=(
                    "Docker Compose is a tool for defining and running "
                    "multi-container applications."
                ),
            ),
            SearchResult(
                url="https://docs.docker.com/reference/compose-file/",
                title="Compose file reference",
                content=(
                    "The Compose file is a YAML file defining services, "
                    "networks, volumes, configs and secrets."
                ),
            ),
        ]

    async def extract_func(url):
        if url.endswith("/compose/"):
            return (
                "Docker Compose overview",
                (
                    "Docker Compose is a tool for defining and running "
                    "multi-container applications. Compose simplifies the "
                    "control of your entire application stack."
                ),
            )
        return (
            "Compose file reference",
            (
                "The Compose file is a YAML file defining services, networks, "
                "volumes, configs and secrets."
            ),
        )

    async def complete_func(messages):
        return "Docker Compose lets you run app stacks from a YAML file."

    fallback = DirectResearchFallback(
        search_func=search_func,
        extract_func=extract_func,
        complete_func=complete_func,
        max_results=2,
        max_extracts=2,
    )

    report = await fallback.run(
        query=(
            "Research what Docker Compose is. Use one web source. "
            "Keep the final answer under 100 words."
        ),
        workspace_path=tmp_path,
        lead_text="",
    )

    assert "fallback model did not return inline citations" not in report
    assert "Docker Compose is a tool" in report
    assert "[1]" in report
    assert "https://docs.docker.com/compose/" in report
    assert "https://docs.docker.com/reference/compose-file/" not in report
    assert len(report.split()) <= 100


async def test_direct_research_fallback_prefers_official_definition_source(tmp_path):
    async def search_func(*, query, max_results, include_raw_content, engines, categories):
        return [
            SearchResult(
                url="https://spacelift.io/blog/docker-compose",
                title="Docker Compose - What is It, Example & Tutorial",
                content=(
                    "Environment variables are set to configure the MySQL "
                    "instance and supply credentials to the WordPress container."
                ),
            ),
            SearchResult(
                url="https://docs.docker.com/compose/",
                title="Docker Compose overview",
                content=(
                    "Docker Compose is a tool for defining and running "
                    "multi-container applications."
                ),
            ),
        ]

    async def extract_func(url):
        if "spacelift.io" in url:
            return (
                "Docker Compose - What is It, Example & Tutorial",
                (
                    "Environment variables are set to configure the MySQL "
                    "instance and supply credentials to the WordPress container. "
                    "This tutorial shows a WordPress example."
                ),
            )
        return (
            "Docker Compose overview",
            (
                "Docker Compose is a tool for defining and running "
                "multi-container applications. Compose lets you define app "
                "services in a YAML file and run them together."
            ),
        )

    async def complete_func(messages):
        return "Docker Compose helps run containers."

    fallback = DirectResearchFallback(
        search_func=search_func,
        extract_func=extract_func,
        complete_func=complete_func,
        max_results=2,
        max_extracts=2,
    )

    report = await fallback.run(
        query=(
            "Research what Docker Compose is. Use one web source. "
            "Keep the final answer under 100 words."
        ),
        workspace_path=tmp_path,
        lead_text="",
    )

    assert "Docker Compose is a tool" in report
    assert "[1]" in report
    assert "[2]" not in report
    assert "Environment variables are set" not in report
    assert "https://docs.docker.com/compose/" in report
    assert "https://spacelift.io/blog/docker-compose" not in report


async def test_finalize_degraded_notes_partial_tool_use(tmp_path):
    orch = _make_orchestrator(tmp_path)
    job = _make_job(tmp_path)
    job.events.append(Event.now(
        job_id=job.id, agent_id="lead", type="tool_call",
        payload={"title": "delegate task"},
    ))
    job.events.append(Event.now(
        job_id=job.id, agent_id="lead", type="message",
        payload={"text": "Here's a summary without a saved report."},
    ))

    await orch._finalize_success(job)

    assert job.status == JobStatus.degraded
    assert "no tool calls observed" not in job.error


async def test_finalize_failed_when_no_report_and_no_message(tmp_path):
    orch = _make_orchestrator(tmp_path)
    job = _make_job(tmp_path)

    await orch._finalize_success(job)

    assert job.status == JobStatus.failed
    assert job.report is None


# ---------- env passthrough for model selection ----------

def test_orchestrator_env_passthrough_is_generic(tmp_path):
    """Orchestrator just stores whatever env dict it's given — the actual
    HERMES_INFERENCE_MODEL passthrough logic lives in main._build_orchestrator
    (see tests/test_build_orchestrator.py), this only guards the constructor
    contract."""
    env = {"CUSTOM_BASE_URL": "http://backend.example/v1", "HERMES_INFERENCE_MODEL": "some-model"}
    orch = Orchestrator(
        hermes_bin="hermes", skills=[], jobs_dir=tmp_path, env=env,
    )
    assert orch._env == env
