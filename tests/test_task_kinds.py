"""Every task kind a store can report has a chip label, or says itself.

`t()` falls back to the key it was given, so a `task_type` the dictionary does
not carry rendered as `kind_subagent_child` in the session list - which is what
318 zcode rows and, after Codex started reporting `thread_source`, 62 more rows
did. The vocabulary is the store's, so this gate cannot enumerate it from thin
air: it takes the literals the parsers write, the values the shipped fixtures
actually produce, and the values a real store was measured to report, and asks
the dictionary about each.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSERS = ROOT / "src" / "agent_handoff" / "parsers"
WEB = ROOT / "web" / "src"

# Kinds the list deliberately does not label: `interactive` is the ordinary
# conversation and `quest-task` has its own chip with its own hint.
UNLABELLED_OK = {"interactive", "quest-task"}


def _literals() -> set[str]:
    """`task_type = "x"`, and the two-value test Codex writes inline."""
    found: set[str] = set()
    for path in PARSERS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        found.update(re.findall(r'task_type\s*=\s*"([^"]+)"', text))
        for group in re.findall(r'thread_source in \(([^)]*)\)', text):
            found.update(re.findall(r'"([^"]+)"', group))
    return found


def _from_the_stores_we_measured() -> set[str]:
    """What the stores on the machine this was written on reported.

    Kept as a literal list because a test that needs a live store is not a test.
    Values: codex thread_source, zcode task_type, workbuddy kinds, qodercn task
    panels - measured with `list_sessions()` over every parser.
    """
    return {
        "subagent",
        "agent_created_thread",
        "subagent_child",
        "interactive",
        "quest-task",
        "playground",
        "background",
        "working",
        "craft",
        "design",
        "coding",
    }


def _kind_keys() -> list[str]:
    """Every `kind_*` key the dictionary mentions, once per mention."""
    text = (WEB / "i18n.ts").read_text(encoding="utf-8")
    return re.findall(r"^\s*(kind_[a-z_]+):", text, re.M)


def _dictionary() -> set[str]:
    """The keys that exist in *both* language blocks - one mention is a typo."""
    keys = _kind_keys()
    return {key for key in keys if keys.count(key) > 1}


def test_every_known_task_kind_has_a_label_in_both_languages():
    wanted = (_literals() | _from_the_stores_we_measured()) - UNLABELLED_OK
    labelled = _dictionary()
    missing = sorted(f"kind_{kind}" for kind in wanted if f"kind_{kind}" not in labelled)
    assert not missing, (
        f"these task kinds would render as a translation key in the session list: {missing}. "
        "Add them to web/src/i18n.ts, or to UNLABELLED_OK with a reason."
    )


def test_each_label_exists_in_both_languages():
    """One entry is a key, two entries are a translation."""
    text = (WEB / "i18n.ts").read_text(encoding="utf-8")
    for key in sorted(set(_kind_keys())):
        count = len(re.findall(rf"^\s*{key}:", text, re.M))
        assert count == 2, f"{key} appears {count} time(s): every label needs zh and en"


def test_the_list_falls_back_to_the_stores_own_word():
    """A kind nobody translated shows `subagent_child`, not `kind_subagent_child`."""
    dashboard = (WEB / "views" / "Dashboard.tsx").read_text(encoding="utf-8")
    assert 'const kindKey = `kind_${s.task_type ?? ""}`;' in dashboard, (
        "the chip must build the key as a value: hasKey narrows a value, and t() "
        "returns the key it was given when the dictionary has none"
    )
    assert "hasKey(kindKey) ? t(kindKey) : s.task_type" in dashboard, (
        "an untranslated kind must show the store's own word, not the key name"
    )
    i18n = (WEB / "i18n.ts").read_text(encoding="utf-8")
    assert "export function hasKey" in i18n
