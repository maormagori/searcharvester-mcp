"""Tests for main._build_orchestrator's env/model passthrough.

Verifies deployment-specific values (model, provider, backend URL, keys)
only ever reach the Hermes subprocess via environment variables — never
hardcoded — and that HERMES_INFERENCE_MODEL round-trips so a deployment can
pick a model without editing the tracked hermes-data/config.yaml.
"""
from __future__ import annotations

import shutil

import pytest

import main as main_module


@pytest.fixture
def rebuild_orchestrator(monkeypatch, tmp_path):
    """Re-run main._build_orchestrator() with a controlled environment,
    pretending `hermes` is on PATH without needing the real binary.

    `_build_orchestrator` does `import shutil` locally, so patching the
    `shutil` module object here (same cached sys.modules entry) still takes
    effect inside that function.
    """
    monkeypatch.setattr(shutil, "which", lambda _bin: "/usr/local/bin/hermes")
    monkeypatch.setenv("JOBS_DIR", str(tmp_path / "jobs"))

    def _rebuild():
        return main_module._build_orchestrator()

    return _rebuild


def test_hermes_inference_model_passes_through(monkeypatch, rebuild_orchestrator):
    monkeypatch.setenv("CUSTOM_BASE_URL", "http://backend.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("HERMES_INFERENCE_MODEL", "gpt-oss:20b")

    orch = rebuild_orchestrator()

    assert orch is not None
    assert orch._env["HERMES_INFERENCE_MODEL"] == "gpt-oss:20b"
    assert orch._env["CUSTOM_BASE_URL"] == "http://backend.example/v1"


def test_hermes_inference_model_omitted_when_unset(monkeypatch, rebuild_orchestrator):
    monkeypatch.setenv("CUSTOM_BASE_URL", "http://backend.example/v1")
    monkeypatch.delenv("HERMES_INFERENCE_MODEL", raising=False)

    orch = rebuild_orchestrator()

    assert orch is not None
    assert "HERMES_INFERENCE_MODEL" not in orch._env


def test_only_known_env_keys_are_forwarded(monkeypatch, rebuild_orchestrator):
    """Guards against accidentally forwarding the whole process environment
    (which could leak unrelated secrets) into the Hermes subprocess env dict
    built here — the full os.environ is merged in separately at spawn time,
    this dict is only the extra allow-listed passthrough."""
    monkeypatch.setenv("CUSTOM_BASE_URL", "http://backend.example/v1")
    monkeypatch.setenv("SOME_UNRELATED_SECRET", "should-not-appear")

    orch = rebuild_orchestrator()

    assert orch is not None
    assert "SOME_UNRELATED_SECRET" not in orch._env
