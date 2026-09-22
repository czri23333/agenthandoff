"""Run the gates CI runs, in the same order, before you push.

Why this exists: a commit in this repository went red on all nine CI jobs because
`ruff check .` was run *before* the last test edit and not after. The gates are a
set, not a menu, and that failure was not hard to avoid - it was easy to run four
of them and believe all five had run. This runs them in one command, in CI's
order, and stops at the first failure with the step named.

    python scripts/ci_local.py                  # the CI steps
    python scripts/ci_local.py --with-frontend  # ... plus tsc -b and npm run build

Steps, in order: pytest, ruff, `gen_tokens --check`, `evidence --check`,
`conformance --check`, and the CLI smoke (`--version`, `doctor`, `matrix`). The
frontend pair is opt-in because CI does not build the UI: the bundle is committed
so a clean clone can `pip install` and serve it, which is why a rebuild has to be
run deliberately whenever `web/` changed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"


def steps(frontend: bool) -> list[tuple[str, list[str], Path | None]]:
    """(label, argv, cwd) in the order CI runs them. cwd=None means the repo."""
    cli = [sys.executable, "-c", "from agent_handoff.cli import main; main()"]
    out: list[tuple[str, list[str], Path | None]] = [
        ("tests", [sys.executable, "-m", "pytest", "tests/", "-q", "-o", "addopts="], None),
        ("lint", [sys.executable, "-m", "ruff", "check", "."], None),
        (
            "generated tokens",
            [sys.executable, "scripts/gen_tokens.py", "--check"],
            None,
        ),
        (
            "evidence",
            [sys.executable, "-m", "agent_handoff.evidence", "--check"],
            None,
        ),
        (
            "conformance",
            [sys.executable, "-m", "agent_handoff.conformance", "--check"],
            None,
        ),
        ("cli --version", [*cli, "--version"], None),
        ("cli doctor", [*cli, "doctor"], None),
        ("cli matrix", [*cli, "matrix"], None),
    ]
    if frontend:
        out.extend(
            [
                ("tsc", ["npx", "tsc", "-b"], WEB),
                ("vite build", ["npm", "run", "build"], WEB),
            ]
        )
    return out


def _run(label: str, argv: list[str], cwd: Path | None) -> int:
    where = "" if cwd is None else f"   (in {cwd.name})"
    print(f"\n[{label}] $ {subprocess.list2cmdline(argv)}{where}", flush=True)
    # `npx`/`npm` are shell shims on Windows, so the frontend steps go through a
    # shell; everything else is a plain argv and never touches one.
    shell = cwd is not None
    return subprocess.call(subprocess.list2cmdline(argv) if shell else argv,
                           cwd=cwd or REPO, shell=shell)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--with-frontend",
        action="store_true",
        help="also run `npx tsc -b` and `npm run build` in web/ (CI does not)",
    )
    args = parser.parse_args(argv)
    for label, command, cwd in steps(args.with_frontend):
        if _run(label, command, cwd) != 0:
            print(f"\nFAILED at: {label}")
            return 1
    print(f"\nAll {len(steps(args.with_frontend))} gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
