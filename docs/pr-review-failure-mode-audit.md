# PR review failure-mode audit

**Issue:** [#332](https://github.com/0bnoxide/AutoGIS/issues/332)

**Snapshot:** 2026-07-26

## Purpose

Issue #332 identified five recurring review themes and PR #338 added them to
the cold `pr-reviewer`. This audit checks those themes against the repository's
actual review history and current controls, then turns the remaining gaps into
an evidence-producing review step.

## Evidence reviewed

The GitHub inline-review corpus contained 267 comments from 2026-06-28 through
2026-07-26: 233 top-level comments and 34 replies. The audit examined:

- every top-level finding on the issue's original examples, PRs #93, #95, and
  #96 (31 comments);
- every top-level Codex inline finding from 2026-07-21 through 2026-07-26
  (71 findings: 25 P1 and 46 P2);
- the current `pr-reviewer`, `envmon-spec-checker`, `arcpy-doc-verifier`,
  post-edit pytest hook, GitHub Actions workflow, and CLAUDE.md bug-tracking
  rule; and
- later examples cited by #332 or found after its checklist landed, including
  issues #301/#302/#304 and PR #367.

The 71 modern Codex findings were manually assigned one primary root-risk
theme. Findings often overlap; the primary theme is the earliest review probe
that should have exposed the defect.

| Primary root-risk theme | Findings | Representative failures |
|---|---:|---|
| Contract and reachability | 20 | recipe steps missing required inputs; producer vocabulary rejected by its consumer; invalid state-machine sequence; help/roadmap claims that cannot execute |
| Boundary shape and serialization | 15 | non-mapping YAML; mixed-type keys; bool accepted as int; invalid UTF-8/control characters; malformed dates |
| Side-effect and outcome safety | 13 | input/output aliasing; check-then-write races; partial multi-artifact publication; cancellation recorded as failure; failed rows reported as present |
| Environment, distribution, and test seams | 12 | resources absent from wheels; cwd-dependent notebooks; optional dependency mocks missing in CI; tests bypassing real console/runtime behavior |
| Identity, multiplicity, and provenance | 7 | repeatable values collapsed; filtered formula rows; sublayer provenance omitted from keys; checkpoint reused for another item |
| Hard invariant or security boundary | 4 | shell-write coordination bypasses; sentinel path traversal; incomplete redirection parsing |

The original PR #93/#95/#96 findings remain valid examples of boundary
robustness, false-success reporting, documentation drift, duplicate handling,
SQL escaping, and Python-floor compatibility. The newer corpus shows the same
families recurring in broader forms: cross-component reachability, key
injectivity, atomic side effects, packaging, and test-environment parity.

## Current-control coverage

| Control | What it catches | Remaining gap |
|---|---|---|
| Post-edit pytest hook | Regressions already represented by tests after Python edits | Does not run for docs/config edits; cannot detect a missing test or a bypassed production seam |
| GitHub Actions CI | Arcpy-free suite on Windows/Python 3.11 with dev extras | Editable install; no Python 3.10 leg, ArcGIS/real GUI, wheel-resource check, console-codec check, or concurrency/failure injection |
| `envmon-spec-checker` | Import boundaries, canonical config, DRAFT markers, new-tool reuse | Structural compliance, not behavioral edge cases |
| `arcpy-doc-verifier` | Current signatures, enums, licensing, and Pro 3.5/3.6 API currency | Arcpy-specific; does not validate data or workflow contracts |
| `pr-reviewer` after PR #338 | Names the original five issue #332 themes | Previously passive: no required applicable/N/A classification or evidence; identity, atomicity, packaging, and real producer-consumer probes were implicit |
| CLAUDE.md bug-issue rule | Makes discovered defects durable and searchable | Tracking occurs after discovery; it does not expose a defect before merge |
| External Codex inline review | Demonstrably finds adversarial P1/P2 defects | Not a repository-owned, uniform evidence contract for every cold review |

CI and static checks should stay focused. The recurring defects depend on
semantic contracts—whether two paths identify the same record, whether a
documented workflow is reachable, or what remains after the second of two
writes fails—so a broad regex linter would create noise without proving
correctness.

## Implemented review system

The existing `pr-reviewer` now owns five stable probe IDs:

| Probe ID | Required question |
|---|---|
| `BOUNDARY_SHAPE` | What happens for missing, malformed, wrongly typed, or wrongly encoded boundary values? |
| `CONTRACT_REACHABILITY` | Does a real producer value and documented invocation reach the consumer with the required vocabulary, arguments, and state? |
| `IDENTITY_PROVENANCE` | Are keys injective and order-independent across duplicates, heterogeneous sources, and repeated runs? |
| `SIDE_EFFECT_SAFETY` | Are overwrite intent, no-op reporting, partial failure, retry, concurrency, and related-state publication safe? |
| `ENVIRONMENT_SEAM` | Does the behavior survive the supported runtime, packaged install, working directory, optional-dependency, and real I/O seam? |

For every cold review, each ID must appear exactly once as `PASS`, `FAIL`, or
`N/A` with evidence. Applicable probes require a minimal adversarial command or
a cited regression test at the real call-site seam. `N/A` requires a reason,
and a green full suite is not evidence for a probe that the suite bypasses.

`tests/test_agent_definitions.py` pins both the five IDs and the evidence-bearing
output contract so a future prompt cleanup cannot silently remove the system.
