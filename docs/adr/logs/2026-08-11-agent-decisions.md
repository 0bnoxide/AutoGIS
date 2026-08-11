# Agent decisions — 2026-08-11

Session: scheduled autonomous run ("fix open issues by significance; check README
staleness; survey for gaps, wiring gaps, unimplemented dead-ends, stale
assertions"). Branch `claude/awesome-cray-foefzz`, PR #475.
No ADR: the batch adds no architecture, invariant or tool. It corrects two
metadata fields and the tests that guard them. This log records the autonomous
*judgment calls*, per `docs/adr/logs/README.md`.

## Scope calls

**Skipped everything the two open PRs already fix.** #467 takes #459, #460,
#461, #462, #463, #466; #472 takes #469 and #436. Read both PR bodies before
picking. That also ruled out #470, #471 and #474 — all three land in
`layout_manager` / `gen-map-series`, which #467 rewrites; fixing them on a
parallel branch buys a merge conflict and no earlier fix.

**Took #458 and #468 together.** Both are `TOOL_REGISTRY` metadata, both were
filed as "reported, not fixed, this is an owner call", and both touch
`capabilities.py` + `cli.py` + README. One diff, no shared files with either
open PR.

**Did not touch the owner-gated QA batches** (#195, #231, #238, #272, #307,
#312) — they need a human at an ArcGIS Pro or AGOL console. #449 / #450 remain
"wire it or delete it" choices, unchanged since the 2026-08-08 log made the
same call. #414 is a feature.

**Did not run the `pr-reviewer` subagent.** The CLAUDE.md merge gate requires it
against the final head *before merge*; this session's harness instructions
forbid dispatching agents unrequested, and the PR is opened Ready for Review,
not merged. Noted as owed in the PR body.

## Judgment calls inside the fixes

**Both issues said "owner call". Neither was — and that finding is the fix.**
Each issue held back because a second surface disagreed with the first. In both
cases a *third* surface was already authoritative and already correct:

- #458: the issue could not tell whether the six tools had been deliberately
  renumbered. They had not. Grepping every name and alias against
  `docs/envmon-feature-roadmap.md` shows **none of the seven appears in the
  79-tool catalog at all** — they are post-roadmap extras, and each number they
  carried belongs to a separately-shipped tool the catalog names in a
  `**Tool name:**` line. Absence from the authority is a fact, not a preference.
  `generate_event_report.py` had already reached this conclusion for its own
  case in #104 and fixed only its docstring, leaving `capabilities.py` wrong —
  precedent for the direction, and evidence that a docstring-only fix does not
  hold.
- #468: the issue could not tell whether `DRAFT` in the runtime column was
  intentional, because `--runtime` offered it as an explicit `click.Choice`.
  But `RUNTIME_MAP` — the map that actually gates execution — said `CLOUD`, the
  row's own `status` field said `draft`, and README:362 said CLOUD. Three
  surfaces against one, and the one is the only one with no consumer that
  depends on it.

**Reassigned the numbers rather than only clearing them.** #458's own suggested
direction was to drop the `Tool N.N:` prose and leave it there. That fixes the
duplicated copy and leaves `roadmap_id` — the field `list-tools --verbose`
actually prints — still wrong. Clearing the seven extras and handing each number
to the catalog's named owner is the same size of diff and leaves no false value.

**Set `manage-screening-levels` to `3.4` while fixing its runtime.** Outside
#468's stated scope. Justified because catalog §3.4's `**Tool name:**` is
`ManageScreeningLevels` verbatim, it is the row already being edited, and the
README carried a `3.x` hedge that is now resolvable. Also updated the README
hedge to match.

**Tried the general invariant first, and it failed — kept a curated test and
said so.** The obvious pin for #458 is "a registry row's name must match the
catalog's `**Tool name:**` for the number it claims". Ran it: **18 hits for 7
defects.** The catalog and registry legitimately use different names for the
same tool in eleven cases (`BuildCalloutsHullCollision` vs
`OptimizeCalloutPlacement`, `DraftParserProfile` vs
`CreateWorkbookParserProfile`, `GenerateEventChangelog` vs
`GenerateEventChangeLog` — casing only). Uniqueness alone catches just the
`10.1` collision, because the other six numbers' rightful owners were carrying
`""` rather than colliding. So: two general tests for the shapes that *are*
mechanically checkable (dangling id, two tools per section) plus one curated
list for the seven. The curated one names its own ceiling in its docstring
rather than implying coverage it does not have.

**Exempted `8.2` from the collision test instead of "fixing" the registry.** The
registry's `8.2` duplicate looks like the same defect as `10.1`, and is not:
`docs/envmon-feature-roadmap.md` carries **two** `### 8.2` headings, and each of
the two tools matches one. The registry is faithful; the catalog is ambiguous.
Renumbering a spec section is an owner call, so the exemption is scoped to that
one id with the reason inline, and the doc defect is filed as **#476** with the
instruction to delete the exemption when it lands.

**Removed a test carve-out rather than working around it.**
`test_runtime_class_agrees_between_tools_and_seed` skipped rows where
`seed_rt == "DRAFT"` and its docstring called the spelling "a documented display
state". The test passed *because* it restated #468. Deleted the carve-out and
corrected the sibling status-vocabulary test's docstring, which cited the
"deliberate" claim as supporting context.

**Derived `RUNTIME_CLASSES` from the `Runtime` enum instead of writing a fourth
literal list.** The `--runtime` Choice, the new vocabulary test and the enum were
three copies of one fact. `--domain` in the same decorator block already derives
from `TOOL_REGISTRY`, so this matches the local idiom rather than inventing one.

## Findings reported, not fixed

**#476** — `### 8.2`, `### 8.3` and `### 8.4` each appear twice in the catalog.
Above.

**#477** — thirteen tools have a `Roadmap #` in the README but `roadmap_id=""`.
The inverse of #458: missing metadata, not a false claim, so `list-tools
--verbose` under-reports rather than misreports. Populating them means asserting
thirteen numbers, each needing the verification #458's seven got — the README's
column is a second hand-maintained surface, and #458 is the proof that one can
be confidently wrong. Two are additionally blocked on #476.

**#465 re-audited, three of six items no longer hold as written.** Item 3
("no `pytest-cov`, `ci.yml` runs plain pytest") is false on all three claims
since #452/#453; the residue is only the missing `--cov-fail-under`. Item 1 is
not reproducible — `.codex/` has never been tracked and is absent from a fresh
clone, so the proposed dedup test would pass vacuously in CI, which is the
failure mode this repo keeps filing. Item 2 is half-resolved, and the surviving
`.claude/hooks/session-start.sh` hardcode is *deliberate* per the comment above
it, so the fix plan's `git rev-parse --show-toplevel` would break what that
comment protects — `--git-common-dir` is the form that works. Items 4, 5, 6 hold
verbatim. Posted to the issue rather than edited into it: re-scoping items 1 and
2 is the owner's call.

**Swept for the #460 shape and found nothing new.** AST-scanned every `cli.py`
command for a `QACollector` that is built and never read. Six hits; five read
`qa.records`, and the sixth is `export_wqx_cmd` — #460 itself, already fixed in
PR #467. No new instance.
