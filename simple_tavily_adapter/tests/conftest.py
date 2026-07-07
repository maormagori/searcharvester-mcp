"""Shared pytest setup.

`main.py` conditionally registers `searcharvester_research` based on
whether any LLM credential env var is present at import time
(`_llm_configured` in main.py). Tests must not depend on whatever the
ambient shell/CI happens to have configured — set harmless placeholders
here, at conftest module load time, which pytest always imports before
collecting test modules (so this runs before any test file's top-level
`import main`).
"""
from __future__ import annotations

import os

os.environ.setdefault("CUSTOM_BASE_URL", "http://test.invalid/v1")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JOBS_DIR", "/tmp/searcharvester-test-jobs")
