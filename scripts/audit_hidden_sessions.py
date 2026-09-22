#!/usr/bin/env python3
"""Does the cockpit show every conversation on this machine?

The listing applies real de-duplication rules -- the qoder family writes each
user turn twice (a fragment file and the conversation file), consecutive
fragments are merged into one row, a fragment whose text already lives in a real
session is absorbed, and internal tool loops are hidden. Each rule removes rows.
A conversation is only *lost* when it is removed by a rule and nothing else
shows it: no listed row contains its turns.

This script asks that question end to end and exits 1 when the answer is not
"nothing is lost", so the claim is checked rather than argued. Four ways this
measurement goes wrong are designed out, because all four were walked into while
writing it:

* `listed` must come from **every** available entry, not only the stores that
  index files. `qoderwake`/`qoderwork` deliberately receive the transcripts the
  IDE filter rejects and have no `_index`; comparing against a partial `listed`
  set reports correctly-moved conversations as invisible.
* Searching for the row that absorbed a fragment must **not cap the rows read**.
  A capped scan misses a carrier whose header block is long and cries data loss.
* The de-duplication machinery must be asked **after** the listing ran, and the
  absorbed fragments have to be read from the machinery, not from the listing's
  output -- an absorbed fragment is by construction absent from the list it was
  removed from, so a checker that reads only that list classifies nothing.
* The id universe must include what each parser says it *hid*, not only what its
  files index. The first version missed 19 codebuddy tool loops that way and
  reported 107 hidden conversations where the cockpit's own chip says 126; the
  script now fails if any hidden id is neither listed elsewhere nor classified.

Usage: python scripts/audit_hidden_sessions.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_handoff.parsers import all_parsers  # noqa: E402
from agent_handoff.parsers.base import read_jsonl  # noqa: E402


def reported_ids(parsers) -> dict:
    """session id -> the parsers whose *files or receipts* report it."""
    owners: dict[str, list] = {}
    for p in parsers:
        ids: set[str] = set()
        index = getattr(p, "_index", None)
        if index:
            ids |= set(index)
        if hasattr(p, "_rollouts"):
            try:
                ids |= {p._thread_of(r.path, r.header) for r in p._rollouts()}
            except Exception:  # noqa: BLE001 - a store that will not enumerate is news, not a crash
                print(f"  NOTE: {p.cli} could not enumerate its own files")
        # A parser's own receipt for what it hid. Without this the census is
        # blind to exactly the rows the listing removed by rule: codebuddy keeps
        # its 19 tool loops outside `_index`, so a file-scan-only universe
        # reported 107 hidden ids while the cockpit's chip said 126.
        try:
            ids |= {m.session_id for m in p.hidden_sessions()}
        except Exception:  # noqa: BLE001 - same: a parser that cannot answer is news
            print(f"  NOTE: {p.cli} could not report what it hides")
        for sid in ids:
            owners.setdefault(sid, []).append(p)
    return owners


def classify(sid: str, owner) -> tuple[str, str]:
    """Why is this id not on screen? Returns (kind, evidence)."""
    raw = owner.load(sid)
    messages = list(raw.messages) if raw is not None else []
    users = [m for m in messages if m.role == "user" and not owner.is_noise(m.text or "")]
    if not users:
        return "EMPTY", f"{len(messages)} msgs, none a user turn"
    text = users[0].text.strip()

    index = getattr(owner, "_index", {}) or {}
    listed = {m.session_id for m in owner.list_sessions()}

    # 1. Merged: a member of a fragment group whose representative is listed.
    for rep, group in (getattr(owner, "_frag_groups", {}) or {}).items():
        if sid in group[1:] and rep in listed:
            return "MERGED", f"turn of listed row {rep[:16]} ({len(group)} fragments)"

    # 2. Absorbed: some other file carries this exact user text. Search every
    #    file of the store, uncapped, and ask whether the carrier is listed.
    for other_sid, paths in index.items():
        if other_sid == sid:
            continue
        for path in paths:
            try:
                rows = read_jsonl(path)
            except OSError:
                continue
            for row in rows:
                if row.get("type") != "user":
                    continue
                role, found, _raw, _tools = owner._row_content(row)
                if role == "user" and found and found.strip() == text:
                    if other_sid in listed:
                        return "ABSORBED", f"text lives in listed row {other_sid[:16]}"
                    return (
                        "LOST",
                        f"absorbed into {other_sid[:16]}, which is not listed either",
                    )
    return "LOST", f"{len(users)} user turns shown by no listed row"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args()

    parsers = [p for p in all_parsers() if p.available()]
    print(f"{len(parsers)} entries available: {[p.cli for p in parsers]}")
    listed: set[str] = set()
    for p in parsers:
        listed |= {m.session_id for m in p.list_sessions()}
    owners = reported_ids(parsers)
    orphans = sorted(set(owners) - listed)
    print(f"ids reported by some store: {len(owners)}   listed by some entry: {len(listed)}")
    print(f"reported but listed nowhere: {len(orphans)} -- classifying\n")

    kinds: dict[str, int] = {}
    lost: list[tuple[str, str, str]] = []
    for sid in orphans:
        owner = owners[sid][0]
        # the merge/absorb machinery is filled by a listing pass
        if hasattr(owner, "_list_all"):
            owner._list_all()
        else:
            owner.list_sessions()
        try:
            kind, evidence = classify(sid, owner)
        except Exception as e:  # noqa: BLE001 - an audit that crashes hides the answer
            kind, evidence = "ERROR", f"{type(e).__name__}: {str(e)[:70]}"
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind in ("LOST", "ERROR"):
            lost.append((owner.cli, sid, evidence))
        print(f"  {kind:<9} {owner.cli:<14} {sid[:22]:<24} {evidence[:88]}")

    tally = ", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))
    print("\nsummary:", tally or "nothing to classify")

    # The census's own coverage: every row a parser says it hid must be either
    # listed by some other entry or classified here. A hidden id in neither set
    # means this script is blind, which is the failure it exists to catch -- and
    # the shape of the bug it had before the receipts existed (codebuddy's 19
    # tool loops live outside `_index`, so 107 of 126 were counted).
    receipts = {m.session_id for p in parsers for m in p.hidden_sessions()}
    unseen = sorted(receipts - set(orphans) - listed)
    print(
        f"hidden receipts: {len(receipts)} rows, "
        f"{len(receipts & set(orphans))} of them classified here"
    )
    if unseen:
        print(f"FAIL: {len(unseen)} hidden ids are listed by nobody and classified by nothing")
        return 1
    if lost:
        print(
            f"\nFAIL: {len(lost)} conversations are reported by a store and shown by no entry"
        )
        return 1
    if not orphans:
        print("\nNOTE: zero unlisted ids on this machine -- the check ran but had nothing to judge")
        return 0
    print("\nOK: every unlisted conversation is visible inside a listed row")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
