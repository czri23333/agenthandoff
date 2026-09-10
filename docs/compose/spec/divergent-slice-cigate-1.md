---
feature: divergent-slice-cigate-1
status: delivered
updated: 2026-09-09
branch: compose/divergent-slice-cigate-1
commits: c033438..91967bc
---

# Divergent Slice Cigate 1

## Report

**What was built** — A new additive `frontend` CI job closes the last blind spot in the gate set: the built cockpit is committed and shipped in the wheel, but nothing in CI compiled, typechecked, or rebuilt it. The job runs on `windows-latest` (where the artifacts are authored) and does `npm ci` → `tsc -b` → `npm run build`, then two guards: **the build actually wrote** (a marker touched before the build; some asset must be newer than it, so a moved `outDir` cannot pass while shipping stale assets) and **the committed dist matches the source** (`git status --porcelain -- src/agent_handoff/server/static` must be empty, which also catches assets the build stopped emitting, new ones, and EOL drift). CONTRIBUTING documents the gate and why it is pinned to Windows. The existing 9-leg test matrix is untouched.

**Verification** — YAML parsed (pyyaml): jobs `['test','frontend']`, 8 steps in order. Local replay of the job's commands on the committed tree: `npm ci` → `tsc -b` exit 0 → `npm run build` (vite 6.4.3, 5307 modules) → `git status --porcelain` empty for the whole tree, i.e. the Windows build reproduces the committed bytes exactly. Guards proven non-vacuous: editing one i18n label + rebuild → 13 changed dist entries (freshness guard fires); marker touched after the build → write-guard fires; both reverted, tree clean. Full `pytest` 235 PASS, `ruff` clean, `evidence --check` and `conformance --check` green. Independent review of c033438..4ddd2e7: no criticals, both guards validated (untracked/deleted/type-error probes all fail it; no false-positive path found on its own runner, `.gitattributes` `eol=lf` being what makes the Windows pin safe).

**Journey log** — The gap stayed invisible because a green CI badge reads as "the repo is covered": `grep -E 'node|npm|vite|tsc' .github/workflows/ci.yml` matched nothing while 13 built assets shipped in the wheel. De-risking the cross-platform question by building in WSL failed on logistics, not on logic — npm over `/mnt/d` never finished (162/253 packages in 25 minutes) — so the design moved the comparison to the authoring platform instead, and CI became the arbiter. The reviewer's blind-spot finding ("no differences ≠ the build wrote") became a second guard rather than a documented excuse. Two tool lessons: PowerShell `Set-Content` silently writes ANSI, mangling UTF-8 (it corrupted a TSX file that had to be reverted — source edits go through the edit tool), and passing paths with apostrophes through PowerShell into Git Bash mangles them; piping the script into `bash -s` works. **Honest gap:** this job has not yet run on a GitHub runner — branches without a PR get no CI — so the first PR opened on this branch is its live test.

## [S1] Problem
CI verifies the Python engine hard — 235 tests across 9 OS×Python legs, `ruff`, and two evidence gates — but never touches the frontend. `grep -E 'node|npm|vite|tsc' .github/workflows/ci.yml` matches nothing, yet 13 built asset files are committed under `src/agent_handoff/server/static/` and shipped inside the wheel. Two silent failures are therefore possible on a green run: a TypeScript error or broken Vite build reaches `main` unnoticed, and an author who edits `web/src/**` without rebuilding+committing ships a stale cockpit — the exact "green gate hiding a wrong artifact" class this project's evidence layer exists to prevent.

## [S2] Design
One additive CI job, `frontend`, on a single runner (`windows-latest` — the platform the committed dist is produced on, so the freshness comparison can never be a cross-platform false positive). Steps: checkout → `actions/setup-node@v4` (node 24, `cache: npm`, `cache-dependency-path: web/package-lock.json`) → `npm ci` in `web/` → `npx tsc -b` (typecheck) → `npm run build` (emits into `../src/agent_handoff/server/static`, `emptyOutDir`) → two guards. Guard one, "the build actually wrote": a marker file is touched before the build and at least one asset must be newer than it, because "no differences" is not the same claim as "the build emitted here" — a moved `outDir` would otherwise pass while the shipped cockpit stays stale. Guard two, "committed dist matches the source": `git status --porcelain -- src/agent_handoff/server/static` must be empty (a strict superset of `git diff --exit-code`: it also catches an asset the build stopped emitting, a new one it started emitting, and EOL drift), with an actionable message ("run npm ci && npm run build in web/ and commit the result"). The existing 9-leg matrix is untouched. Documented assumption: the freshness half is valid only where the artifacts are authored, hence Windows; recorded in CONTRIBUTING so a future Linux-based contributor knows why it is pinned there.

## [S3] Out of Scope
Changing the frontend build config (`outDir`, `emptyOutDir`, `sourcemap`), shipping the dist by building it at wheel time, proving byte-equality across operating systems, any UI or styling change, and adding ESLint/Prettier gates to the frontend.

## Tasks
- [x] T1: Additive `frontend` CI job — acceptance: `ci.yml` gains the job (setup-node + npm ci + tsc + build + write-guard + `git status --porcelain` freshness guard); the YAML parses; running the same commands locally on the committed tree leaves the working tree clean (covers: S2)
- [x] T2: Prove both guards can fail — acceptance: a deliberate frontend source edit followed by `npm run build` makes the freshness guard non-empty, and a marker touched after the build makes the write-guard fire (both observed locally under Git Bash, then reverted), so neither check is vacuous (covers: S2; depends: T1)
- [x] T3: Document the gate and its platform pin — acceptance: CONTRIBUTING states the frontend is built and freshness-checked in CI on Windows and why; `uv run python -m agent_handoff.evidence --check` and `conformance --check` stay green (covers: S2; depends: T1)
