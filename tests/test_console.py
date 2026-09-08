"""Output must survive the console the user actually has.

Measured here and on CI: `✓` (U+2713) is unencodable in gbk AND cp1252, so
printing the support matrix used to raise UnicodeEncodeError before it could
report anything - a tool that dies while stating its evidence is the worst
possible failure for this project. The console rendering path is ASCII-only, and
these tests assert that property directly rather than trusting the intent.
"""

from __future__ import annotations

import io
import sys

import pytest

from agent_handoff import cli, matrix

CONSOLE_CODECS = ("gbk", "cp1252")  # zh-CN Windows, Western Windows


@pytest.fixture
def rows():
    return matrix.build_rows()


def test_console_table_encodes_on_windows_codecs(rows):
    table = matrix.render_markdown("en", rows, ascii_cell=True)
    for codec in CONSOLE_CODECS:
        table.encode(codec)  # raises before the fix


def test_readme_table_keeps_the_glyphs(rows):
    """GitHub renders the emoji; only the terminal path is plain ASCII."""
    assert "✅" in matrix.render_markdown("en", rows)


def test_a_chinese_console_still_gets_a_report(monkeypatch):
    """An unencodable character degrades to `?`; it never kills the run."""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    cli._survive_console_codepage()
    print("proven: ✓")
    stream.flush()
    assert b"proven: ?" in buffer.getvalue()


def test_matrix_command_writes_a_table_to_a_gbk_console(monkeypatch):
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    assert cli.main(["matrix"]) == 0
    stream.flush()
    assert "stable (fixture-proven)" in buffer.getvalue().decode("gbk")


def test_list_unknown_cli_suggests_closest_and_doctor(capsys):
    """A typo'd --cli names candidates and the next command, not just an error."""
    assert cli.main(["list", "--cli", "qoder"]) == 1
    err = capsys.readouterr().err
    assert "has no available store" in err
    assert "did you mean" in err and "qoderwork" in err
    assert "handoff doctor" in err


def test_resolve_unknown_cli_suggests_closest():
    from agent_handoff import parsers as P

    with pytest.raises(FileNotFoundError, match="did you mean"):
        P.resolve_session("latest", cli="qoder")


def test_resolve_unknown_session_points_at_next_steps(monkeypatch):
    """A dead session id tells the user where to look next."""
    from agent_handoff import parsers as P

    monkeypatch.setattr(P, "all_parsers", lambda: [])
    with pytest.raises(FileNotFoundError, match="handoff list -n 5"):
        P.resolve_session("nosuchsession123")
    with pytest.raises(FileNotFoundError, match="handoff search"):
        P.resolve_session("nosuchsession123")
