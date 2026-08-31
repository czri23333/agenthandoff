"""Per-request pressure versus cumulative spend, on Codex rollouts.

The bug this replaces: `token_count` carries both numbers, the parser kept only
the cumulative one, and everything downstream read it as context fill - a session
that had spent 1.2B tokens in total against a ~1M window was reported as
`context_exceeded` (and every long session is like that). A usage table wants the
sum; pressure and end-state want the last call. These tests keep them apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff.parsers.codex import CodexParser

SID = "019fac0f-0000-7000-8000-0000000000aa"


def _rollout(tmp_path: Path, records: list[dict]) -> Path:
    root = tmp_path / "sessions" / "2026" / "08" / "31"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rollout-2026-08-31T10-00-00-{SID}.jsonl"
    lines = [json.dumps(row) for row in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path / "sessions"


def _records(window: int, calls: list[tuple[int, int]]) -> list[dict]:
    """`calls` is (this request's input tokens, cumulative input tokens)."""
    rows: list[dict] = [
        {
            "type": "session_meta",
            "payload": {
                "id": SID,
                "timestamp": "2026-08-31T10:00:00.000Z",
                "cwd": "D:/demo",
                "originator": "codex_cli_rs",
                "cli_version": "0.60.1",
                "source": "cli",
                "model_provider": "openai",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "started_at": 1780000000,
                "model_context_window": window,
            },
        },
    ]
    for index, (per_call, total) in enumerate(calls):
        rows.append(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": per_call,
                            "output_tokens": 500,
                            "cached_input_tokens": per_call // 2,
                            "total_tokens": per_call + 500,
                        },
                        "total_token_usage": {
                            "input_tokens": total,
                            "output_tokens": 500 * (index + 1),
                            "total_tokens": total + 500 * (index + 1),
                        },
                        "model_context_window": window,
                    },
                },
            }
        )
    rows.append({"type": "event_msg", "payload": {"type": "task_complete"}})
    return rows


@pytest.fixture
def long_session_under_pressure(tmp_path):
    """1.4M tokens spent in total; the last request fit in 140k of a 996k window."""
    root = _rollout(
        tmp_path,
        _records(996_000, [(16_688, 16_688), (79_997, 96_685), (138_122, 354_947)]),
    )
    return CodexParser(root)


def test_pressure_reads_the_last_request(long_session_under_pressure):
    parser = long_session_under_pressure
    raw = parser.load(SID)
    assert raw is not None
    assert parser.last_request_tokens(SID)["input_tokens"] == 138_122


def test_a_long_session_is_not_context_exceeded(long_session_under_pressure):
    raw = long_session_under_pressure.load(SID)
    kind = raw.interruption.kind if raw.interruption else "clean"
    assert kind != "context_exceeded", "cumulative spend was read as a full window"


def test_usage_reports_the_cumulative_run_with_call_count(long_session_under_pressure):
    usage = long_session_under_pressure.usage(SID)
    assert usage is not None
    assert usage["totals"]["tokens_in"] == 354_947
    assert usage["totals"]["calls"] == 3


def test_a_genuinely_full_window_is_still_detected(tmp_path):
    root = _rollout(tmp_path, _records(200_000, [(50_000, 50_000), (196_000, 246_000)]))
    parser = CodexParser(root)
    raw = parser.load(SID)
    assert raw is not None and raw.interruption is not None
    assert raw.interruption.kind == "context_exceeded"
    assert "196" in raw.interruption.detail or "200" in raw.interruption.detail


def test_no_token_records_means_no_claim(tmp_path):
    root = _rollout(tmp_path, _records(0, []))
    parser = CodexParser(root)
    assert parser.usage(SID) is None
    assert parser.last_request_tokens(SID) == {}
