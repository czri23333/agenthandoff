"""The two readers with no fixture: check the claim they actually rest on.

`codebuddy-cn` and `qoder-ide` have no sanitized fixture and no live store on this
machine, so `handoff matrix` calls them *unverified* — and that is the correct label,
because a store this repo has never read proves nothing about a vendor's layout. What
is checkable is the weaker statement their docstrings make: they are subclasses of
dialects that *are* fixture-proven, so the same input must produce the same parse.
That is a dialect test, not store evidence; the distinction is the whole point of the
support matrix, so it is named here rather than blurred.

For `qoder-ide` the subclass is one step removed (`QoderIdeParser` extends the CN
class, which carries the fragment merge and the two SQLite overlays), which makes the
check more valuable, not less: it is the only thing standing behind "behaves
identically".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff.parsers.jsonl_family import (
    CodebuddyCnParser,
    CodebuddyParser,
    QodercnIdeParser,
    QoderIdeParser,
)

QUESTION = "why is the handoff bundle missing tool calls?"
ANSWER = "because the reader folds them into [工具] markers"

# (proven sibling, unverified edition, the sibling's store directory name)
PAIRS = [
    (CodebuddyParser, CodebuddyCnParser, ".codebuddy", ".codebuddycn"),
    (QodercnIdeParser, QoderIdeParser, ".qoder-cn", ".qoder"),
]


def _write_store(tmp_path: Path, dirname: str) -> Path:
    root = tmp_path / dirname / "projects" / "C--x"
    root.mkdir(parents=True)
    rows = [
        {"type": "runtime-config", "sessionId": "s1", "timestamp": 1},
        {
            "type": "user",
            "timestamp": "2026-09-01T10:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": QUESTION}]},
        },
        {
            "type": "assistant",
            "timestamp": "2026-09-01T10:00:05Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": ANSWER}]},
        },
    ]
    with open(root / "s1.jsonl", "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return root


@pytest.mark.parametrize("proven_cls,edition_cls,proven_dir,edition_dir", PAIRS)
def test_the_unverified_edition_parses_like_its_proven_sibling(
    tmp_path: Path, proven_cls, edition_cls, proven_dir: str, edition_dir: str
):
    proven = proven_cls(_write_store(tmp_path, proven_dir))
    edition = edition_cls(_write_store(tmp_path, edition_dir))

    proven_meta = next(m for m in proven.list_sessions() if m.session_id == "s1")
    edition_meta = next(m for m in edition.list_sessions() if m.session_id == "s1")

    assert edition_meta.title == proven_meta.title == QUESTION
    assert edition_meta.cli == edition_cls.cli
    assert edition_meta.cli != proven_meta.cli

    proven_raw = proven.load("s1")
    edition_raw = edition.load("s1")
    assert proven_raw is not None and edition_raw is not None
    assert [m.role for m in edition_raw.messages] == [m.role for m in proven_raw.messages]
    assert [m.text for m in edition_raw.messages] == [m.text for m in proven_raw.messages]
    assert QUESTION in {m.text for m in edition_raw.messages}
    assert ANSWER in {m.text for m in edition_raw.messages}
