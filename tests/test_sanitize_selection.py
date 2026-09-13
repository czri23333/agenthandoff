from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "sanitize_fixtures", REPO / "scripts" / "sanitize_fixtures.py"
)
assert _spec and _spec.loader
sanitize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sanitize)


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_codex_selects_rollout_files_by_their_first_uuid(tmp_path: Path) -> None:
    base = tmp_path / "codex"
    date = base / "sessions" / "2026" / "09" / "12"
    sid = "aaaaaaaa-1111-4111-8111-111111111111"
    other = "bbbbbbbb-2222-4222-8222-222222222222"
    _write(date / f"rollout-2026-09-12T10-00-00-{sid}.jsonl", 40)
    _write(date / f"rollout-2026-09-12T10-01-00-{sid}_continuation.jsonl", 30)
    _write(date / f"rollout-2026-09-12T10-02-00-{other}.jsonl", 20)
    _write(date / "unrelated.jsonl", 10)
    _write(base / "session_index.jsonl", 5)

    kept, dropped = sanitize.select_files("codex", base, base / "sessions", [sid])

    assert {p.relative_to(base).as_posix() for p in kept} == {
        "session_index.jsonl",
        f"sessions/2026/09/12/rollout-2026-09-12T10-00-00-{sid}.jsonl",
        f"sessions/2026/09/12/rollout-2026-09-12T10-01-00-{sid}_continuation.jsonl",
    }
    assert dropped == []
    assert len(kept) == len(set(kept))


def test_codex_selection_does_not_copy_other_date_directory_files(tmp_path: Path) -> None:
    base = tmp_path / "codex"
    date = base / "sessions" / "2026" / "09" / "12"
    sid = "aaaaaaaa-1111-4111-8111-111111111111"
    other = "bbbbbbbb-2222-4222-8222-222222222222"
    _write(date / f"rollout-2026-09-12T10-00-00-{sid}.jsonl", 10)
    _write(date / f"rollout-2026-09-12T10-01-00-{other}.jsonl", 10)
    _write(date / "unrelated.jsonl", 10)
    _write(base / "session_index.jsonl", 3)

    kept, _ = sanitize.select_files("codex", base, base / "sessions", [sid])

    assert {p.name for p in kept} == {
        "session_index.jsonl",
        f"rollout-2026-09-12T10-00-00-{sid}.jsonl",
    }


def test_codex_selection_enforces_the_cli_byte_cap_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "codex"
    date = base / "sessions" / "2026" / "09" / "12"
    sid = "aaaaaaaa-1111-4111-8111-111111111111"
    _write(date / f"rollout-2026-09-12T10-00-00-{sid}.jsonl", 4)
    _write(date / f"rollout-2026-09-12T10-01-00-{sid}_continuation.jsonl", 4)
    _write(base / "session_index.jsonl", 2)
    monkeypatch.setattr(sanitize, "MAX_CLI_BYTES", 6)

    kept, dropped = sanitize.select_files("codex", base, base / "sessions", [sid])

    assert [p.relative_to(base).as_posix() for p in kept] == [
        "session_index.jsonl",
        f"sessions/2026/09/12/rollout-2026-09-12T10-00-00-{sid}.jsonl",
    ]
    assert [p.relative_to(base).as_posix() for p in dropped] == [
        f"sessions/2026/09/12/rollout-2026-09-12T10-01-00-{sid}_continuation.jsonl"
    ]


def test_kimi_still_picks_up_its_session_directory_siblings(tmp_path: Path) -> None:
    base = tmp_path / "kimi-sessions"
    sid = "session-" + "c" * 24
    session_dir = base / "wd_scope-aaaaaaaaaa" / sid
    _write(session_dir / "state.json", 5)
    _write(session_dir / "agents" / "main" / "wire.jsonl", 6)
    _write(base / "wd_scope-bbbbbbbbbb" / "unrelated" / "state.json", 7)

    kept, dropped = sanitize.select_files("kimi", base, base, [sid])

    assert {p.relative_to(base).as_posix() for p in kept} == {
        f"wd_scope-aaaaaaaaaa/{sid}/agents/main/wire.jsonl",
        f"wd_scope-aaaaaaaaaa/{sid}/state.json",
    }
    assert dropped == []


def test_single_file_base_is_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "agents.db"
    _write(db, 30)
    kept, dropped = sanitize.select_files("cherrystudio", db, db, ["whatever"])
    assert kept == [db]
    assert dropped == []