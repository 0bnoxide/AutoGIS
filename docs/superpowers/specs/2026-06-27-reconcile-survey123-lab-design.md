# ReconcileSurvey123AndLabResults Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** ReconcileSurvey123AndLabResults (Phase 2.2 / Tool 2.6)
**Priority:** HIGH (catches mismatches between field, lab, and GIS before map production)

---

## Problem

After a sampling event, three data sources must agree:
- **Survey123 submissions** — field crew's sample IDs, dates, matrices, locations
- **Lab EDD** — lab's sample IDs and result metadata
- **GIS well layer** — canonical location IDs and coordinates

Mismatches (format differences like `MW-1` vs `MW-01`, wrong date, wrong matrix, or
a field sample that never reached the lab) are currently caught manually — or not until
figures are produced with missing data. There is no pre-production reconciliation step.

The existing `reconcile_locations.py` (Phase 2.4) checks workbook location IDs vs GIS
wells. This tool extends that concept to three-way comparison: field vs lab vs GIS.

---

## Approach

**Chosen:** Pure headless comparison with CSV inputs for both Survey123 export and lab
EDD sample roster. Uses the same fuzzy-match logic as `reconcile_locations.py`
(`difflib.SequenceMatcher`, configurable threshold). Output via `QACollector`.

Survey123 field submissions are exportable as CSV from the Survey123 website or AGOL.
Lab EDDs are already parsed by `edd_importer.py`; a lightweight "sample roster"
extraction is added to that module.

No arcpy dependency at comparison time. An optional `--gdb` flag is reserved for a
future LOCAL path (matching against GIS features).

**Rejected: Direct AGOL API query for Survey123 data.** Requires network, credentials,
and the AGOL MCP server. The simpler CSV export path covers the immediate need; AGOL
integration is Phase 4 territory.

**Rejected: Absorbing into validate_database.** `validate_database` checks GDB
contents; this tool runs before import, comparing raw sources. Different gate, different
timing.

---

## Architecture

```
autogis/
  core/envmon/
    reconcile_survey123_lab.py   ← NEW
  adapters/
    cli.py                       ← add reconcile-survey123-lab command
tests/envmon/
  test_reconcile_survey123_lab.py ← NEW, arcpy-free
```

---

## Public API (`reconcile_survey123_lab.py`)

```python
@dataclass
class Survey123Sample:
    sample_id: str
    location_id: str
    sample_date: str       # ISO date string YYYY-MM-DD
    matrix: str
    sampled_by: str = ""

@dataclass
class LabSample:
    sample_id: str
    location_id: str
    sample_date: str
    matrix: str
    analyte_count: int = 0

@dataclass
class ReconcileS123LabResult:
    matched: list[tuple[Survey123Sample, LabSample]]
    field_only: list[Survey123Sample]      # in Survey123 but not in lab EDD
    lab_only: list[LabSample]              # in lab EDD but not in Survey123
    flags: list[str]                       # human-readable mismatch summaries

def load_survey123_csv(path: Path) -> list[Survey123Sample]:
    """Parse Survey123 export CSV.
    Expected columns: SampleID, LocationID, SamplingDate, Matrix, SampledBy
    Column names are configurable via a header_map dict (optional).
    """

def extract_lab_samples_from_edd(edd_path: Path, profile_path: Path) -> list[LabSample]:
    """Run edd_importer to extract the sample roster without importing to GDB."""

def reconcile_field_lab(
    field: list[Survey123Sample],
    lab: list[LabSample],
    threshold: float = 0.85,
) -> ReconcileS123LabResult:
    """
    Match samples by sample_id (exact first, then fuzzy at threshold).
    For matched pairs: flag date mismatches, matrix mismatches.
    Return unmatched field and lab samples.
    """

def reconcile_to_qa(result: ReconcileS123LabResult) -> QACollector:
```

---

## Matching Logic

```
for each field_sample:
    if lab_sample.sample_id == field_sample.sample_id (exact):
        matched pair
    elif similarity(field_sample.sample_id, lab_sample.sample_id) >= threshold:
        fuzzy match — add flag "sample_id_mismatch"
    else:
        field_only

for each unmatched lab_sample:
    lab_only
```

For matched pairs, additional checks:
- date differs by > 1 day → flag `date_mismatch`
- matrix differs → flag `matrix_mismatch` (ERROR)
- location_id differs → flag `location_mismatch` (WARNING; alias resolution deferred
  to `reconcile_locations`)

---

## QA Severity Mapping

| Flag | Severity | Category |
|---|---|---|
| `sample_id_mismatch` (fuzzy match) | WARNING | `sample_id_mismatch` |
| `date_mismatch` | WARNING | `date_mismatch` |
| `matrix_mismatch` | ERROR | `matrix_mismatch` |
| `location_mismatch` | WARNING | `location_mismatch` |
| Sample in field but not lab | WARNING | `field_only_sample` |
| Sample in lab but not field | WARNING | `lab_only_sample` |

---

## CLI Command

```
autogis envmon reconcile-survey123-lab \
  --survey <survey123_export.csv> \
  --edd <lab_edd.csv_or_xlsx> \
  --edd-profile <lab_profile.yaml> \
  --site <site_id> \
  [--threshold 0.85] \
  [--report <report.md>] \
  [--fail-on error|warning]
```

---

## Survey123 CSV Column Map (configurable)

```python
DEFAULT_S123_HEADER_MAP = {
    "sample_id": "SampleID",
    "location_id": "LocationID",
    "sample_date": "SamplingDate",
    "matrix": "Matrix",
    "sampled_by": "SampledBy",
}
```

Callers can override via a `--header-map` JSON option or by passing a dict.

---

## Test Strategy

`tests/envmon/test_reconcile_survey123_lab.py` — all arcpy-free:

1. Exact match → ReconcileS123LabResult with one matched pair, empty field_only/lab_only
2. Fuzzy match on sample_id → flag `sample_id_mismatch` in result.flags
3. Date mismatch on matched pair → WARNING `date_mismatch` in QA
4. Matrix mismatch on matched pair → ERROR `matrix_mismatch` in QA
5. Field sample not in lab → WARNING `field_only_sample`
6. Lab sample not in field → WARNING `lab_only_sample`
7. `load_survey123_csv()` with minimal header map returns correct `Survey123Sample` list
8. `reconcile_to_qa()` produces correct severity counts from a synthetic result
