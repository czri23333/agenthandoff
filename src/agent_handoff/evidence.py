"""Publish the measurements, and fail when the README and the evidence disagree.

The support matrix used to be typed by hand and it drifted into a false claim. The
fix is not "be more careful": it is that no cell in that table is authored any
more. This module writes the table into both READMEs from the fixtures, stamps the
date it was derived, and re-derives it on demand - so a reader who suspects the
table has one command to run, and CI runs it first.

Every artifact here is generated from the repo's own fixtures, never from a live
store, so it says the same thing on the maintainer's machine and on a fresh clone:

    README.md / README.zh-CN.md   the matrix block between the markers
    config/support-matrix.json    the same rows as data, for tooling
    conformance/<cli>.json        the format fingerprints (see conformance.py)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from agent_handoff import fixtures, matrix

REPO = matrix.REPO
MARK_BEGIN = "<!-- MATRIX BEGIN: generated, do not edit -->"
MARK_END = "<!-- MATRIX END -->"
READMES = {"en": REPO / "README.md", "zh": REPO / "README.zh-CN.md"}
MATRIX_JSON = REPO / "config" / "support-matrix.json"
STAMP = date.today().isoformat()


LEGEND = {
    "en": (
        "Legend: stable = a fixture parses to real dialogue; shape only = the "
        "source store held no conversation to sample; unverified = reader exists, "
        "no fixture yet; fixture fails = the fixture does not parse; roadmap = no "
        "reader; unavailable = needs an optional codec here."
    ),
    "zh": (
        "图例：稳定 = 夹具能解析出真实对话；仅形态 = 源存档本身没有对话内容；"
        "未验证 = 有读取器但没有夹具；夹具解析失败 = 夹具读不出来；"
        "路线图 = 尚无读取器；本机不可用 = 这里缺可选解码器。"
    ),
}


def render_block(lang: str = "en", rows: list[matrix.Row] | None = None) -> str:
    """The README section, with its own provenance and reproduction command."""
    rows = rows if rows is not None else matrix.build_rows()
    counts = matrix.summary(rows)
    proven = counts.get("stable", 0)
    if lang == "zh":
        intro = (
            "下表由 `tests/fixtures/sanitized/` 里的脱敏真实格式夹具推导生成，不是手写"
            "（推导日期见 `config/support-matrix.json`）。其中 {n} 项有夹具证据：克隆后运行 "
            "`pip install -e . && python -m agent_handoff.evidence --check` 即可复现；"
            "其余状态标注的是证据缺口，不是功能承诺。"
        ).replace("{n}", str(proven))
    else:
        intro = (
            "This table is derived from the sanitized real-format fixtures under "
            "`tests/fixtures/sanitized/` - not typed by hand (the derivation date "
            "lives in `config/support-matrix.json`). {n} rows carry fixture evidence "
            "you can reproduce after a clone with `pip install -e . && python -m "
            "agent_handoff.evidence --check`; the other labels name evidence gaps, "
            "not feature promises."
        ).replace("{n}", str(proven))
    return "\n".join(
        [
            MARK_BEGIN,
            intro,
            "",
            matrix.render_markdown(lang, rows),
            "",
            LEGEND[lang],
            MARK_END,
        ]
    )


def _splice(text: str, block: str) -> str | None:
    """Replace the marker region, or return None when the markers are missing."""
    start = text.find(MARK_BEGIN)
    end = text.find(MARK_END)
    if start == -1 or end == -1 or end < start:
        return None
    head, tail = text[:start], text[end + len(MARK_END) :]
    return head + block + tail


def sync_readmes() -> list[str]:
    """Write the generated block into every README; returns the ones that changed."""
    changed: list[str] = []
    for lang, path in READMES.items():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        block = render_block(lang)
        updated = _splice(text, block)
        if updated is None:
            raise SystemExit(f"{path.name}: {MARK_BEGIN} marker missing - add it back")
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")
            changed.append(path.name)
    return changed


def write_matrix_json() -> bool:
    """Refresh config/support-matrix.json; True when it changed on disk."""
    payload = {
        "version": matrix.MATRIX_VERSION,
        "generated": STAMP,
        "rows": [r.to_dict() for r in matrix.build_rows()],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if MATRIX_JSON.is_file() and MATRIX_JSON.read_text(encoding="utf-8") == text:
        return False
    MATRIX_JSON.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_JSON.write_text(text, encoding="utf-8", newline="\n")
    return True


def stale_targets() -> list[str]:
    """Artifacts that no longer match what the fixtures say right now."""
    problems: list[str] = []
    for lang, path in READMES.items():
        if not path.is_file():
            problems.append(f"{path.name}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        current = _splice(text, render_block(lang))
        if current is None:
            problems.append(f"{path.name}: matrix markers missing")
        elif current != text:
            problems.append(f"{path.name}: support matrix is stale")
    if not MATRIX_JSON.is_file():
        problems.append("config/support-matrix.json: missing")
    else:
        try:
            stored = json.loads(MATRIX_JSON.read_text(encoding="utf-8"))
        except ValueError:
            stored = {}
        fresh = json.loads(
            json.dumps(
                {
                    "version": matrix.MATRIX_VERSION,
                    "generated": STAMP,
                    "rows": [r.to_dict() for r in matrix.build_rows()],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        # `generated` is today's date; compare everything else.
        stored_rows = {r["cli"]: r for r in stored.get("rows", [])}
        for row in fresh["rows"]:
            if stored_rows.get(row["cli"]) != row:
                problems.append(f"config/support-matrix.json: stale row `{row['cli']}`")
    for cli in fixtures.available():
        if not fixtures.BASELINE_ROOT.joinpath(f"{cli}.json").is_file():
            problems.append(f"conformance/{cli}.json: no fingerprint baseline")
    return problems


def unproven_clis() -> list[str]:
    """Readers that exist but have no fixture to back the claim."""
    return matrix.unproven()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="evidence", description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail if artifacts are stale")
    mode.add_argument("--write", action="store_true", help="regenerate READMEs and JSON")
    args = ap.parse_args(argv)

    if args.write:
        for name in sync_readmes():
            print(f"[write] {name}")
        if write_matrix_json():
            print(f"[write] {MATRIX_JSON.relative_to(REPO).as_posix()}")
        print(render_block("en"))
        return 0

    problems = stale_targets()
    for problem in problems:
        print(f"! {problem}")
    rows = matrix.build_rows()
    print(f"{len(rows)} rows; summary={matrix.summary(rows)}")
    gaps = unproven_clis()
    if gaps:
        print(f"unproven readers (no fixture): {', '.join(gaps)}")
    if problems:
        print("Run `python -m agent_handoff.evidence --write` and commit the diff.")
        return 1
    print("README matrix and support-matrix.json match the fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
