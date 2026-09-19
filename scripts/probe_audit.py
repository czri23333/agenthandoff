#!/usr/bin/env python
"""Audit the cheap list-page probes against each parser's own full parse.

Run it: `python scripts/probe_audit.py [--per-store 40]`

`peek_status` and `peek_needs_reply` answer for every row of the session list,
so they run per session and must stay cheap - which is also how they can drift
away from what the detail page says about the same session. This walks the
stores on this machine and reports the two ways they can be wrong:

  lying    the probe answered, and the full parse disagrees.
  silent   the full parse names an end state the probe could have read.

A null `peek_status` is not a defect by itself: `parsers/base.py` says a null
means unknown and is never to be read as clean, and for most of the stores here
the log genuinely records no ending (limitations item 31). `lying` is the one
that ships a wrong badge to a user.
"""
from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_handoff.server.app import all_parsers  # noqa: E402
from agent_handoff.summarize import summarize  # noqa: E402

# Kinds a null probe is entitled to leave unanswered: the parse could not name an
# ending either, so there was nothing for the probe to have read.
SILENCABLE = {
    "clean", "error", "cancelled", "context_exceeded", "user_pending", "length_truncated",
}


def audit(parser, per_store: int) -> tuple[int, int, int, collections.Counter]:
    """(sessions, lying, silent, words the probe emitted) for one store."""
    metas = parser.list_sessions()
    step = max(1, len(metas) // per_store)
    lying = silent = 0
    words: collections.Counter = collections.Counter()
    for meta in metas[::step][:per_store]:
        sid = meta.session_id
        try:
            probe = parser.peek_status(sid)
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
    return len(metas), lying, silent, words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-store", type=int, default=40, help="sessions to parse per store")
    args = ap.parse_args()
    total = bad = 0
    all_words: collections.Counter = collections.Counter()
    for parser in all_parsers():
        cli = getattr(parser, "cli", type(parser).__name__)
        t0 = time.perf_counter()
        n, lying, silent, words = audit(parser, args.per_store)
        if not n:
            continue
        total += n
        bad += lying
        all_words.update(words)
        note = "  <-- probe contradicts the detail page" if lying else ""
        print(f"{cli:18} n={n:5} sampled={min(n, args.per_store):3} "
              f"lying={lying:2} silent={silent:3} {time.perf_counter() - t0:4.0f}s{note}")
    print(f"\n{total} sessions on this machine; {bad} sampled rows where a probe "
          "contradicts the detail page.")
    print("words the probes emit (STATUS_TONES and both locales must cover each): "
          f"{dict(sorted(all_words.items()))}")
    if any(w.startswith("raise:") for w in all_words):
        print("a probe raised instead of answering - that is a crash on the list path")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
