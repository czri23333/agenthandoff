"""The JSONL family's cheap probes: what one listed row costs to answer.

`peek_needs_reply` runs once per row of the session list, on every poll, for every
store -- so both its answers and its footprint are under test here. The shapes it
shipped with are each pinned by a test, named after what the live stores showed
(spec Round 56): a turn just above the read window, a store whose listing never
filled the map the probe consulted, an entry that delegates its transcripts to
another parser and asks itself instead, and -- for a session split over files --
which of them the answer comes from, pinned from both directions.
"""

from __future__ import annotations

import json
from pathlib import Path

import agent_handoff.parsers.jsonl_family as jf
from agent_handoff.parsers.jsonl_family import CodebuddyParser, QodercnIdeParser


def _row(sid: str, role: str, minute: int, text: str) -> dict:
    return {
        "type": role,
        "sessionId": sid,
        "timestamp": f"2026-09-20T10:{minute:02d}:00Z",
        "cwd": "C:/w",
        "message": {"role": role, "content": text},
    }


def _blob(sid: str, kb: int, minute: int) -> dict:
    """A record with no dialogue in it, the size a real attachment row is."""
    return {
        "type": "attachment",
        "sessionId": sid,
        "timestamp": f"2026-09-20T10:{minute:02d}:00Z",
        "cwd": "C:/w",
        "data": {"payload": "x" * (kb * 1024)},
    }


def _write(store: Path, name: str, rows: list[dict]) -> Path:
    path = store / f"{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _qoder(tmp_path: Path, sessions: dict[str, list[dict]]) -> QodercnIdeParser:
    store = tmp_path / ".qoder-cn" / "projects" / "C--w"
    store.mkdir(parents=True)
    for name, rows in sessions.items():
        _write(store, name, rows)
    return QodercnIdeParser(tmp_path / ".qoder-cn")


def test_a_turn_deeper_than_the_old_window_is_still_answered(tmp_path, monkeypatch):
    """A qoder tail is 30-100 KB of non-dialogue, so the turn moved out of reach.

    This machine's ``qoder-ide`` store answered 1,350 of its 2,287 rows with the
    old window and answers 2,279 with this one: the refused rows had their newest
    turn on disk all along — attachments and history snapshots between 16 KB and
    EOF pushed it above what the probe read, and the column said "unknown" about a
    conversation that was waiting, or not waiting, in plain sight.
    """
    p = _qoder(
        tmp_path,
        {
            "ses-waiting": [
                _row("ses-waiting", "user", 1, "first ask"),
                _row("ses-waiting", "assistant", 2, "an answer"),
                _row("ses-waiting", "user", 3, "and then what?"),
                # The blobs belong to that last turn: attachments and history
                # snapshots written for it, so they carry its minute. Records
                # stamped *after* the newest turn are a different case and have
                # their own test below.
                *[_blob("ses-waiting", 12, 3) for i in range(4)],  # 48 KB below it
            ],
            "ses-answered": [
                _row("ses-answered", "user", 1, "another ask"),
                _row("ses-answered", "assistant", 2, "the reply"),
                *[_blob("ses-answered", 12, 2) for i in range(4)],
            ],
        },
    )
    p.list_sessions()
    assert p.peek_needs_reply("ses-waiting") is True, (
        "the turn that closes the conversation is 48 KB above EOF, and the column "
        "still says nothing"
    )
    assert p.peek_needs_reply("ses-answered") is False


def test_a_window_that_cannot_reach_the_turn_declines_rather_than_guesses(tmp_path):
    """The bound is the honest part of the fix.

    Widening far enough answers every row -- reading a whole transcript per row
    would, and that is ~156 MB and 13,000 rows per rebuild on this machine's
    stores, for a column the list polls every 30 s. So the probe reads a bounded
    window and says "unknown" past it: the one answer that cannot make a stalled
    session look finished.
    """
    p = _qoder(
        tmp_path,
        {
            "ses-buried": [
                _row("ses-buried", "user", 1, "a question far below the blobs"),
                *[_blob("ses-buried", 20, 2 + i) for i in range(20)],  # 400 KB
            ]
        },
    )
    p.list_sessions()
    assert p.peek_needs_reply("ses-buried") is None, (
        "a turn 400 KB above EOF was answered anyway -- the probe read past its "
        "window, or invented an answer to avoid saying unknown"
    )


def test_one_listed_row_costs_one_bounded_read(tmp_path, monkeypatch):
    """What the fix may not do is turn a per-row probe into a per-row file read.

    Recorded rather than asserted about internals another way: the sizes asked for
    and the number of files consulted, per row.
    """
    p = _qoder(
        tmp_path,
        {
            f"ses-{i}": [
                _row(f"ses-{i}", "user", 1, f"ask {i}"),
                *[_blob(f"ses-{i}", 12, 2 + j) for j in range(3)],
            ]
            for i in range(5)
        },
    )
    asked: list[tuple[str, int]] = []
    real = jf._tail_lines

    def spy(path, max_bytes):
        asked.append((path.name, max_bytes))
        return real(path, max_bytes)

    monkeypatch.setattr(jf, "_tail_lines", spy)
    p.list_sessions()
    for i in range(5):
        p.peek_needs_reply(f"ses-{i}")
    assert asked, "the probe answered without reading anything"
    assert all(size <= p._PROBE_BYTES for _name, size in asked), (
        f"a row was answered from more than {p._PROBE_BYTES // 1024} KB: {asked}"
    )
    per_row = len(asked) / 5
    assert per_row <= p._PROBE_FILES, (
        f"{per_row:.1f} files read per row, against a bound of {p._PROBE_FILES}"
    )


def test_a_store_that_appends_out_of_order_does_not_get_a_finished_answer(tmp_path):
    """When the file's own records disagree about which end is newest, say unknown.

    ``codebuddy`` writes a row near the top of a transcript with a timestamp newer
    than the rows at EOF, so "read the end" is not "read the last word" -- and the
    row that hid one of this machine's conversations sat above the window. The
    listing dates every row from those records, so a date newer than the turn the
    probe found is the signal.

    The guard runs on the "not waiting" answer only. An ``unknown`` beside a
    conversation that is waiting costs a highlight; ``answered`` beside one that
    is waiting hides the work the column exists to surface.
    """
    late = {
        "type": "assistant",
        "sessionId": "ses-out-of-order",
        "timestamp": "2026-09-22T22:00:00Z",  # newer than anything at EOF
        "cwd": "C:/w",
        "message": {"role": "assistant", "content": "a record written early, stamped late"},
    }
    waiting = {
        "type": "user",
        "sessionId": "ses-still-waiting",
        "timestamp": "2026-09-22T22:00:00Z",
        "cwd": "C:/w",
        "message": {"role": "user", "content": "same shape, but this one ends on me"},
    }
    p = _qoder(
        tmp_path,
        {
            "ses-out-of-order": [
                late,
                _row("ses-out-of-order", "user", 1, "asked at ten"),
                _row("ses-out-of-order", "assistant", 2, "answered at ten"),
            ],
            "ses-still-waiting": [
                waiting,
                _row("ses-still-waiting", "user", 1, "asked at ten"),
            ],
        },
    )
    p.list_sessions()
    assert p.peek_needs_reply("ses-out-of-order") is None, (
        "the listing dates this session after the turn the probe found, so the "
        "probe answered 'finished' about a file whose newest content it did not see"
    )
    assert p.peek_needs_reply("ses-still-waiting") is True, (
        "a waiting row was silenced by the same guard: the cost of the guard is "
        "an absent highlight, never a hidden conversation"
    )


def test_a_store_that_lists_by_walking_its_store_still_answers(tmp_path):
    """Codebuddy and WorkBuddy list by walking, and the probe could not see it.

    Those listings build their rows from their own walk and never filled
    ``_index``, the map the probe read -- so all 156 ``workbuddy`` rows and 16
    ``codebuddy`` rows on this machine answered "unknown" without reading a byte,
    while the listing had opened the very file a moment earlier. The map the
    listing fills for the probe is deliberately not ``_index``: that one is what
    ``load()`` merges, so writing a row's sub-agent transcripts into it would
    change a transcript to answer a column.
    """
    store = tmp_path / ".codebuddy" / "projects" / "C--p"
    store.mkdir(parents=True)
    _write(
        store,
        "ses-flat",
        [
            _row("ses-flat", "user", 1, "does this store answer?"),
            _row("ses-flat", "assistant", 2, "it does"),
            _row("ses-flat", "user", 3, "one more thing"),
        ],
    )
    p = CodebuddyParser(tmp_path / ".codebuddy")
    listed = {m.session_id for m in p.list_sessions()}
    assert "ses-flat" in listed, f"the fixture row was never listed: {sorted(listed)}"
    assert p.peek_needs_reply("ses-flat") is True, (
        "a listing that walked the store left its own row unanswerable"
    )


def test_a_split_session_is_answered_from_its_own_transcript_not_its_subagents(
    tmp_path,
):
    """Companions first would answer nine live sessions backwards.

    ``qoder-ide`` splits a session over the main transcript plus one `agent-*`
    file per sub-agent, and a sub-agent transcript ends on the task it was given,
    not on the last word of the conversation. Measured across this machine's 172
    split rows: reading the companions before the canonical file answered 9 of
    them the opposite way from what their own detail page shows.
    """
    store = tmp_path / ".qoder-cn" / "projects" / "C--w"
    sid = "7c0d1111-2222-3333-4444-555566667777"
    companion = "agent-ageneral-purpose-9ae1f00d"
    store.mkdir(parents=True)
    _write(
        store,
        sid,
        [
            _row(sid, "user", 1, "do the thing"),
            _row(sid, "assistant", 2, "the thing is done"),
        ],
    )
    # Bigger than the canonical file, so the old size-based tie-break in
    # `_group_files` ranks it first and any drift back to "largest file wins"
    # is caught here rather than in the listing.
    _write(
        store,
        companion,
        [
            _row(sid, "assistant", 3, "delegating"),
            _row(sid, "user", 4, "sub-agent: now count the rows"),
            *[_blob(sid, 12, 5 + i) for i in range(3)],
        ],
    )
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    listed = {m.session_id for m in p.list_sessions()}
    assert sid in listed, f"the split fixture was never listed: {sorted(listed)}"
    assert p.peek_needs_reply(sid) is False, (
        "the column read a sub-agent transcript and reported the conversation as "
        "waiting, while its detail page ends on the assistant's reply"
    )
    # The order is what decides, not the fixtures: read alone, the companion
    # says the conversation is waiting.
    assert jf._tail_lines(store / f"{companion}.jsonl", p._PROBE_BYTES), "empty companion"


def test_a_session_still_answers_when_the_head_of_the_group_says_nothing(tmp_path):
    """The fallback half of the same order, so fixing one direction cannot break the other.

    A session continued into a newer file keeps its last words there; when the
    canonical transcript's window holds no turn -- it is not the newest file any
    more -- the probe has to move on rather than report "unknown".
    """
    store = tmp_path / ".qoder-cn" / "projects" / "C--w"
    sid = "ab12cd34-1111-2222-3333-444455556666"
    store.mkdir(parents=True)
    _write(
        store,
        sid,
        [
            _row(sid, "user", 1, "an old question"),
            _row(sid, "assistant", 2, "an old answer"),
            # The canonical file's tail is out of reach of the window: 300 KB of
            # non-dialogue rows sit above its last turn.
            *[_blob(sid, 20, 4 + i) for i in range(15)],
        ],
    )
    continued = _write(
        store,
        f"{sid}-continued",
        [
            _row(sid, "user", 30, "and one more thing"),
        ],
    )
    p = QodercnIdeParser(tmp_path / ".qoder-cn")
    p.list_sessions()
    assert p.peek_needs_reply(sid) is True, (
        "the canonical transcript's window held no turn and the probe stopped there "
        "instead of reading the newer file this session continued into"
    )
    # Same session, but the canonical tail is reachable: the head answers and the
    # companion is never consulted.
    (store / f"{sid}.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in [
                _row(sid, "user", 1, "an old question"),
                _row(sid, "assistant", 2, "an old answer"),
                _row(sid, "assistant", 3, "the last word"),
            ]
        ),
        encoding="utf-8",
    )
    continued.touch()
    p.list_sessions()
    assert p.peek_needs_reply(sid) is False, (
        "the canonical transcript said the conversation is finished, and a newer "
        "companion overrode it"
    )


def test_an_entry_that_delegates_its_transcripts_asks_the_owner(tmp_path):
    """The wake entries read the shared qoder store through another parser.

    Their rows' transcripts belong to that parser -- it holds the file index, the
    fragment merge and the tail probe -- so the answer has to be asked of it.
    Before that, a wake row was declined by the entry that listed it while its
    owner was reading the same file for the list next door.
    """
    from agent_handoff.parsers.qoderwake import QoderwakeParser

    class Shared:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def peek_needs_reply(self, session_id: str):
            self.seen.append(session_id)
            return True

    p = QoderwakeParser(tmp_path / ".qoderwake" / "data" / "store")
    shared = Shared()
    p._shared = shared
    assert p.peek_needs_reply("qs-1") is True
    assert shared.seen == ["qs-1"], "the entry answered a wake row without asking the store"

    p._shared = None
    assert p.peek_needs_reply("qs-1") is None, "no owner, but an answer anyway"


def test_a_row_is_answered_once_per_file_version_not_once_per_poll(tmp_path, monkeypatch):
    """The widened window may not turn every 30 s poll into a 144 MB re-read.

    64 KB across this machine's 2,491 family rows is that much per rebuild, so the
    answer is remembered against the version of the files it was read from and the
    date the listing carried -- the same invalidation rule as every other cache in
    the family. A rewrite has to bring the answer back to life: the test moves the
    transcript from "waiting" to "answered" and expects the next call to say so.
    """
    p = _qoder(
        tmp_path,
        {
            "ses-x": [
                _row("ses-x", "user", 1, "waiting for an answer"),
                _blob("ses-x", 12, 1),
            ]
        },
    )
    p.list_sessions()
    store = tmp_path / ".qoder-cn" / "projects" / "C--w"
    reads: list[str] = []
    real = jf._tail_lines

    def spy(path, max_bytes):
        reads.append(path.name)
        return real(path, max_bytes)

    monkeypatch.setattr(jf, "_tail_lines", spy)
    assert p.peek_needs_reply("ses-x") is True
    first = len(reads)
    assert first, "the probe answered without reading, so there is nothing to cache"

    # The next poll: a fresh listing, the same file versions.
    p.list_sessions()
    assert p.peek_needs_reply("ses-x") is True
    assert len(reads) == first, f"a poll re-read {len(reads) - first} files that had not changed"

    _write(
        store,
        "ses-x",
        [
            _row("ses-x", "user", 1, "waiting for an answer"),
            _blob("ses-x", 12, 1),
            _row("ses-x", "assistant", 2, "and here it is"),
        ],
    )
    p.list_sessions()
    assert p.peek_needs_reply("ses-x") is False, (
        "the transcript moved and the cached answer did not"
    )
    assert len(reads) > first, "the answer was re-derived without reading the new version"


def test_two_stores_sharing_a_session_id_do_not_share_an_answer(tmp_path):
    """The memo is keyed by store, because a session id is not unique across them.

    The qoder family already reads two stores for one conversation set, and a key
    of session id alone would let one store's answer answer the other's row.
    """
    waiting = _qoder(
        tmp_path / "a",
        {"ses-shared": [_row("ses-shared", "user", 1, "asked in store a")],
         "decoy": [_row("decoy", "assistant", 1, "keep the groups different")]},
    )
    answered = _qoder(
        tmp_path / "b",
        {
            "ses-shared": [
                _row("ses-shared", "user", 1, "asked in store b"),
                _row("ses-shared", "assistant", 2, "answered in store b"),
            ]
        },
    )
    waiting.list_sessions()
    answered.list_sessions()
    assert waiting.peek_needs_reply("ses-shared") is True
    assert answered.peek_needs_reply("ses-shared") is False, (
        "one store's answer was served for the other store's row"
    )
