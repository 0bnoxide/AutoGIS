# Agent Decisions Log — 2026-06-27 Night Implementer Batch

Recorded by the AutoGIS cloud agent session. All locked design decisions
were already codified in ADR-0026; this log records interpretation calls
made during implementation.

---

## Feature Selection — 2026-06-27T00:00:00Z

**Decision:** Implement the three tools specified by ADR-0026:
CompareMonitoringEvents (4.7), ProcessLevelLoop (8.1), and
IdentifyMonitoringDataGaps (4.10).

**Reasoning:** ADR-0026 is dated today (2026-06-27), explicitly queues
these three tools for the night-implementer batch, and provides complete
functional-structure decisions for each. All three are arcpy-free, CSV-in/
CSV-out, and reuse established infra (`read_records_csv`, `QACollector`,
`_render_qa`). No design ambiguity; minimal architectural risk.

**Revisit if:** ADR-0026 is superseded or a higher-priority headless tool
is added to the queue.

---

## CompareMonitoringEvents — 2026-06-27T00:01:00Z

**Decision:** `PercentChange` is stored as a raw `float` (full precision)
rather than rounded. The plan tests use exact values (100.0, 5.0) and the
computation `(10.5-10)/10*100 = 5.0` is exact in IEEE 754, so no rounding
is needed at the record level. Callers may round for display.

**Reasoning:** ADR-0026 says "be precise on PercentChange" and the plan
confirms exact 100.0/5.0. Rounding here would change semantics — leave it
to the consumer.

**Revisit if:** Downstream tools require a fixed decimal precision in the CSV.

---

## CompareMonitoringEvents — 2026-06-27T00:02:00Z

**Decision:** `SiteID` in `ComparisonRecord` is taken from the first
result's `SiteID` for the series (not validated for consistency across
records in the same series).

**Reasoning:** The plan does not require cross-record SiteID validation,
and the ADR scopes this tool to single-site CSV inputs. Multi-site
mixing is an upstream responsibility (import-edd / build-event).

**Revisit if:** Multi-site result CSVs need to be supported.

---

## ProcessLevelLoop — 2026-06-27T00:03:00Z

**Decision:** A row that carries BOTH a backsight and a foresight is
treated as: (1) close the prior setup with the foresight, (2) open the
next setup with the backsight. This models the field rod-book pattern
where the instrument is set up at a turning point and reads both the
incoming and outgoing rod.

**Reasoning:** ADR-0026 states "A row may carry both a foresight (closing
the prior setup) and a backsight (opening the next) — process foresight
first, then backsight." Implemented exactly as specified.

**Revisit if:** Field data shows setup_id can distinguish the two readings
even in the same row — would require splitting into two rows at parse time.

---

## ProcessLevelLoop — 2026-06-27T00:04:00Z

**Decision:** The closing BM foresight row is included in the output
`LevelLoopObservation` list with its raw elevation, but after adjustment
the closing BM's adjusted elevation equals `known_elevation` (within
floating-point). We do NOT synthesize a special closing-BM record; we
include the actual observation row as-is with its closing elevation.

**Reasoning:** Preserving all input rows in the output makes the output
auditable (1:1 with the input). The adjustment pass corrects turning-point
elevations; the closing BM's computed elevation is only used for
misclosure, not as an output elevation.

**Revisit if:** Downstream consumers need the closing BM's adjusted
elevation separately.

---

## IdentifyMonitoringDataGaps — 2026-06-27T00:05:00Z

**Decision:** The schedule YAML `well_analytes` key is optional (absent
means all wells use `required_analytes`). Parsing uses `.get()` with an
empty dict default; no error is raised for an absent `well_analytes` key.

**Reasoning:** The plan's YAML example shows `well_analytes` as optional.
Enforcing its presence would break schedules that don't need per-well
overrides.

**Revisit if:** `ValidateEnvConfig` (10.2) adds schedule-YAML validation
and enforces a stricter schema (see ADR-0026 known limitation).

---

## TOOLS Registry — 2026-06-27T00:06:00Z

**Decision:** All three new CLI commands are registered as `Runtime.CLOUD`
in `capabilities.py`.

**Reasoning:** All three are explicitly headless per ADR-0026 ("arcpy-free,
schema-backed, CSV I/O"). They never call `_guard()` and never import arcpy.

**Revisit if:** A future version adds a GDB-write mode (e.g.,
ProcessLevelLoop 8.2 writes ElevationHistory), which would make it HYBRID
or LOCAL.

---

## duplicate reconcile-locations command — 2026-06-27T00:07:00Z

**Decision:** The pre-existing duplicate `@envmon.command("reconcile-locations")`
at lines 218-255 of `cli.py` was left untouched. Only new commands were added.

**Reasoning:** Fixing a pre-existing bug is out of scope for this batch.
Removing the duplicate risks a test regression without a matching test update.

**Revisit if:** Tests start failing because Click raises on duplicate command
registration, or the team schedules a cli.py cleanup pass.
