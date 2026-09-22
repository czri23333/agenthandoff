#!/usr/bin/env python
"""Audit the cheap list-page probes against each parser's own full parse.

Run it: `python scripts/probe_audit.py [--per-store 40]`

`peek_status` and `peek_needs_reply` answer for every row of the session list,
so they run per session and must stay cheap - which is also how they can drift
away from what the detail page says about the same session. This walks the
stores on this machine and reports the two ways each of them can be wrong:

  lying    the probe answered, and the full parse disagrees.
  silent   the full parse names something the probe could have read.

Two columns are printed per store, `status=` and `needs=`, because the two
probes read different things and a green one says nothing about the other: a
gate that checks only the badge it was written for is how the column next to it
starts shipping answers nobody audited.

A null `peek_status` is not a defect by itself: `parsers/base.py` says a null
means unknown and is never to be read as clean, and for most of the stores here
the log genuinely records no ending (limitations item 31). Same for a null
"needs input": a conversation whose last turn is out of the probe's window is
unknown, not finished (limitations item 39). `lying` is the one that ships a
wrong badge to a user.
"""
from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_handoff.parsers.base import read_jsonl  # noqa: E402
from agent_handoff.parsers.jsonl_family import _iso  # noqa: E402
from agent_handoff.server.app import all_parsers  # noqa: E402
from agent_handoff.summarize import summarize  # noqa: E402

# Kinds a null probe is entitled to leave unanswered: the parse could not name an
# ending either, so there was nothing for the probe to have read.
SILENCABLE = {
    "clean", "error", "cancelled", "context_exceeded", "user_pending", "length_truncated",
}


def audit(parser, per_store: int) -> tuple[int, int, int, int, int, collections.Counter]:
    """(sessions, status-lying, status-silent, needs-lying, needs-silent, words)."""
    metas = parser.list_sessions()
    step = max(1, len(metas) // per_store)
    lying = silent = needs_lying = needs_silent = 0
    words: collections.Counter = collections.Counter()
    for meta in metas[::step][:per_store]:
        sid = meta.session_id
        try:
            probe = parser.peek_status(sid)
            needs = parser.peek_needs_reply(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"    probe raised {type(exc).__name__} on {sid[:13]}")
            continue
        words[str(probe)] += 1
        raw = parser.load(sid)
        if raw is None:
            continue
        kind = summarize(raw).interruption.kind
        if probe is not None and probe != kind:
            lying += 1
            print(f"    LIE {sid[:13]} probe={probe} detail={kind}")
        elif probe is None and kind in SILENCABLE:
            silent += 1
        # The other probe's own question, judged the same way: the last turn of the
        # whole transcript, with no window. Read from the rows rather than from
        # `raw.messages` - the rendered text is a different string from the one
        # `_row_content` hands the probe, and they disagree about injected
        # `<system-reminder>` context. What this gate cannot catch is a wrong turn
        # predicate; only that predicate's own tests can.
        truth: bool | None
        if hasattr(parser, "_resolve_group") and hasattr(parser, "_row_content"):
            # Turns in read order, each with the stamp its record carries: `load()`
            # sorts chronologically when every message carries one, so "last in the
            # file" is not "last on the page" for a session split over files - a
            # sub-agent transcript ends on the task it was handed. Where the sort
            # cannot apply (a turn with no stamp) the file order stands, as there.
            # The tie-break has to be the position, because `sort` is stable: two
            # turns stamped in the same second keep their file order on the page,
            # and `max` alone would hand the choice to the earlier one.
            turns: list[tuple[int, bool, str]] = []
            for path in parser._resolve_group(sid):
                for row in read_jsonl(path):
                    role, text, _raw, _tools = parser._row_content(row)
                    if role in ("user", "assistant") and text and not parser.is_noise(text):
                        turns.append((len(turns), role == "user", _iso(row.get("timestamp"))))
            stamps = [t[2] for t in turns]
            if turns and all(stamps) and len(set(stamps)) > 1:
                truth = max(turns, key=lambda t: (t[2], t[0]))[1]
            else:
                truth = turns[-1][1] if turns else None
        else:
            # A store with no row-level turn notion (SQLite, mostly): its probe does
            # not exist, so this only says how many rows it could have answered.
            shown = [
                m
                for m in raw.messages
                if m.role in ("user", "assistant") and (m.text or "").strip()
            ]
            truth = None if not shown else shown[-1].role == "user"
        if truth is None:
            pass
        elif needs is not None and bool(needs) != truth:
            needs_lying += 1
            print(f"    LIE(needs) {sid[:13]} probe={needs} transcript_user_last={truth}")
        elif needs is None:
            needs_silent += 1
    return len(metas), lying, silent, needs_lying, needs_silent, words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-store", type=int, default=40, help="sessions to parse per store")
    args = ap.parse_args()
    total = bad = needs_bad = 0
    all_words: collections.Counter = collections.Counter()
    for parser in all_parsers():
        cli = getattr(parser, "cli", type(parser).__name__)
        t0 = time.perf_counter()
        n, lying, silent, needs_lying, needs_silent, words = audit(parser, args.per_store)
        if not n:
            continue
        total += n
        bad += lying
        needs_bad += needs_lying
        all_words.update(words)
        note = "  <-- a probe contradicts the detail page" if lying or needs_lying else ""
        print(
            f"{cli:18} n={n:5} sampled={min(n, args.per_store):3} "
            f"status: lying={lying:2} silent={silent:3}   "
            f"needs: lying={needs_lying:2} silent={needs_silent:3}   "
            f"{time.perf_counter() - t0:4.0f}s{note}"
        )
    print(
        f"\n{total} sessions on this machine; {bad} sampled rows where the status "
        f"probe and {needs_bad} where the needs-input probe contradicts the detail "
        "page. Either one exits 1: a wrong badge ships to a user, and a wrong "
        "'not waiting' hides a conversation that is."
    )
    print("words the probes emit (STATUS_TONES and both locales must cover each): "
          f"{dict(sorted(all_words.items()))}")
    if any(w.startswith("raise:") for w in all_words):
        print("a probe raised instead of answering - that is a crash on the list path")
    return 1 if (bad or needs_bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
