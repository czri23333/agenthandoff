# `handoff memory-export` — design

*Implemented 2026-09-01. Status: shipped behind tests; source coverage below
is exactly what the code scans, nothing more.*

## What it is

Session handoff covers *what was done*; `memory-export` covers *what was
agreed*. It gathers the standing-instruction files that each coding CLI keeps
outside any single session and renders them in one tool-neutral format:

```
## instructions / identity / career / projects / preferences
- [YYYY-MM-DD] (cli `path`) - entry text
```

followed by `## sources scanned` and `## completeness`.

## Honesty contract (enforced by tests/test_memory_export.py)

1. A store that does not exist is reported `missing` — never silently dropped,
   never pretended empty. Unreadable and over-budget files get their own
   statuses.
2. Dates are file **modification times in UTC** ("last edited"), and the
   output says so. No guessing; no date → `[unknown]`.
3. Empty categories print an explicit note; no filler is fabricated.
4. Config files (zcode/kimi-code) are parsed to prove they parse and their
   top-level **keys are named, values never dumped**.
5. Classification is a keyword heuristic and the output labels it as such.
6. A narrow secret scan (vendor-prefixed keys, PEM, JWT, URL credentials)
   flags hits before the user pastes the export anywhere; it does not
   redact, because the export is user-initiated and redaction here would be
   unrecoverable guessing. High-entropy strings are deliberately not caught
   (false positives are as unrecoverable; see docs/research.md item 14).
7. Budgets bound every untrusted input (1 MiB per file, 4 000 chars per
   entry, 400 entries per file) — the capture_policy.rs discipline from the
   ai-memory study (docs/research.md item 15).

## Sources scanned

| cli | location | kind | verified 2026-09-01 |
|---|---|---|---|
| claude | `~/.claude/CLAUDE.md` | markdown | documented location; not present on this machine |
| codex | `~/.codex/AGENTS.md` | markdown | present on this machine, read live |
| gemini | `~/.gemini/GEMINI.md` | markdown | documented location; not present on this machine |
| kimi-code | `~/.kimi-code/config.toml` | config | present; parsed, keys only |
| zcode | `~/.zcode/cli/config.json` | config | present; parsed, keys only |
| project | `<cwd>/AGENTS.md`, `CLAUDE.md`, `GEMINI.md` | markdown | opt-out via `--no-project` |

Chinese-ecosystem memory stores (CodeBuddy, dsh, MiMo, Qoderwork, QwenWork)
are **not** scanned: none of them exposes a parseable standing-instruction
file we have been able to locate. Adding one requires the same evidence bar
as parsers — a real file, observed, under test.

## Usage

```
handoff memory-export                 # scan all sources + project files
handoff memory-export --lang zh       # Chinese section headings (指令/身份/职业/项目/偏好)
handoff memory-export --json          # machine-readable twin of the same honesty contract
handoff memory-export --cli codex     # one CLI only (unknown names exit 2 with the known list)
handoff memory-export --no-project    # skip AGENTS.md/CLAUDE.md in cwd
handoff memory-export --out notes.md  # to a file (parent dirs created; failures exit 2, one line)
```

## UX details that are tests, not vibes

- An existing-but-empty instruction file is reported `read, 0 entries —
  file is empty`, so zero entries is never ambiguous.
- Secret flags report label/offset/length and never echo the matched text:
  the flag line itself must not create a second copy of a credential in
  terminal scrollback (the entry still carries it — the export is the
  user's own content, user-initiated).
- Console output survives cp936/cp1252 consoles via the shared
  `_survive_console_codepage` guard; UTF-8 files are the lossless copy.
- `--out` failures print one `error:` line and exit 2 — never a traceback.

## Cockpit GUI (tab 5, `#memory`)

The same data, as a page instead of a command: `GET /api/memory-export`
returns entries, reports, secret flags, completeness, and BOTH language
markdowns so the copy/download buttons are lossless in either language.
Unknown `cli` values are a 404 carrying the known list; the endpoint shares
the CLI's honesty contract (missing stores stay listed, flags never echo
matched text).

Text rendering on that page follows the L0–L7 font-stack brief: the browser
owns shaping and layout (L2–L5), and the app stays out of its way —
- `.tx-user` = `line-break: strict` (UAX #14 kinsoku) + `overflow-wrap:
  anywhere` + `unicode-bidi: isolate` + `pre-wrap` on user-authored text;
- `dir="auto"` + bidi isolation on every user-content span and path, so RTL
  or mixed-script entries cannot reorder their neighbours (L2/L4);
- no JS ever slices entry text by code unit; the only truncation allowed is
  CSS line-clamp (breaks between rendered graphemes). Any future JS cut must
  go through `Intl.Segmenter` (UAX #29) — `.slice()` can land inside an
  emoji ZWJ sequence or on a combining mark.

## Known limits (stated, not hidden)

- Markdown splitting is list-item-based; free-form prose files lose
  structure (each non-empty line becomes an entry).
- `config-noted` sources contribute zero entries: knowing a file parses is
  not the same as understanding its memory.
- No session content is exported; that is `capture`/`resume` territory.
- The matrix/evidence system does not yet grade these sources; wiring them
  into `handoff matrix` is the next step once a second machine verifies the
  table above.
