# Sanitized real-format fixtures

Each directory is a **structure-preserving, content-replaced sample of a real
session store** on the maintainer's machine, produced by
`scripts/sanitize_fixtures.py`. Keys, nesting, record types, enum vocabulary, id
shapes, file layout and record counts come from the vendor's own files; every
string is generated. Absolute paths become synthetic, secrets are hashed-redacted,
emails and URLs point at `example.test`, and the build fails if a home path, a
username (in any of the spellings vendors mangle it into), or one of this
machine's project directory names survives anywhere in the tree — including inside
SQLite cells and inflated zlib blobs.

Per directory, `.fixture.json` records where a parser must be aimed
(`with_root`), how many records were sampled away (`max_records`,
`sampled_records`), how much dialogue the source sessions held
(`source_messages`), and the seed. A fixture is a **sample**: it proves the
format, not a transcript.

| consumer | command |
|---|---|
| does it parse? | `pytest tests/test_fixtures.py` |
| is the claim current? | `python -m agent_handoff.evidence --check` |
| did the format drift? | `python -m agent_handoff.conformance --check` |
| rebuild from live stores | `python scripts/sanitize_fixtures.py` (maintainer only) |

`kimi/` is *shape only*: that store holds a single empty "New Session", so it
proves layout and nothing else. `claude/` and `codebuddy-cn/` have no fixture at
all — no store was ever available to sample — which is why the support matrix
labels them `unverified` instead of ✅.
