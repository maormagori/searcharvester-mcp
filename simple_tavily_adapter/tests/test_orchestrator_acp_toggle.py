"""acp_enabled=False must skip spawning `hermes acp` entirely."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from orchestrator import Job, JobStatus, Orchestrator


async def _wait_for_terminal(orch: Orchestrator, job_id: str, timeout: float = 1.0) -> Job:
    terminal = {
        JobStatus.completed, JobStatus.failed,
        JobStatus.timeout, JobStatus.cancelled, JobStatus.degraded,
    }
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        job = orch.get(job_id)
        assert job is not None
        if job.status in terminal:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached a terminal state")


async def test_acp_disabled_never_spawns_hermes_and_uses_fallback(tmp_path):
    fallback = AsyncMock()
    fallback.run = AsyncMock(return_value="# Report\n\nBody. [1]\n\n## References\n[1] example - https://example.com\n")

    orch = Orchestrator(
        hermes_bin="hermes-binary-that-does-not-exist",
        skills=[],
        jobs_dir=tmp_path,
        env={},
        research_fallback=fallback,
        acp_enabled=False,
    )

    job_id = await orch.spawn("what is RAG")
    job = await _wait_for_terminal(orch, job_id)

    assert job.status == JobStatus.completed
    assert job.report is not None and job.report.startswith("# Report")
    fallback.run.assert_awaited_once()

    # No ACP subprocess was ever touched.
    assert job._process is None
    assert not any(e.type == "tool_call" for e in job.events)


async def test_acp_disabled_and_fallback_fails_goes_to_failed_not_degraded(tmp_path):
    fallback = AsyncMock()
    fallback.run = AsyncMock(side_effect=RuntimeError("direct fallback found no extractable sources"))

    orch = Orchestrator(
        hermes_bin="hermes-binary-that-does-not-exist",
        skills=[],
        jobs_dir=tmp_path,
        env={},
        research_fallback=fallback,
        acp_enabled=False,
    )

    job_id = await orch.spawn("what is RAG")
    job = await _wait_for_terminal(orch, job_id)

    # Never degraded: degraded means "ACP replied with chat text but no
    # report", which can't happen when ACP never ran at all.
    assert job.status == JobStatus.failed
    assert job.report is None
