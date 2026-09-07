---
feature: divergent-slice-bundle-1
status: in-progress
updated: 2026-09-07
branch: compose/divergent-slice-bundle-1
commits: 5389600..HEAD
---

# Divergent Slice Bundle 1

## Report

## [S1] Problem
Both renderers emit `bundle_version "0.2"` (`render.py` `BUNDLE_VERSION`, `model.py` `to_dict`), but the normative JSON Schema pins `"const": "0.1"` — every shipped bundle violates its own contract. Nothing enforces the contract (limitations #12: schema documented, never validated), so the next renderer drift will again surface weeks later as an empty field.

## [S2] Design
Additive evolution, no rewrites: keep `schema/handoff-bundle-v0.1.schema.json` and the v0.1 spec prose untouched. Add normative `schema/handoff-bundle-v0.2.schema.json` describing current renderer output (required top fields, `bundle_version` const `0.2`, extended meta, interruption, state/files/tool shapes, transcript/raw/unfinished carriers). Add `tests/test_bundle_contract.py` validating `summarize(raw).to_dict()` for fixture sessions with the `jsonschema` dev dependency (core stays stdlib-only per ADR-001; dev extras already carry pytest/ruff/httpx). Delete limitations #12 and update the README contract line to name the v0.2 schema.

## [S3] Out of Scope
Markdown renderer prose vs spec text, the backup manifest's same-named `bundle_version` key (a different document), resume-prompt spec, frontend `bundle_version` typing, and any renderer behavior change — output bytes must not move.

## Tasks
- [ ] T1: v0.2 schema — acceptance: new `schema/handoff-bundle-v0.2.schema.json` describes current `to_dict()` output field-for-field; `uv run pytest tests/test_fixtures.py -q` still passes (covers: S2)
- [ ] T2: Contract test — acceptance: `tests/test_bundle_contract.py` validates fixture-session bundles via `jsonschema` and fails on a mutated version/required key (reproduction-first); full `uv run pytest tests/ -q` passes (covers: S2; depends: T1)
- [ ] T3: Docs closure — acceptance: limitations #12 deleted (entries renumbered), README contract line names v0.2; `uv run python -m agent_handoff.evidence --check` and `ruff check` pass (covers: S2; depends: T2)
