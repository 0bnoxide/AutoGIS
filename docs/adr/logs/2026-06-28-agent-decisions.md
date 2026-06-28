# Agent Decisions Log — 2026-06-28 Nightly Cloud Agent Batch

Recorded by the AutoGIS nightly cloud agent. Each section records an
interpretation or judgment call made during the session.

---

## Feature Selection — 2026-06-28T00:00:00Z

**Decision:** Implement three headless (CLOUD) tools from existing plans:
  1. `run-history-report` (Tool 10.1) — multi-event per-location/analyte history summary
  2. `validate-schedule` (Tool 10.2) — monitoring schedule YAML structure validation
  3. `apply-screening` (Tool 3.5) — re-evaluate ExceedsScreeningLevel on existing records

**Reasoning:** All three have detailed implementation plans already written
(2026-06-27-run-history-summary-report.md, 2026-06-27-validate-schedule-yaml.md,
2026-06-27-normalize-results-apply-screening.md). None have a corresponding source
file in `autogis/core/envmon/` (confirmed by `ls` of the directory). All three are
Runtime.CLOUD (arcpy-free, openpyxl-free), fully testable in this headless environment.
They compose naturally: apply-screening enriches records, history-report summarises
them, validate-schedule pre-flights the schedule used to find gaps.

**Revisit if:** A higher-priority headless feature is queued in a new ADR, or if
implementation reveals that these modules were already created in a parallel branch.

---

## Worktree Chain — 2026-06-28T00:01:00Z

**Decision:** Feature branches chained: feat/run-history-report off origin/main →
feat/validate-schedule off feat/run-history-report → feat/apply-screening off
feat/validate-schedule. This ensures cli.py and capabilities.py changes don't conflict
in the PRs when merged in sequence.

**Reasoning:** The task spec requires this chaining pattern explicitly to avoid merge
conflicts on shared files. Each PR inherits the previous feature's registry additions.

**Revisit if:** PRs are merged out of order or squashed in a way that loses the
capabilities.py and cli.py changes.

---

## run-history-report: HistorySummaryRow.NTotal — 2026-06-28T00:02:00Z

**Decision:** `NTotal` includes non-detected and not-measured records but excludes
`IsNotAnalyzed=1` records. The trend computation only uses records from the two most
recent unique `SampleDate` values, using per-date means for multi-sample events.

**Reasoning:** Plan spec says "Records with `IsNotAnalyzed == 1` excluded from all
counts" and "Stats computed over `ResultNumeric` for detected results only." Keeping
non-detects in NTotal gives the full sampling count (detect + non-detect) while
separating the statistic computations. This matches common lab reporting conventions.

**Revisit if:** Downstream consumers need NTotal to mean "detected only" or if
IsNotMeasured records should also be excluded.

---

## validate-schedule: analyte_dict type — 2026-06-28T00:03:00Z

**Decision:** The `analyte_dict` parameter is `Optional[Set[str]]` (a set of canonical
analyte names), not a full dictionary with metadata. The CLI loads the analyte dict CSV
and extracts the `AnalyteCanonicalName` column into a set for fast membership tests.

**Reasoning:** The plan specifies "CSV with AnalyteCanonicalName column." Using a set
rather than a dict is the minimal interface needed for membership checking. If richer
data (units, groups) is needed in the future, the dict form can be added as an
optional second parameter.

**Revisit if:** validate-schedule needs to check analyte units or groups, not just names.

---

## apply-screening: unit_conversion_failed leaves record unchanged — 2026-06-28T00:04:00Z

**Decision:** When unit conversion fails (incompatible dimensions or unknown unit),
the original record is appended unchanged (ExceedsScreeningLevel not updated), and
a WARNING is emitted. The record is not dropped.

**Reasoning:** Plan spec states "emit WARNING `unit_conversion_failed`, leave
`ExceedsScreeningLevel` as-is (or None)." Preserving the record ensures no data
loss; the WARNING flags it for human review. Dropping records would be destructive.

**Revisit if:** Downstream consumers treat "None" exceedance differently and need
a distinct sentinel value for "conversion failed" vs "no screening level available."

---

## TOOLS dict gaps — 2026-06-28T00:05:00Z

**Decision:** Only the three new commands are added to capabilities.py TOOLS dict.
Existing commands that are missing from TOOLS (evaluate-rpd, evaluate-rpd-qa,
export-summary, export-report-format-summary-tables, evaluate-readiness,
validate-rtk-survey, import-rtk-survey, reconcile-survey123-lab, route-survey123)
are NOT fixed in this batch.

**Reasoning:** Fixing the existing TOOLS gaps is a correctness fix, not a feature, and
is out of scope for this feature-implementation batch. The missing tools don't call
`_guard()` with their own name (LOCAL tools that exist pass hardcoded strings or skip
TOOLS lookup), so the gap doesn't cause runtime errors. A separate "fix-capabilities-dict"
PR should address this with proper tests.

**Revisit if:** A test is added that checks TOOLS completeness against CLI commands,
causing CI failures.

---

## duplicate reconcile-locations command — 2026-06-28T00:06:00Z

**Decision:** Left the pre-existing duplicate `@envmon.command("reconcile-locations")`
at lines 218-255 of `cli.py` untouched. Not addressed in this batch.

**Reasoning:** Inherited from 2026-06-27 agent batch (logged in 2026-06-27 decisions
log). Fixing it in this session would risk interfering with the chained worktree PRs
if any test depends on the current behavior. Scoped out.

**Revisit if:** A test starts failing because Click raises on duplicate command
registration, or the team schedules a cli.py cleanup pass.
