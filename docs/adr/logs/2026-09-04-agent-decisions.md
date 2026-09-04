# Agent decisions — 2026-09-04

Session: owner asked for #523 (GW pipeline scratch persistence, the only open
follow-up from the #312 live-Pro QA run) to be fixed and merged. Branch
`claude/gw-pipeline-scratch-persistence-116b87`.

## No ADR for this fix

**Decision:** ship as a bug fix, no ADR.
**Reasoning:** the change applies the pattern #383 already established for
`concentration_surface` (per-run scratch tag, reverse-order cleanup, lock
reported as QA naming the path) to `groundwater_contours` and
`gw_model_pipeline`. #383 itself shipped without an ADR; nothing structural
or invariant-level is decided here.
**Revisit if:** scratch handling is generalised beyond these three modules —
that would be a convention worth an ADR.

## Shared helper lives in concentration_surface, and that module now uses it

**Decision:** extract the #383 cleanup loop into `cleanup_scratch` next to
`scratch_tag` in `concentration_surface.py` and call it from all three
modules, rather than copying the loop into the two GW modules.
**Reasoning:** one implementation of the lock-warning text; the
concentration-surface call site becomes a net deletion; the existing
`scratch_cleanup_failed` message/recommended-action strings the tests pin are
preserved verbatim (the tool name is a parameter).
**Revisit if:** `groundwater_contours` importing `concentration_surface` at
module level ever becomes a cycle (today `concentration_surface` imports
neither GW module).

## Dropped the issue's "000210 hint" item

**Decision:** no string-match on `ERROR 000210` in `contour_generation_failed`.
**Reasoning:** the per-run tag removes the collision at the root — a new run
never touches an earlier run's names, so a lock-held leftover cannot produce
000210 on the EBK leg any more. The residual lock case (cleanup cannot delete
an object the operator added to the map) is reported by the shared helper
with the exact path and recovery steps, which is what the issue asked the
hint to convey. A hint keyed on an error code that can no longer arise from
this cause would be speculative.
**Revisit if:** a live-Pro run reproduces 000210 on a tagged scratch path.

## Judgment: `_write_contour_outputs` split

**Decision:** move the post-scratch persistence half of
`build_groundwater_contours` into a private helper.
**Reasoning:** wrapping the original 200-line body in an outer `try/finally`
for cleanup would have pushed the publish stage two indent levels deep; the
split keeps the scratch lifecycle one readable `try/finally` and changes no
behaviour (same statements, same order, same QA codes).
