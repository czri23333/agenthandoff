"""Tests for memory_export: the honesty contract is the feature."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_handoff import memory_export as me


def _write(path: Path, text: str, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    # codex: a real markdown store with bullets, an indented continuation,
    # and prose that classifies differently.
    _write(
        home / ".codex/AGENTS.md",
        (
            "# Rules\n"
            "- Always run tests before committing.\n"
            "  Especially the concurrency ones.\n"
            "- Never force-push to main.\n"
            "- Project webgal: voice pipeline must stay lossless.\n"
        ),
        mtime=1767225600.0,  # 2026-01-01 UTC
    )
    # zcode: config only — parsed, named, never dumped.
    _write(home / ".zcode/cli/config.json", '{"mcp": {"servers": {}}, "theme": "dark"}')
    # claude deliberately absent: the report must say missing, not empty.
    return home


def test_missing_store_is_reported_not_dropped(fake_home: Path) -> None:
    entries, reports = me.scan_sources(home=fake_home, project=None)
    by_path = {r.path: r for r in reports}
    assert any(r.cli == "claude" and r.status == "missing" for r in reports)
    assert not any(r.cli == "claude" and r.status == "read" for r in reports)
    assert "~/.codex/AGENTS.md" in by_path and by_path["~/.codex/AGENTS.md"].status == "read"


def test_entries_dates_and_merging(fake_home: Path) -> None:
    entries, _ = me.scan_sources(home=fake_home, project=None)
    bullets = [e for e in entries if e.source == "codex"]
    assert any(e.date == "2026-01-01" for e in bullets)
    # indented continuation merges into its parent bullet
    merged = [e for e in bullets if "concurrency" in e.text]
    assert len(merged) == 1
    assert "Always run tests before committing." in merged[0].text


def test_project_files_are_scanned(fake_home: Path, tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _write(proj / "AGENTS.md", "- Use uv, not pip, in this repo.\n")
    entries, reports = me.scan_sources(home=fake_home, project=proj)
    assert any(e.source == "project" and "uv" in e.text for e in entries)
    assert any(
        r.cli == "project" and r.path == "CLAUDE.md" and r.status == "missing" for r in reports
    )


def test_render_lists_all_five_sections_and_empty_note(fake_home: Path) -> None:
    text = me.export_markdown(home=fake_home, project=None)
    for section in me.CATEGORIES:
        assert f"## {section}" in text
    assert me.EMPTY_NOTES["en"] in text  # identity/career held nothing
    assert "## sources scanned" in text
    assert "## completeness" in text


def test_render_zh(fake_home: Path) -> None:
    text = me.export_markdown(home=fake_home, project=None, lang="zh")
    for heading in ("指令", "身份", "职业", "项目", "偏好"):
        assert f"## {heading}" in text
    assert me.EMPTY_NOTES["zh"] in text
    assert "## 扫描的来源" in text
    assert "## 完整性" in text
    # the entry content itself is never translated, only the scaffolding
    assert "Always run tests before committing." in text


def test_config_source_is_noted_not_dumped(fake_home: Path) -> None:
    _, reports = me.scan_sources(home=fake_home, project=None)
    zcode = next(r for r in reports if r.cli == "zcode")
    assert zcode.status == "config-noted"
    assert "dark" not in zcode.detail  # values never dumped
    assert "mcp" in zcode.detail and "theme" in zcode.detail  # top-level keys named


def test_empty_file_is_labelled(fake_home: Path) -> None:
    _write(fake_home / ".codex/AGENTS.md", "\n   \n")
    _, reports = me.scan_sources(home=fake_home, project=None)
    codex = next(r for r in reports if r.cli == "codex")
    assert codex.status == "read" and codex.entries == 0
    assert codex.detail == "file is empty"


def test_secret_scan_flags_but_never_echoes(fake_home: Path) -> None:
    key = "ghp_ABCDEF0123456789ABCDEF0123456789abcd"
    _write(fake_home / ".codex/AGENTS.md", f"- token: {key}\n")
    text = me.export_markdown(home=fake_home, project=None)
    assert "## secret scan" in text
    assert "vendor api key" in text
    # the entry itself carries the user's content (that is the point of an
    # export), but the FLAG must not create a second copy of the secret
    flag_lines = [line for line in text.splitlines() if "vendor api key" in line]
    assert flag_lines and all(key not in line for line in flag_lines)
    assert "content withheld" in text


def test_json_export_shape(fake_home: Path) -> None:
    payload = me.export_json(home=fake_home, project=None)
    assert set(payload) == {"entries", "reports", "secret_flags", "completeness"}
    assert payload["completeness"]["read"] == 1
    assert payload["completeness"]["total"] == len(payload["reports"])
    assert any(e["source"] == "codex" for e in payload["entries"])
    # entries are date-sorted; json keeps the same honesty as markdown
    dates = [e["date"] for e in payload["entries"]]
    assert dates == sorted(dates)


def test_oversized_file_is_skipped_not_read(fake_home: Path) -> None:
    big = fake_home / ".codex/AGENTS.md"
    big.write_bytes(b"x" * (me.MAX_FILE_BYTES + 1))
    _, reports = me.scan_sources(home=fake_home, project=None)
    codex = next(r for r in reports if r.cli == "codex")
    assert codex.status == "oversized" and codex.entries == 0


def test_entry_budgets() -> None:
    lines = "\n".join(f"- line {i} " + "y" * 6000 for i in range(me.MAX_ENTRIES_PER_FILE + 50))
    got = me.split_markdown_entries(lines)
    assert len(got) == me.MAX_ENTRIES_PER_FILE
    assert all(len(e) <= me.MAX_ENTRY_CHARS for e in got)


def test_classify_priority() -> None:
    assert me.classify("My name is Alice and I live in Osaka.") == "identity"
    assert me.classify("I work at Acme Corp as a compiler engineer.") == "career"
    assert me.classify("The webgal project keeps a lossless vault.") == "projects"
    assert me.classify("Always answer in Chinese.") == "instructions"
    assert me.classify("likes dark roast coffee") == "preferences"


def test_unknown_date_sorts_first() -> None:
    a = me.Entry("x", "p", "2026-01-02", "preferences", "b")
    b = me.Entry("x", "p", "unknown", "preferences", "a")
    ordered = me._sorted_entries([a, b])
    assert ordered[0].date == "unknown"


def test_known_clis_matches_sources() -> None:
    assert me.known_clis() == ["claude", "codex", "gemini", "kimi-code", "zcode"]


def test_cli_rejects_unknown_cli(capsys: pytest.CaptureFixture[str]) -> None:
    from agent_handoff.cli import main

    rc = main(["memory-export", "--cli", "bogus", "--no-project"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown cli" in err and "codex" in err  # the known list is offered


def test_cli_out_failure_is_a_message_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from agent_handoff.cli import main

    # Writing "to" an existing directory raises IsADirectoryError inside the
    # handler; the user must see one line, not a stack.
    rc = main(["memory-export", "--no-project", "--out", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert err.startswith("error: cannot write") and "Traceback" not in err
