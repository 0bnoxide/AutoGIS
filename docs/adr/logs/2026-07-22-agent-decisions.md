# Agent decisions — 2026-07-22

Context: The owner asked the agent to choose its own task, steered it to the
production roadmap, approved the recommended Phase 3 design/scope, then went to
bed granting explicit permission to write YAMLs and exercise judgement while
unavailable. These are the autonomous judgement calls made in that window.
Durable decision: ADR-0100. Spec:
`docs/superpowers/specs/2026-07-22-site-onboarding-bootstrap-design.md`.

## Picked Phase 3 (`init-site`) as the task

**Decision:** Build the Phase 3 first slice rather than the other candidates
(the GUI picker-hide work, open Pro-QA issues, or the merger bug found by the
background hunt).

**Reasoning:** GUI files were claimed by another live session (branch
`feat/gui-usability-picker-hide`, now PR #277). The open issues are Pro-QA
(need a human + real ArcGIS Pro) or Codex/coordination meta-work — poor
autonomous targets. Phases 1–2 are shipped, so Phase 3 is the next sanctioned
roadmap item: arcpy-free, self-contained, testable, and the owner steered me to
the roadmap.

**Revisit if:** the owner prefers a different sequencing or reopens a deferred
group.

## "schedule" == existing event config; no new schema

**Decision:** Treat the roadmap's "site/schedule/parser/figure-spec skeleton"
schedule leg as the existing `config/event_configs/` artifact; do not create a
schedule schema.

**Reasoning:** No schedule concept exists in the codebase, and ADR-0087
explicitly rejected a scheduler under YAGNI. `event_config.example.yaml` was
already a copy-and-fill template. Inventing a schema would violate roadmap
governance (no speculative infrastructure).

**Revisit if:** a real scheduling requirement is reopened by the owner.

## Sentinel substitution tokens instead of `{site_id}` / `render()`

**Decision:** Substitute `__SITE_ID__` / `__SITE_NAME__` via two `str.replace`
calls; do not reuse `harvest/templates.render()` or use `{site_id}` tokens.

**Reasoning:** Figure/parser templates legitimately carry `{site_id}` /
`{figure_spec_id}` as runtime placeholders that must survive init-site
untouched. `render()`'s regex misfires (`_unknown`) on brace tokens absent from
the attribute dict and could corrupt `{{...}}`. Plain `str.replace` on distinct
sentinels is simpler and correct on edge cases (advisor-flagged).

**Revisit if:** templates ever need more than two substitution variables.

## Scaffold all four families in slice 1

**Decision:** Generate site + event + parser + figure skeletons together (owner
answered "All four" to the one scope question before going to bed).

**Reasoning:** The Phase 3 gate requires the directory structure fully
assembled. Parser/figure files ship as DRAFT/`_TODO` skeletons, satisfying both
"assemble the structure" and "identify unverified anchors."

## Worktree suite artifact treated as non-blocking

**Decision:** Treated the 13 `tests/test_gui_executor.py` failures under the
PostToolUse hook as a known worktree environment artifact, not a regression, and
verified the true suite with `PYTHONPATH="$(pwd)"` (2343 passed, 0 failed).

**Reasoning:** Those tests spawn subprocesses that `import autogis`; in a
worktree the editable install points at the main checkout, so a subprocess from
a tmp cwd hits `ModuleNotFoundError`. Setting `PYTHONPATH` to the worktree makes
all 25 pass. The failing tests never import the new module. Matches the
`worktree-coord-gotchas` "editable-install false regressions" note.

## Held the merger bug for explicit approval

**Decision:** Did NOT ship the unrelated `event_results_merger.py:110` DictWriter
fieldnames bug (found by the background hunt) as a follow-up PR; surfaced it for
the owner instead.

**Reasoning:** I framed it to the owner as "your call," so "approve recommended
items" does not clearly cover it, and standing memory says to ask before
self-generated follow-up PRs. Fix is ready (`fieldnames = union of all rows'
keys`) pending a yes.

## Followed the pre-authorized @codex review-then-merge loop

**Decision:** After opening the PR, mention @codex, poll ~15–20 min, apply the
fixes it flags, and merge only when the review arrived, was addressed, the suite
is green, and no REQUEST_CHANGES is open. If @codex is silent after ~20 min,
leave the PR open with a status comment and stop — do not merge blind.

**Reasoning:** Owner pre-authorized "@codex review clears the merge" and noted
minor fixes are usually needed first; "mention clears you to merge" means
review-then-merge, not mention-then-merge (advisor-reinforced).
