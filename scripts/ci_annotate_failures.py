"""Turn a pytest junit.xml into GitHub check annotations.

A red CI run used to say only "Process completed with exit code 1"; the failing
test's name lived behind a log page that requires sign-in. This reads the junit
report pytest already wrote and prints one `::error::` workflow command per
failing case, which GitHub turns into a check-run annotation - so the Checks tab
(and the API) names the test without any log access.

Usage: python scripts/ci_annotate_failures.py [junit.xml]
Exit code is always 0: annotating must never mask the real failure.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:220]
    return ""


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "junit.xml")
    if not path.is_file():
        print(f"::warning::no junit report at {path}; nothing to annotate")
        return 0
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        print(f"::warning::unreadable junit report: {exc}")
        return 0

    failing = 0
    for case in root.iter("testcase"):
        for bad in list(case.findall("failure")) + list(case.findall("error")):
            failing += 1
            name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
            detail = (bad.get("message") or "").strip().splitlines()
            summary = detail[0][:220] if detail else _first_line(bad.text)
            print(f"::error title=pytest failure::{name} — {summary}")
    print(f"{failing} failing test case(s) annotated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
