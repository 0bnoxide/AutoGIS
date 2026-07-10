# Agent decisions — 2026-07-10 (canonical-read merge gate, ADR-0079)

Judgment calls made while closing the ADR-0075 merge gate. Design decisions were
pressure-tested with a `fable` advisor (per the user's standing request to keep
fable in the loop); the calls and reasoning are mine.

## One record-aware adapter instead of per-site asdict roundtrips
**Decision:** Add `canonical_records(records, qa)` to `canonical_read.py` rather
than repeat an `asdict → canonical_result_rows → map-back` roundtrip at each of
the seven dataclass consumers.
**Reasoning:** Seven hand-rolled roundtrips are seven chances to botch the
identity map-back; the policy module already declares itself the single place
this logic lives. The adapter returns the SAME record objects (via an `_i`
sentinel) because consumers rely on identity / `dataclasses.replace`.
**Revisit if:** a consumer needs a non-preferred fraction or a per-consumer
policy — then the shared helper is the wrong tool.

## apply_screening / evaluate_rpd_qa / validate_database left unconverted
**Decision:** Do NOT route these through the QC-dropping policy.
**Reasoning:** `apply_screening` is a 1:1 restamp that writes the full
system-of-record table back — dropping rows is data loss; stamp truthfully and
canonicalize where you *count*. `evaluate_rpd_qa` needs the field-duplicate's
result rows, which carry `QCType="FIELD_DUP"`. `validate_database` is a per-row
integrity validator that must see every raw row. Canonicalizing any of them
would defeat its purpose.
**Revisit if:** the RPD tool is migrated (see follow-up) or the screening flag's
downstream contract changes.

## Canonical-consumer boundary defined by value/flag columns, not table name
**Decision:** Treat a module as an in-gate canonical consumer iff it reads the
value/flag columns (`ResultNumeric`/`ExceedsScreeningLevel`/`QCType`/
`ResultFraction`), and put the legacy field-name island
(`AnalyteName`/`ResultValue`/`ReportedUnits`) out of scope.
**Reasoning:** The first audit keyed on the literal string `Env_AnalyticalResults`
and both under-covered (missed shared-reader consumers) and mis-included legacy
tools. `AnalyteName` exists in both vocabularies, so it can't be the key; the
value columns are what a canonical export actually carries. The value-column
sweep is what caught `event_changelog`, which reads `ResultNumeric` but keys on
`AnalyteName` (so it slipped both earlier passes).
**Revisit if:** a canonical→legacy export bridge is built — then an island tool
becomes a silent-corruption vector (a canonical export makes every legacy-tool
row parse as non-detect, not a clean no-op) and needs a tripwire or migration.

## Ship as a new ADR, not a note under ADR-0075
**Decision:** ADR-0079 (parent 0075). Number verified free against origin/main
AND every open PR's files before writing (this repo has collided on ADR numbers
repeatedly).
**Reasoning:** The vocabulary boundary, the three deliberate non-conversions, and
the enforcement posture are decisions, not mere execution of 0075.
