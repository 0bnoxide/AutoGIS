# Agent decisions — 2026-07-15 (ADR-0084 key-collision resolution, #230)

Judgment calls made implementing ADR-0084 after the user signed off on option 1
(extend the per-reader `MethodDilutionKey` value recipe; do **not** widen the
frozen keys). A supplement to ADR-0084, not a substitute — the ADR carries the
decision; this records the autonomous calls behind its "Implementation" section.

## Confirmed the direction before building on it
**Decision:** When the interactive picker returned "widen frozen keys" — the
option ADR-0084 explicitly rejects and one that reverses ADR-0075's "never
widen again" — I did not proceed; I surfaced the two consequences (ADR-0075
reversal, cross-format reimport blast radius) and asked for plain-text
confirmation. The user answered "option 1".
**Reasoning:** A frozen-invariant reversal is hard to walk back once data is
reimported, and the session hand-off flagged the picker as misfiring all
session. A one-line confirmation was cheap insurance against acting on a
misclick. Not over-asking: I confirmed once, with the specific implication, not
the whole menu again.

## Method fold is analytical-stream-only
**Decision:** `_compose_dilution_key` appends `lab_anl_method_name` to
`__equis_method_dilution_key` only for non-QC rows.
**Reasoning:** `MethodID` is already a frozen `Env_QCResults` key part, so
folding it into the QC recipe distinguishes nothing and only churns QC keys on
reimport. Stream is intrinsic to the row, so the conditional stays per-row
deterministic — no conflict with the ADR-0080/0082 "same physical row keys the
same" rule.

## QC run-instance token is surgical, and numbers distinct signatures
**Decision:** Append `#N` to `MethodDilutionKey` only inside groups that
actually collide on the frozen key, numbering by first appearance of each
distinct data signature (all fields except provenance) in source order — not by
raw row position.
**Reasoning:** Two things at once. Surgical (collision-groups only) means a
non-repeated QC row keeps its slice-1 key verbatim, shrinking the reimport
re-key the ADR's Consequences flagged. Signature-numbering (not positional) is
what lets a genuine duplicate — identical data, differing only in `SourceRow` —
reuse its number and still collapse, instead of a blind `#1/#2` keeping a
spurious row. A positional ordinal would have been simpler and wrong on the §3
edge case.
**Revisit if:** a real EQuIS file carries a lab per-analysis instance id column
— prefer that (per-row, source-alone deterministic) over the group ordinal, per
ADR-0084 §2.

## Genuine-duplicate QA reuses the format-agnostic guard; renamed to `edd_`
**Decision:** `detect_within_file_key_collisions` splits a surviving collision
— identical-except-provenance → non-blocking `edd_true_duplicate` WARNING; rows
that differ → blocking `edd_key_collision` ERROR (unchanged). Category is
`edd_`-prefixed, not the proposal's `equis_`.
**Reasoning:** The guard already runs for every format; teaching it the
genuine-vs-under-discrimination split is more correct than a bolt-on EQuIS-only
check, and keeps the #230 safety net intact for formats without the recipe
extension. `edd_true_duplicate` matches its sibling `edd_key_collision` — an
`equis_` prefix on a format-agnostic guard would misdescribe it. Logged because
it deviates from the ADR proposal's literal category name.

## No separate design spec written
**Decision:** Fold the concrete design into ADR-0084's "Implementation" section
instead of writing a `docs/superpowers/specs/` doc, despite the hand-off listing
"write the slice-2 spec".
**Reasoning:** ADR-0075 §3 already sanctions recipe extension as the mechanism,
so no new architecture was introduced to spec. The ADR + this log carry the
decision and refinements. YAGNI — a spec doc restating the ADR is process for
its own sake.
**Revisit if:** slice-2's actual new dialect profiles (mining / epar4 / NYSDEC)
get built — that work is genuinely new and warrants its own spec.
