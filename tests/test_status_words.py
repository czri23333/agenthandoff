"""The end-state vocabulary is one table, checked from both ends.

The cockpit renders a word from two different layers: what a parser proves about
how a turn ended (`Interruption.kind`) and what a cheap list probe forwards from
a store's own status column (`completed`, `working`, `idle`, `archived`,
`failed`). Until now the colour came from a chain of `kind === ...` tests in
`StatusTag`, which meant a store that started reporting a word nobody had
thought of was rendered in the error colour - the product presenting "I have not
heard of this" as "this went wrong". That is the same failure as defaulting an
unrecorded ending to `clean`, pointing the other way.

These tests are the closure: the table, both locales' labels and the backend's
declared word list must agree, and the fallback for an unknown word must never
be the error colour.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_handoff.model import END_STATE_WORDS, Interruption

WEB = Path(__file__).resolve().parents[1] / "web" / "src"
COMPONENTS = (WEB / "components.tsx").read_text(encoding="utf-8")
I18N = (WEB / "i18n.ts").read_text(encoding="utf-8")


def _tone_table() -> dict[str, str]:
    block = re.search(
        r"const STATUS_TONES: Record<string, string> = \{(.*?)\n\};", COMPONENTS, re.S
    )
    assert block, "STATUS_TONES gone from components.tsx - the colouring reverted to a chain"
    return dict(re.findall(r'^\s*(\w+): "([^"]+)",', block.group(1), re.M))


def _labels(locale: str) -> set[str]:
    block = re.search(rf"\n  {locale}: \{{(.*?)\n  \}},?\n", I18N, re.S)
    assert block, f"{locale} block not found in i18n.ts"
    return {m for m in re.findall(r"it_(\w+):", block.group(1))}


def test_the_colour_table_covers_every_word_the_backend_can_emit() -> None:
    tones = _tone_table()
    assert set(tones) == set(END_STATE_WORDS), (
        f"table is missing {sorted(set(END_STATE_WORDS) - set(tones))} "
        f"and has undeclared {sorted(set(tones) - set(END_STATE_WORDS))}"
    )


def test_every_word_has_a_label_in_both_locales() -> None:
    zh, en = _labels("zh"), _labels("en")
    assert set(END_STATE_WORDS) <= zh, sorted(set(END_STATE_WORDS) - zh)
    assert set(END_STATE_WORDS) <= en, sorted(set(END_STATE_WORDS) - en)
    # A label with no colour would be the same drift seen from the other side.
    assert zh == en, f"locales disagree: zh-only {sorted(zh - en)}, en-only {sorted(en - zh)}"


def test_an_unmodelled_word_never_borrows_the_error_colour() -> None:
    """A store inventing a state must not be rendered as a failed session."""
    tones = _tone_table()
    assert tones["unknown"] == "ah-faint", "`unknown` is absence of evidence, not a finding"
    assert '?? "ah-faint"' in COMPONENTS, "the fallback for an unlisted word is no longer neutral"
    assert '?? "ah-err"' not in COMPONENTS


def test_clean_is_a_claim_a_store_has_to_make_not_a_default() -> None:
    default = Interruption()
    assert default.kind == "unknown"
    assert default.detected is False
    # Proving it is still available - a store with an end marker says so.
    proven = Interruption(kind="clean", detail="task_complete carried no error")
    assert proven.kind == "clean"
    assert proven.detected is False  # a clean end is not an interruption either


def test_only_a_terminal_store_status_counts_as_an_ending() -> None:
    """The other half of Round 39: a recorded ending must not be hidden.

    Making `unknown` the default also silenced the two stores that *do* keep a
    status column, so their rows said nothing while their own list badge said
    `completed`. The mapping below is what reconnects them - and it is limited
    to terminal words, because `working` and `idle` describe a live job and
    `archived` describes the task board, none of which says how a turn ended.
    """
    from agent_handoff.parsers.jsonl_family import STORE_END_STATES, _CodebuddyHybridParser

    class Stub(_CodebuddyHybridParser):
        cli = "stub"

        def __init__(self, word: str | None) -> None:  # skip the filesystem
            self._word = word

        def _store_status_word(self, session_id: str) -> str | None:
            return self._word

    for word, kind in (("completed", "clean"), ("done", "clean"), ("failed", "error"),
                       ("error", "error")):
        s = Stub(word)
        assert s.peek_status("s") == kind, (word, s.peek_status("s"))
        got = s._proven_interruption("s")
        assert got is not None and got.kind == kind, (word, got)
    for word in ("working", "idle", "archived", "running", "", None):
        s = Stub(word)
        assert s.peek_status("s") is None, word
        assert s._proven_interruption("s") is None, word

    assert set(STORE_END_STATES.values()) <= set(END_STATE_WORDS)
    assert not {"working", "idle", "archived", "running", "pending"} & set(STORE_END_STATES)
