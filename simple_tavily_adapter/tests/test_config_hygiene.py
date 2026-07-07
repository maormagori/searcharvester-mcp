"""Guards that the versioned Hermes config baked into the image stays
generic — no deployment-specific IPs, hosts, or secrets — and that the
research skills actually ship in the built image.

Reads `/app/hermes-data/...` / `/app/hermes_skills/...`, the paths the
Dockerfile COPYs these into (see simple_tavily_adapter/Dockerfile). These
only exist when running inside the built image (e.g. via
`docker compose exec tavily-adapter pytest`) — skipped otherwise.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_APP_ROOT = Path("/app")
_CONFIG_PATH = _APP_ROOT / "hermes-data" / "config.yaml"
_SOUL_PATH = _APP_ROOT / "hermes-data" / "SOUL.md"
_SKILLS_ROOT = _APP_ROOT / "hermes_skills"

_SAFE_IPS = {"0.0.0.0", "127.0.0.1", "255.255.255.255"}
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _require(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path} not present — not running inside the built image")
    return path.read_text(encoding="utf-8", errors="replace")


def test_config_yaml_ships_with_empty_base_url():
    text = _require(_CONFIG_PATH)
    assert 'base_url: ""' in text, (
        "hermes-data/config.yaml must ship with an empty base_url — the "
        "real endpoint comes from the CUSTOM_BASE_URL env var at runtime, "
        "never hardcoded in the tracked config"
    )


def test_config_yaml_has_no_embedded_ip_addresses():
    text = _require(_CONFIG_PATH)
    found = {ip for ip in _IPV4_RE.findall(text) if ip not in _SAFE_IPS}
    assert not found, f"config.yaml embeds IP address(es) that should come from env vars instead: {found}"


def test_soul_md_has_no_embedded_ip_addresses():
    text = _require(_SOUL_PATH)
    found = {ip for ip in _IPV4_RE.findall(text) if ip not in _SAFE_IPS}
    assert not found, f"SOUL.md embeds IP address(es): {found}"


def test_research_skills_are_bundled_in_image():
    if not _SKILLS_ROOT.exists():
        pytest.skip(f"{_SKILLS_ROOT} not present — not running inside the built image")
    expected = {
        "searcharvester-search",
        "searcharvester-extract",
        "searcharvester-deep-research",
    }
    present = {p.name for p in _SKILLS_ROOT.iterdir() if p.is_dir()}
    missing = expected - present
    assert not missing, f"skills missing from bundled hermes_skills/: {missing}"
    for name in expected:
        assert (_SKILLS_ROOT / name / "SKILL.md").exists(), f"{name}/SKILL.md missing"
