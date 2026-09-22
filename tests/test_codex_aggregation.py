"""One Codex session can span several rollout files; the reader must see one.

The store appends ``rollout-<ts>-<thread-id>.jsonl`` for the first run and
``rollout-<ts>-<thread-id>_<continuation>.jsonl`` for every resume, so a parser
that treats one file as one session shows turn one of eight and silently drops
the rest. Identity is the thread: ``payload.id`` when the header carries one,
the filename's UUID otherwise. ``payload.session_id`` is the ROOT session that a
sub-agent shares with its parent and must never merge two different threads.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_handoff.model import ts_to_iso
from agent_handoff.parsers.codex import CodexParser

SID = "019fac0f-0000-7000-8000-0000000000aa"
CONT = "019fac0b-6030-7393-a07e-9c2286efc0ac"
# The first file's *filename* carries another UUID entirely: only its header
# names the thread, and that alone has to resolve the session.
STRAY = "019fac00-0000-7000-8000-0000000000ff"
OTHER = "019fac11-1111-7111-8111-111111111111"

MTIME_FIRST = 1_780_000_100.0
MTIME_SECOND = 1_780_000_200.0
MTIME_OTHER = 1_780_000_300.0


def _write(path: Path, rows: list[dict], mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))
    os.utime(path, (mtime, mtime))


def _header(sid: str, at: str, root: str | None = None) -> dict:
    payload = {"id": sid, "session_id": root or sid, "timestamp": at, "cwd": "D:/demo"}
    return {"type": "session_meta", "payload": payload}


def _turn(role: str, text: str, at: str) -> dict:
    return {
        "type": "response_item",
        "timestamp": at,
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": "output_text", "text": text}],
        },
    }


def _tokens(at: str, per_request: int) -> dict:
    usage = {"input_tokens": per_request, "output_tokens": 7}
    return {
        "type": "event_msg",
        "timestamp": at,
        "payload": {
            "type": "token_count",
            "info": {"last_token_usage": usage, "total_token_usage": usage},
        },
    }


def _two_file_store(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    """Session SID on two rollout files, plus an unrelated one-file session."""
    root = tmp_path / "sessions"
    paths = {
        "first": root / f"rollout-2026-08-31T10-00-00-{STRAY}.jsonl",
        "second": root / f"rollout-2026-08-31T10-05-00-{SID}_{CONT}.jsonl",
        "other": root / f"rollout-2026-08-31T11-00-00-{OTHER}.jsonl",
    }
    _write(
        paths["first"],
        [
            _header(SID, "2026-08-31T10:00:00.000Z"),
            _turn("user", "first ask", "2026-08-31T10:00:01.000Z"),
            _turn("assistant", "first answer", "2026-08-31T10:00:02.000Z"),
            _tokens("2026-08-31T10:00:03.000Z", 111),
            {
                "type": "event_msg",
                "timestamp": "2026-08-31T10:00:04.000Z",
                "payload": {"type": "task_complete"},
            },
        ],
        MTIME_FIRST,
    )
    _write(
        paths["second"],
        [
            _header(SID, "2026-08-31T10:05:00.000Z"),
            _turn("user", "second ask", "2026-08-31T10:05:01.000Z"),
            _turn("assistant", "second answer", "2026-08-31T10:05:02.000Z"),
            _tokens("2026-08-31T10:05:03.000Z", 222),
        ],
        MTIME_SECOND,
    )
    _write(
        paths["other"],
        [
            _header(OTHER, "2026-08-31T11:00:00.000Z"),
            _turn("user", "other ask", "2026-08-31T11:00:01.000Z"),
            _turn("assistant", "other answer", "2026-08-31T11:00:02.000Z"),
        ],
        MTIME_OTHER,
    )
    return root, paths


def test_list_sessions_folds_a_multi_file_session_into_one_row(tmp_path):
    root, paths = _two_file_store(tmp_path)
    metas = CodexParser(root).list_sessions()

    assert len(metas) == 2
    assert sum(1 for m in metas if m.session_id == SID) == 1
    by_id = {m.session_id: m for m in metas}
    assert set(by_id) == {SID, OTHER}
    # oldest file where the thread began, newest file's mtime for last activity
    assert by_id[SID].source_path == str(paths["first"])
    assert by_id[SID].started_at == ts_to_iso("2026-08-31T10:00:00.000Z")
    assert by_id[SID].updated_at == ts_to_iso(int(MTIME_SECOND * 1000))
    assert by_id[OTHER].source_path == str(paths["other"])


def test_load_concatenates_both_files_in_timestamp_order(tmp_path):
    root, paths = _two_file_store(tmp_path)
    raw = CodexParser(root).load(SID)

    assert raw is not None
    assert [m.text for m in raw.messages] == [
        "first ask",
        "first answer",
        "second ask",
        "second answer",
    ]
    # the unrelated session is not pulled in
    assert "other ask" not in "".join(m.text for m in raw.messages)
    assert raw.meta.session_id == SID
    assert raw.meta.source_path == str(paths["first"])
    assert raw.meta.started_at == ts_to_iso("2026-08-31T10:00:00.000Z")
    assert raw.meta.updated_at == ts_to_iso(int(MTIME_SECOND * 1000))


def test_raw_archive_returns_one_entry_per_file_oldest_first(tmp_path):
    root, paths = _two_file_store(tmp_path)
    parser = CodexParser(root)
    entries = parser.raw_archive(SID)

    assert entries is not None
    assert [Path(e["path"]).name for e in entries] == [paths["first"].name, paths["second"].name]
    assert entries[0]["text"] == paths["first"].read_bytes().decode("utf-8")
    assert entries[1]["text"] == paths["second"].read_bytes().decode("utf-8")
    # one file per session stays one entry, and an unknown id stays absent
    assert len(parser.raw_archive(OTHER) or []) == 1
    assert parser.raw_archive("no-such-session") is None


def test_build_runs_once_over_the_merged_rows(tmp_path, monkeypatch):
    """One call to ``_build`` with every file's rows, not one call per file."""
    root, _paths = _two_file_store(tmp_path)
    parser = CodexParser(root)
    calls: list[int] = []
    original = CodexParser._build

    def spy(self, meta, rows):
        calls.append(len(rows))
        return original(self, meta, rows)

    monkeypatch.setattr(CodexParser, "_build", spy)
    raw = parser.load(SID)

    assert raw is not None
    assert len(calls) == 1
    assert calls[0] == 9  # 5 rows in the first file, 4 in the continuation
    assert [m.text for m in raw.messages][-1] == "second answer"


def test_last_request_tokens_are_the_newest_files_last_record(tmp_path):
    root, _paths = _two_file_store(tmp_path)
    parser = CodexParser(root)

    tokens = parser.last_request_tokens(SID)
    assert tokens["input_tokens"] == 222  # the continuation file's number
    assert parser.last_request_tokens(OTHER) == {}
    # both files' requests are counted in the session total
    usage = parser.usage(SID)
    assert usage is not None and usage["totals"]["calls"] == 2


def test_a_file_is_matched_by_its_header_id_not_its_filename(tmp_path):
    """The first file is named after another UUID; only its header names SID."""
    root, paths = _two_file_store(tmp_path)
    parser = CodexParser(root)

    assert paths["first"].name.endswith(f"-{STRAY}.jsonl")
    assert STRAY != SID
    assert parser.load(SID) is not None
    assert len(parser.raw_archive(SID) or []) == 2
    assert sorted(m.session_id for m in parser.list_sessions()) == sorted([SID, OTHER])


def test_rows_are_ordered_by_record_timestamp_across_files(tmp_path):
    """Record timestamps order the merge; file order only breaks ties."""
    root = tmp_path / "sessions"
    _write(
        root / f"rollout-2026-08-31T13-00-00-{SID}.jsonl",
        [
            _header(SID, "2026-08-31T13:00:00.000Z"),
            _turn("user", "early", "2026-08-31T13:00:01.000Z"),
            _turn("assistant", "late", "2026-08-31T13:00:03.000Z"),
        ],
        MTIME_FIRST,
    )
    _write(
        root / f"rollout-2026-08-31T13-00-02-{SID}_{CONT}.jsonl",
        [
            _header(SID, "2026-08-31T13:00:02.000Z"),
            _turn("assistant", "between", "2026-08-31T13:00:02.000Z"),
        ],
        MTIME_SECOND,
    )
    raw = CodexParser(root).load(SID)

    assert raw is not None
    assert [m.text for m in raw.messages] == ["early", "between", "late"]


def test_peek_status_is_clean_when_any_file_completed(tmp_path):
    root, _paths = _two_file_store(tmp_path)
    parser = CodexParser(root)

    # task_complete sits in the oldest file; the newest file never saw one
    assert parser.peek_status(SID) == "clean"
    assert parser.peek_status(OTHER) is None


def test_files_sharing_a_root_session_are_not_merged(tmp_path):
    """A sub-agent keeps its parent's ``session_id``; that ROOT must not group."""
    root = tmp_path / "sessions"
    parent = "019fac22-2222-7222-8222-222222222222"
    child = "019fac33-3333-7333-8333-333333333333"
    _write(
        root / f"rollout-2026-08-31T12-00-00-{parent}.jsonl",
        [
            _header(parent, "2026-08-31T12:00:00.000Z"),
            _turn("user", "parent ask", "2026-08-31T12:00:01.000Z"),
            _turn("assistant", "parent answer", "2026-08-31T12:00:02.000Z"),
        ],
        MTIME_FIRST,
    )
    _write(
        root / f"rollout-2026-08-31T12-00-05-{child}.jsonl",
        [
            _header(child, "2026-08-31T12:00:05.000Z", root=parent),
            _turn("user", "child ask", "2026-08-31T12:00:06.000Z"),
            _turn("assistant", "child answer", "2026-08-31T12:00:07.000Z"),
        ],
        MTIME_SECOND,
    )
    parser = CodexParser(root)

    assert sorted(m.session_id for m in parser.list_sessions()) == sorted([parent, child])
    parent_raw = parser.load(parent)
    child_raw = parser.load(child)
    assert parent_raw is not None and child_raw is not None
    assert [m.text for m in parent_raw.messages] == ["parent ask", "parent answer"]
    assert [m.text for m in child_raw.messages] == ["child ask", "child answer"]


def test_the_filename_names_the_thread_when_the_header_has_no_id(tmp_path):
    """Older headers wrote no ``id``; the filename's UUID is the fallback, and
    the header's ``session_id`` (the ROOT) never names a thread on its own."""
    root = tmp_path / "sessions"
    _write(
        root / f"rollout-2026-08-31T09-00-00-{OTHER}.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "session_id": SID,
                    "timestamp": "2026-08-31T09:00:00.000Z",
                    "cwd": "D:/demo",
                },
            },
            _turn("user", "orphan ask", "2026-08-31T09:00:01.000Z"),
        ],
        MTIME_FIRST,
    )
    parser = CodexParser(root)

    assert [m.session_id for m in parser.list_sessions()] == [OTHER]
    raw = parser.load(OTHER)
    assert raw is not None
    assert [m.text for m in raw.messages] == ["orphan ask"]
    assert parser.load(SID) is None

def test_a_rebuild_derives_the_rollout_list_once_per_file_list(tmp_path):
    """Filtering rollouts per session must not re-derive the rollout list.

    `_session_files` walks every rollout to pick one thread's, and the list
    endpoint calls it once per session: measured on this machine's codex store
    (110 files, 103 sessions) that was 207 derivations of the same list and
    **45,540 of the 65,746 `os.stat` calls in one rebuild of all twenty
    stores** (spec Round 52). The memo is keyed by the file list it came from,
    so a rollout that appears, vanishes or is renamed still re-derives; this
    checks both halves -- the answer cannot move, and the cost must not scale
    with sessions.
    """
    threads = [SID, "019fac11-2222-7222-8222-222222222222", OTHER]
    paths = []
    for i, sid in enumerate(threads):
        for part in (0, 1):
            path = tmp_path / "sessions" / f"rollout-2026-08-0{i}T00-0{part}-{sid[-4:]}.jsonl"
            _write(
                path,
                [
                    _header(f"{sid}-{part}" if part else sid, ts_to_iso(1_780_000_000.0 + part)),
                    _turn("user", f"ask {i}-{part}", ts_to_iso(1_780_000_050.0 + part)),
                    _turn("assistant", "ok", ts_to_iso(1_780_000_060.0 + part)),
                ],
                1_780_000_100.0 + 100 * i + part,
            )
            paths.append(path)
    store = tmp_path / "sessions"
    files = {str(p) for p in paths}

    real_stat = Path.stat
    asked = {"n": 0}

    def counted(self, *a, **kw):
        if str(self) in files:
            asked["n"] += 1
        return real_stat(self, *a, **kw)

    orig_rollouts = CodexParser._rollouts
    Path.stat = counted
    try:
        def rebuild(parser_factory):
            """What `_build_session_roots` does per store: list, then ask every
            row its two questions -- and it is those probes that re-enter
            `_session_files`, not the listing."""
            asked["n"] = 0
            pr = parser_factory()
            rows = sorted((m.session_id, m.title, m.updated_at) for m in pr.list_sessions())
            for m in rows:
                pr.peek_status(m[0])
                pr.peek_needs_reply(m[0])
            return rows, asked["n"]

        # Arm 1: the memo as shipped.
        rows_memo, with_memo = rebuild(lambda: CodexParser(store))

        # Arm 2: the same code, told to pretend the store moved every time.
        def unmemorised(self):
            self._rollout_cache = None
            return orig_rollouts(self)

        CodexParser._rollouts = unmemorised
        rows_unmemo, without_memo = rebuild(lambda: CodexParser(store))
        CodexParser._rollouts = orig_rollouts

        assert rows_memo, "nothing listed, so the equality below is vacuous"
        assert rows_memo == rows_unmemo, "the memo changed the answer"
        assert without_memo > with_memo * 2, (
            f"{with_memo} stat calls with the memo against {without_memo} without it: "
            "the rollout list is still being re-derived per session"
        )
        # Cost tracks the files, not files x sessions.
        assert with_memo <= 4 * len(files), f"{with_memo} stats for {len(files)} rollout files"
        # And the cost must track the files, not files x sessions.
        assert with_memo <= 4 * len(files), f"{with_memo} stats for {len(files)} files"

        # The key has to be the file *set*, not the instance: a new rollout in
        # the same instance must be seen without any help.
        late = store / "rollout-2026-08-09T00-00-late.jsonl"
        _write(
            late,
            [
                _header("019fac11-9999-7999-8999-999999999999", ts_to_iso(1_780_000_900.0)),
                _turn("user", "brand new ask", ts_to_iso(1_780_000_910.0)),
                _turn("assistant", "ok", ts_to_iso(1_780_000_920.0)),
            ],
            1_780_000_999.0,
        )
        grown = CodexParser(store)
        grown.list_sessions()  # fills the memo
        rows_after = sorted((m.session_id, m.title) for m in grown.list_sessions())
        assert len(rows_after) == len(rows_memo) + 1, (
            "a rollout added after the memo reuses stale rows"
        )
    finally:
        Path.stat = real_stat
        CodexParser._rollouts = orig_rollouts
