"""The cockpit endpoint keeps the CLI's honesty contract: unknown clis are a
404 with the known list, and missing stores stay visible in the reports."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx", reason="fastapi TestClient needs httpx")

from agent_handoff.server.app import app  # noqa: E402

Client = pytest.importorskip("fastapi.testclient", reason="agenthandoff[server]").TestClient


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "AGENTS.md").write_text("- Always run the tests first.\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def test_memory_export_api_reports_missing_and_read(fake_home: Path) -> None:
    client = Client(app)
    r = client.get("/api/memory-export", params={"with_project": "false"})
    assert r.status_code == 200
    data = r.json()
    statuses = {(rep["cli"], rep["status"]) for rep in data["reports"]}
    assert ("codex", "read") in statuses
    assert ("claude", "missing") in statuses  # skipped, never silently dropped
    assert any(e["category"] and e["text"] for e in data["entries"])
    assert "## instructions" in data["markdown_en"]
    assert "## 指令" in data["markdown_zh"]
    assert data["completeness"]["read"] >= 1


def test_memory_export_api_rejects_unknown_cli(fake_home: Path) -> None:
    client = Client(app)
    r = client.get("/api/memory-export", params={"cli": "bogus"})
    assert r.status_code == 404
    assert "known" in r.json()["detail"]
