"""Unit tests for orchestrator prompt building and job finalization.

No Docker/hermes required — `_build_prompt` and `_finalize_success` are
pure/self-contained enough to exercise directly.
"""
from __future__ import annotations

import asyncio

from events import Event
from orchestrator import Job, JobStatus, Orchestrator, _build_prompt


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
