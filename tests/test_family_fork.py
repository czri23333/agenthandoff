"""The store's in-file fork record: what the transcript is allowed to claim.

A `resend-fork-notice` row carries no turn and no role - only the id of the
user turn the editor rewrote. Read wrong, it either lies about which copy is
live or marks a turn the record never named, so every case below fixes one way
the row can be misread.
"""

import json

from agent_handoff.parsers.jsonl_family import CodebuddyParser

SID = "fork001"


def _user(rid, text, ts):
    return {
        "type": "message",
        "sessionId": SID,
        "cwd": "D:/demo",
        "id": rid,
        "timestamp": ts,
        "role": "user",
        "content": [{"type": "input_text", "text": text}],
    }


def _assistant(rid, text, ts):
    return {
        "type": "message",
        "sessionId": SID,
        "cwd": "D:/demo",
        "id": rid,
        "timestamp": ts,
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def _notice(ts, edited=None):
    row = {
        "type": "resend-fork-notice",
        "timestamp": ts,
        "cwd": "D:/demo",
        "id": f"n{ts}",
    }
    if edited is not None:
        row["editedUserItemId"] = edited
    return row


def _load(tmp_path, rows):
    root = tmp_path / ".codebuddy" / "projects" / "p"
    root.mkdir(parents=True)
    (root / f"{SID}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    p = CodebuddyParser(tmp_path / ".codebuddy")
    raw = p.load(SID)
    assert raw is not None
    return raw


def test_a_fork_marks_both_turns_it_names(tmp_path):
    """The edited turn is the abandoned copy; the one below the record is live."""
    raw = _load(
        tmp_path,
        [
            _user("u1", "make the ledger work", 100),
            _assistant("a1", "done, it works now", 110),
            _notice(120, "u1"),
            _user("u2", "make the ledger work, and test it", 130),
            _assistant("a2", "tested", 140),
        ],
    )
    assert [(m.text, m.resent, m.superseded) for m in raw.messages] == [
        ("make the ledger work", False, True),
        ("done, it works now", False, False),
        ("make the ledger work, and test it", True, False),
        ("tested", False, False),
    ]
    # Read, not merely tolerated: the row must stop being an unread shape.
    assert not [n for n in raw.meta.notes if n.startswith("unhandled_row:resend-fork-notice")]


def test_a_record_naming_nothing_in_this_file_says_so(tmp_path):
    """A link whose target is absent is a fact, not a silently dropped row."""
    raw = _load(
        tmp_path,
        [
            _user("u1", "first ask", 100),
            _notice(120, "vanished0000"),
            _user("u2", "second ask", 130),
        ],
    )
    assert "fork_target_missing:1" in raw.meta.notes
    assert [m.superseded for m in raw.messages if m.role == "user"] == [False, False]
    # the re-sent end still resolves - the record does sit above u2
    assert [m.resent for m in raw.messages if m.role == "user"] == [False, True]


def test_a_re_send_claim_never_reaches_past_the_next_turn(tmp_path):
    """Marking a later turn would invent a fork the store did not record.

    If the copy the store wrote under the record never became a turn (noise,
    a mirrored duplicate), the claim is spent rather than carried onward.
    """
    raw = _load(
        tmp_path,
        [
            _user("u1", "ask one", 100),
            _notice(120, "u1"),
            _assistant("a1", "answer", 130),
            _user("u2", "ask two", 140),
        ],
    )
    assert [(m.text, m.resent) for m in raw.messages if m.role == "user"] == [
        ("ask one", False),
        ("ask two", False),
    ]
    # The named turn is still the abandoned copy - that link is by id, not position.
    assert [m.superseded for m in raw.messages if m.role == "user"] == [True, False]


def test_a_turn_can_be_a_re_send_and_later_edited_again(tmp_path):
    """Both ends hold of one turn, so neither fact may overwrite the other.

    Measured as the ordinary case: 63 of the 77 records on this machine's
    stores name a turn that is itself a re-send.
    """
    raw = _load(
        tmp_path,
        [
            _user("u1", "v1", 100),
            _notice(120, "u1"),
            _user("u2", "v2", 130),
            _notice(150, "u2"),
            _user("u3", "v3", 160),
        ],
    )
    assert [(m.text, m.resent, m.superseded) for m in raw.messages] == [
        ("v1", False, True),
        ("v2", True, True),
        ("v3", True, False),
    ]
    assert not [n for n in raw.meta.notes if n.startswith("fork_target_missing")]


def test_a_record_with_no_id_still_marks_the_copy_above_it(tmp_path):
    """Half the link is still the fact a reader needs: this turn replaced one."""
    raw = _load(
        tmp_path,
        [
            _user("u1", "ask", 100),
            _notice(120),
            _user("u2", "ask, rephrased", 130),
        ],
    )
    assert "fork_target_missing:1" in raw.meta.notes
    assert [(m.text, m.resent) for m in raw.messages if m.role == "user"] == [
        ("ask", False),
        ("ask, rephrased", True),
    ]


def test_the_sanitized_store_fixture_marks_the_same_shape():
    """The synthetic rows above must not be the only thing the reader proves.

    The fixture's session 178eaf06 holds 17 records, and the sanitizer that
    built it removed some rows, which is what makes this file the interesting
    case: 14 of the named turns survive and get marked, the 3 that do not are
    reported as missing rather than guessed at, and 2 records now sit above an
    assistant row — a re-send claim that cannot reach a user turn stops there
    instead of landing on the next real one. 15 of 17 marked, never 17 of 17.
    """
    import pytest

    from agent_handoff import fixtures
    from agent_handoff.parsers.jsonl_family import WorkbuddyParser

    if not fixtures.cli_dir("workbuddy").is_dir():
        pytest.skip("workbuddy fixture not shipped in this checkout")
    target = fixtures.root_for("workbuddy")
    assert target is not None
    p = WorkbuddyParser().with_root(target)
    raw = p.load("178eaf06-459d-beab-834c-986de5d899f1")
    assert raw is not None
    assert sum(1 for m in raw.messages if m.resent) == 15
    assert sum(1 for m in raw.messages if m.superseded) == 14
    assert "fork_target_missing:3" in raw.meta.notes
    assert not [n for n in raw.meta.notes if n.startswith("unhandled_row:resend-fork-notice")]
