"""Ask one live store what row shapes it contains, and what we do about each.

The excuse lists in `parsers/jsonl_family.py` were built from a 131-session
sample (spec Round 41), so "no unread shapes" has always been a claim about a
sample. This asks the question of every file the store holds:

  1. census every row's shape name (the parser's own `_row_shape`, so the two
     agree on what a "shape" is) and how many files carry it;
  2. load a real session that carries each shape and report the parser's verdict.

Three verdicts are possible and only one is a problem. `read` means the parser
took something from the row; `excused` means the shape is on a list that says
"this carries nothing the product models", which is a decision with a count
beside it; `UNREAD` means the store started writing something nobody has
classified, which is the thing this script exists to catch.

Needs that CLI's live store, so it is a maintainer command, not a CI gate
(same standing as `sanitize_fixtures.py`). Exit code is 1 when any shape comes
back UNREAD, so a cron can watch a store for drift.

    python scripts/sweep_row_shapes.py --cli qoder-ide
    python scripts/sweep_row_shapes.py --cli codex --max-load 40
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_handoff.parsers import all_parsers  # noqa: E402
from agent_handoff.parsers.jsonl_family import (  # noqa: E402
    FILE_BEARING_ATTACHMENTS,
    ROLELESS_ROW_TYPES,
    _row_shape,
)


def _census(root: Path) -> tuple[dict, dict, int, int]:
    rows: collections.Counter = collections.Counter()
    carriers: dict[str, list[str]] = collections.defaultdict(list)
    files = malformed = 0
    for f in sorted(root.rglob("*.jsonl")):
        files += 1
        try:
            fh = f.open(encoding="utf-8", errors="replace")
        except OSError:
            malformed += 1
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    malformed += 1
                    continue
                if not isinstance(row, dict):
                    malformed += 1
                    continue
                kind = _row_shape(row)
                rows[kind] += 1
                if f.stem not in carriers[kind]:
                    carriers[kind].append(f.stem)
    return rows, carriers, files, malformed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cli", required=True)
    ap.add_argument("--max-load", type=int, default=60,
                    help="cap sessions parsed for the verdict column (0 = skip it)")
    ap.add_argument("--root", default=None,
                    help="read this store directory instead of the one on this "
                         "machine (a copy, an older roll, a hand-made case)")
    args = ap.parse_args()

    parser = next((p for p in all_parsers() if p.cli == args.cli), None)
    if parser is None:
        print(f"no parser named {args.cli!r}", file=sys.stderr)
        return 2
    if args.root:
        # The parsers take their root, so pointing at a copy is the same code
        # path a live store goes through -- that is what makes this a check and
        # not a reading of the source.
        parser = type(parser)(Path(args.root))
        root = Path(args.root)
    else:
        # The family parsers keep their own root; the rest are found by the same
        # probe the doctor runs, whose name is the cli with a `_store` suffix.
        root = getattr(parser, "root", None)
        if root is None:
            from agent_handoff import locations

            probe = getattr(locations, args.cli.replace("-", "_") + "_store", None)
            info = probe() if probe else None
            root = Path(info.path) if info and getattr(info, "path", None) else None
    if not root or not Path(root).exists():
        print(f"{args.cli}: no store on this machine", file=sys.stderr)
        return 2
    root = Path(root)

    rows, carriers, files, malformed = _census(root)
    listed = {m.session_id for m in parser.list_sessions()}
    print(f"store: {root}")
    print(f"files={files} rows={sum(rows.values())} malformed={malformed} "
          f"listed-sessions={len(listed)}")
    print(f"distinct shapes={len(rows)}\n")
    print(f"{'shape':<40} {'rows':>7} {'files':>6}  verdict")

    unread: list[str] = []
    loads = 0
    parsed: set[str] = set()
    for kind, n in rows.most_common():
        candidates = [s for s in carriers[kind] if s in listed]
        checked = bool(args.max_load and loads < args.max_load and candidates)
        if checked:
            loads += 1
            raw = parser.load(candidates[0])
            parsed.add(candidates[0])
            marks = [x for x in raw.meta.notes if x.startswith("unhandled_row")]
            exact = [x for x in marks if x.split(":")[1].split("=")[0] == kind]
            capped = len(marks) >= 5
        else:
            exact, capped = [], False
        roleless = kind in ROLELESS_ROW_TYPES
        file_bearing = kind.split("/")[-1] in FILE_BEARING_ATTACHMENTS
        if exact:
            verdict = f"UNREAD ({exact[0].split('=')[-1]} in that session)"
            unread.append(kind)
        elif not checked:
            verdict = "not checked (load budget, or only in sub-agent traces)"
        elif capped:
            verdict = "read or excused (note cap reached, unverified)"
        elif file_bearing:
            # Not an excuse: `_load_paths` takes a real path out of these rows,
            # so calling them "excused" would hide work the parser does.
            verdict = "read (names a touched file)"
        elif roleless:
            verdict = "excused (carries nothing the product models)"
        else:
            verdict = "read (no note)"
        print(f"{kind:<40} {n:>7} {len(carriers[kind]):>6}  {verdict}")

    print(f"\n{loads} shapes classified by parsing, across {len(parsed)} session(s); "
          "the census column covers every file.")
    if unread:
        print(f"\n{len(unread)} shape(s) this store writes that we do not classify:\n  "
              + "\n  ".join(unread))
        return 1
    print("every shape in this store is read, excused by name, or unverified above.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
