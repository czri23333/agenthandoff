---
feature: divergent-slice-cigate-1
status: in-progress
updated: 2026-09-09
branch: compose/divergent-slice-cigate-1
commits: c033438..HEAD
---

# Divergent Slice Cigate 1

## Report

## [S1] Problem
CI verifies the Python engine hard — 235 tests across 9 OS×Python legs, `ruff`, and two evidence gates — but never touches the frontend. `grep -E 'node|npm|vite|tsc' .github/workflows/ci.yml` matches nothing, yet 13 built asset files are committed under `src/agent_handoff/server/static/` and shipped inside the wheel. Two silent failures are therefore possible on a green run: a TypeScript error or broken Vite build reaches `main` unnoticed, and an author who edits `web/src/**` without rebuilding+committing ships a stale cockpit — the exact "green gate hiding a wrong artifact" class this project's evidence layer exists to prevent.

## [S2] Design
One additive CI job, `frontend`, on a single runner (`windows-latest` — the platform the committed dist is produced on, so the freshness comparison can never be a cross-platform false positive). Steps: checkout → `actions/setup-node@v4` (node 24, `cache: npm`, `cache-dependency-path: web/package-lock.json`) → `npm ci` in `web/` → `npx tsc -b` (typecheck) → `npm run build` (emits into `../src/agent_handoff/server/static`, `emptyOutDir`) → two guards. Guard one, "the build actually wrote": a marker file is touched before the build and at least one asset must be newer than it, because "no differences" is not the same claim as "the build emitted here" — a moved `outDir` would otherwise pass while the shipped cockpit stays stale. Guard two, "committed dist matches the source": `git status --porcelain -- src/agent_handoff/server/static` must be empty (a strict superset of `git diff --exit-code`: it also catches an asset the build stopped emitting, a new one it started emitting, and EOL drift), with an actionable message ("run npm ci && npm run build in web/ and commit the result"). The existing 9-leg matrix is untouched. Documented assumption: the freshness half is valid only where the artifacts are authored, hence Windows; recorded in CONTRIBUTING so a future Linux-based contributor knows why it is pinned there.

## [S3] Out of Scope
Changing the frontend build config (`outDir`, `emptyOutDir`, `sourcemap`), shipping the dist by building it at wheel time, proving byte-equality across operating systems, any UI or styling change, and adding ESLint/Prettier gates to the frontend.

## Tasks
- [ ] T1: Additive `frontend` CI job — acceptance: `ci.yml` gains the job (setup-node + npm ci + tsc + build + write-guard + `git status --porcelain` freshness guard); the YAML parses; running the same commands locally on the committed tree leaves the working tree clean (covers: S2)
- [ ] T2: Prove both guards can fail — acceptance: a deliberate frontend source edit followed by `npm run build` makes the freshness guard non-empty, and a marker touched after the build makes the write-guard fire (both observed locally under Git Bash, then reverted), so neither check is vacuous (covers: S2; depends: T1)
- [ ] T3: Document the gate and its platform pin — acceptance: CONTRIBUTING states the frontend is built and freshness-checked in CI on Windows and why; `uv run python -m agent_handoff.evidence --check` and `conformance --check` stay green (covers: S2; depends: T1)
