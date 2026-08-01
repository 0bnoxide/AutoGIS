# ADR-0022: Unit-conversion gate for screening-level evaluation

**Status:** Accepted

**Date:** 2026-06-25

## Context

`evaluate_screening()` in `autogis/core/envmon/result_parser.py` (lines 297-305) compares
a numeric result value directly against a raw `Optional[float]` screening level threshold.
No unit check is performed before the comparison.

Lab EDDs and historical workbooks routinely mix units: a screening level stored in ug/L
compared against a result measured in mg/L produces a numeric ratio off by 1000. The
exceedance flag is silently wrong — the function returns `True` or `False` with no
indication that the comparison was dimensionally incoherent.

The unit registry and the two functions needed to fix this — `convert()` and
`same_dimension()` — already ship in `autogis/core/common/units.py` (ADR-015 companion,
delivered with the validate-units command). The validate-units commit message explicitly
flagged this: "v1 does not touch the live screening path; convert()/same_dimension() ship
ready for that follow-up."

This is a correctness invariant, not a feature addition.

## Decision

Before any numeric comparison in `evaluate_screening()`:

1. Check `same_dimension(result_unit, screening_unit)`. If units are
   dimensionally incompatible (e.g., mg/L vs mg/kg), raise `UnitDimensionError` rather
   than returning a silent wrong answer.
2. If dimensionally compatible, call `convert(value, from_unit=result_unit,
   to_unit=screening_unit)` to normalise the result value before comparison.
3. If either unit is `None` or unrecognised by the registry, log a `QA_WARNING` and fall
   through to the raw comparison (preserving backward-compatible behaviour for
   configurations that predate the unit registry).

The fix is scoped to `result_parser.py` only. No changes to `evaluate_screening()`'s
public signature — callers pass units through the existing `result_unit` and
`screening_unit` keyword arguments that are already part of the function signature.

## Consequences

### Positive consequences

- Cross-unit comparisons (ug/L vs mg/L, mg/L vs mg/kg) raise a clear error instead of
  returning a silently wrong exceedance flag
- `None`/unknown-unit fallback preserves backward compatibility with existing site configs
  that do not yet populate unit fields
- The fix is surgical — one function, no new public API surface

### Negative consequences

- Any test or caller that passes mismatched units will now raise `UnitDimensionError`
  where it previously returned a wrong boolean; these tests need updating to either pass
  compatible units or assert the error
- Sites with incomplete unit metadata in `screening_levels.yaml` will emit QA warnings
  on every evaluation until the YAML stubs are filled (acceptable — the stubs are already
  marked `_TODO` per ADR-011)

## Alternatives considered

1. **Ignore the gap until screening_levels.yaml is filled:** Defer the fix until real
   threshold data is in the YAML.
   - **Rejected:** The comparison bug is independent of whether the thresholds are real
     numbers or stubs. A future operator filling in real thresholds would inherit a silent
     wrong-answer engine. Fixing correctness before filling data is the safer order.

2. **Convert at write time (normalise all screening levels to a canonical unit on
   YAML load):** Store all thresholds in a single canonical unit (e.g., ug/L) at config
   load time.
   - **Rejected:** Requires knowing the canonical unit per analyte family at load time,
     which the unit registry does not yet support. Conversion at comparison time is
     simpler and avoids a lossy transformation in the config layer.

3. **Raise on any `None` unit rather than falling through:** Require fully populated unit
   metadata before the function is callable.
   - **Rejected:** Would break every existing site config and test that pre-dates the unit
     registry. The fallthrough with `QA_WARNING` provides a migration path.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — units.py and
  result_parser.py are both arcpy-free; this fix stays in core
- [ADR-011: H281 profile and screening levels draft status](0011-h281-profile-draft-status.md) —
  screening_levels.yaml stubs remain `_TODO`; the unit fix is independent of that gate
- [ADR-016: Lab EDD Importer design](0016-lab-edd-importer-design.md) — EDD import is the
  primary driver that surfaces cross-unit comparisons in production data
