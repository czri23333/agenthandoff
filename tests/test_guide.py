"""The tool has to say what to do next, and both surfaces must say the same thing.

`handoff` with no arguments used to be a usage error; someone typing the name of
the tool is asking a question. And a first-run panel that stops at "resume"
teaches a workflow that predates the budget ladder and the lease - which is how
documentation becomes wrong without anyone editing it.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_handoff import cli

WEB = Path(__file__).resolve().parent.parent / "web" / "src"


def test_bare_command_answers_the_question(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "handoff doctor" in out and "handoff capture" in out


def test_guide_covers_the_whole_loop(capsys):
    assert cli.main(["guide"]) == 0
    out = capsys.readouterr().out
    for command in ("doctor", "list", "capture", "resume", "watch", "publish"):
        assert f"handoff {command}" in out, f"the guide never mentions {command}"


def test_guide_never_leaves_an_empty_parenthesis(capsys):
    assert cli.main(["guide"]) == 0
    out = capsys.readouterr().out
    assert "()" not in out, "a store with no detail line rendered as `cli()`"


def test_cockpit_panel_and_cli_teach_the_same_steps():
    """The two surfaces must teach the same loop, step for step.

    Key-based rather than count-based: the panel labels its steps out of order
    (guideStepFind sits between 1 and 2), and a count check passed while a step
    was missing from one language.
    """
    i18n = (WEB / "i18n.ts").read_text(encoding="utf-8")
    panel = (WEB / "views" / "Dashboard.tsx").read_text(encoding="utf-8")
    shown = set(re.findall(r'"(guideStep\w*)"', panel))
    assert len(shown) == len(cli.GUIDE_STEPS), f"panel shows {len(shown)} of {len(cli.GUIDE_STEPS)}"
    for key in shown:
        assert i18n.count(f"{key}:") == 2, f"{key} is missing from one language"

