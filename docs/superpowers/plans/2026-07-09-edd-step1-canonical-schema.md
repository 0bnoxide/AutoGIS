# EDD Expansion Step 1 — Canonical Schema + Key Redesign Implementation Plan

> **⚠️ HISTORICAL — DO NOT EXECUTE (superseded 2026-07-10).** Every task in this
> plan already shipped in **PR #212** (merged to main, 258f0a8) and its durable
> record is **[ADR-0075](../../adr/0075-canonical-schema-expansion-step1.md)** —
> **NOT ADR-0074**, which was taken by DraftLithologyFromScan (PR #210). All
> `0074` references below (planned filenames, example commit messages, code
> comments) are stale pre-execution guesses: read every one as **ADR-0075**.
> Do not create any ADR or re-run any task from this document — it is kept
> verbatim only as the planning record for the Step-1 build.

**Spec:** `docs/superpowers/specs/2026-07-08-canonical-schema-expansion-design.md` — the **AMENDMENT section at the top is authoritative** (MINIMAL Step-1 freeze). Paper-mapping record: `docs/superpowers/specs/2026-07-09-edd-paper-mapping-outcome.md`.

**Goal:** Expand `Env_AnalyticalResults` with the 12 frozen WQX-era columns, widen its dedup key to the frozen 11 components, extract the real key computation into a pure testable helper, generalize profile value-mapping, fix the EDD path's missing schema-ensure, and ship the canonical-read helper — so Step 2 (WQX) can import Total/Dissolved pairs without silent data loss.

**Architecture:** All changes ride the existing additive-only machinery: new nullable columns in `TABLE_SCHEMAS` + defaulted dataclass fields (no producer/factory breakage), `create_or_update_gdb_schema` + `upgrade_schema.py`/`Env_SchemaVersion` for migration (SCHEMA_VERSION 2.1→2.2, **no new migration framework**). The dedup key moves to a pure `compute_unique_key()` in `gdb_schema.py` so key-distinctness tests exercise the real logic without arcpy. A new arcpy-free `canonical_read.py` gives readers of the widened grain one shared fraction-resolution/QC-exclusion policy; `build_current_event.py` is the reference conversion.

**Tech Stack:** Python 3.10+, stdlib only for all new code. No new packages.

## Global Constraints

- **arcpy-free at import time:** `gdb_schema.py`, `edd_profile.py`, `edd_importer.py`, and the new `canonical_read.py` must import and run without `arcpy`/`arcgis` present. ALL new tests run arcpy-free via `python -m pytest -q`.
- **`compute_unique_key()` must be pure** (no arcpy, no I/O) — it is the seam the key tests reach, because `append_records_idempotent` is arcpy-gated and only reachable through monkeypatched fakes.
- **Text/code key parts default `""`, NEVER `None`** — `_norm_key_part` passes `None` through but uppercases strings, so a `None` default breaks re-import idempotency. `SourceCell`'s existing `""` convention is the pattern. (DATE fields like `AnalysisDate`/`PrepDate` are not key parts and default `None`.)
- **Discriminator values must be deterministic from source data** — never timestamps or counters; the same file must produce the same keys on every re-import.
- **Additive only, one shot per name:** field names, table names, and the `UNIQUE_KEYS` composition frozen here can never be renamed or re-keyed (`create_or_update_gdb_schema` never renames/retypes/drops). Copy names exactly from the spec AMENDMENT.
- **The 11-component key is final** — never widened again: `SiteID, Matrix, LocationID, SampleID, SampleDate, AnalyteCanonicalName, DepthIntervalText, SourceCell, ResultFraction, QCType, MethodDilutionKey`. `ResultBasis` is a data column folded into the `MethodDilutionKey` composite, NOT a 12th component.
- **DO NOT build (deferred to Step 3):** `Env_QCResults` table, VI fields / `Env_VIBuildingSurveys`, `CASNumber`, `QuantitationLimit`, `IsReportable`, the EQuIS `MethodDilutionKey` composite extension (test_type/column_number), NYSDEC anything.
- Reuse existing mechanisms everywhere (ponytail): no new migration framework, no reader Protocol, no `LabEDDProfile` restructure beyond the additive `value_maps` field.
- `from __future__ import annotations` at top of every new module.
- Suite must be green after every task; each task is independently committable.
- Repo writes only on this worktree branch (`worktree-lab-profile-drafting-tooling`) — never main.

---

## File Map

**Created:**
- `docs/adr/0074-canonical-schema-expansion-step1.md` — the ADR *(stale: shipped as `0075-canonical-schema-expansion-step1.md`; 0074 went to the lithology ADR — see banner)*
- `autogis/core/envmon/canonical_read.py` — `canonical_result_rows()` shared read policy
- `tests/envmon/test_gdb_schema_keys.py` — `compute_unique_key` + key-distinctness + backward-compat tests
- `tests/envmon/test_canonical_read.py`

**Modified:**
- `autogis/core/envmon/gdb_schema.py` — 12 new columns in `TABLE_SCHEMAS["Env_AnalyticalResults"]`; 12 defaulted fields on `AnalyticalResultRecord`; 11-component `UNIQUE_KEYS` entry; new `_norm_key_part` + `compute_unique_key()`; delete dead `record_to_row` (~L404-406)
- `autogis/core/envmon/import_to_gdb.py` — import key helpers from `gdb_schema` instead of local `_norm_key_part` (~L114-121) / inline key (~L152)
- `autogis/core/envmon/edd_profile.py` — additive `value_maps: dict[str, dict[str, str]]` + `map_value()`; `matrix_map` kept, merged into `value_maps["matrix"]`
- `autogis/core/envmon/edd_importer.py` — `normalize_edd_rows` resolves + populates the 12 new fields (value-mapped discriminators); `run_edd_import` schema-ensure call + new forwarding stub
- `autogis/core/envmon/table_normalizer.py` — explicitly NO diff needed (all new fields defaulted); verified by tests in Task 4
- `autogis/core/envmon/build_current_event.py` — `LONG_FIELD_MAP` + canonical-read conversion (reference implementation)
- `autogis/core/envmon/upgrade_schema.py` — `SCHEMA_VERSION = "2.2"`
- `tests/envmon/test_edd_profile.py` — value_maps tests
- `tests/envmon/test_edd_importer.py` — new-field population + schema-ensure tests
- `tests/envmon/test_upgrade_schema.py` (or wherever `SCHEMA_VERSION` is asserted; no test pins "2.1" today — add the pin)

**Task list:**
1. ADR-0074 — record the frozen Step-1 decisions
2. `compute_unique_key()` extraction + delete dead `record_to_row`
3. `value_maps` generalization on `LabEDDProfile`
4. 12 new columns: `TABLE_SCHEMAS` + `AnalyticalResultRecord` + both producers + round-trip test
5. `UNIQUE_KEYS` → 11 components + key-distinctness + backward-compat tests + SCHEMA_VERSION 2.2
6. `run_edd_import` schema-ensure fix
7. Canonical-read helper + `build_current_event.py` conversion
8. Self-review

---

## Task 1: ADR — record the frozen Step-1 decisions

**Files:**
- Create: `docs/adr/0074-canonical-schema-expansion-step1.md`

**Interfaces:**
- Consumes: the spec AMENDMENT (`docs/superpowers/specs/2026-07-08-canonical-schema-expansion-design.md`) and the paper-mapping outcome (`docs/superpowers/specs/2026-07-09-edd-paper-mapping-outcome.md`)
- Produces: the durable decision record every later task's names/key must match verbatim

- [ ] **Step 1: Verify the ADR number is actually free**

ADR numbers collide repeatedly in this repo (0034, 0071 twice, 0062, 0063 — see `docs/adr/README.md`). Highest on this branch is `0072`; open PR #209 claims `0073`, so `0074` is the expected next-free — but re-verify at execution time against BOTH main and every open PR's files:

```bash
ls docs/adr/ | sort | tail -5
git fetch origin main --quiet && git ls-tree --name-only origin/main docs/adr/ | sort | tail -5
gh pr list --state open --json number,files --jq '.[] | {number, adr: [.files[].path | select(startswith("docs/adr/"))]}'
```

If `0074` is taken, use the next free number and update the filename everywhere in this plan.

- [ ] **Step 2: Write the ADR**

Create `docs/adr/0074-canonical-schema-expansion-step1.md` following the format in `docs/adr/README.md` / `TEMPLATE.md` (Status: Accepted; Date: execution date; link both spec docs). It MUST record, with exact names:

1. **New `Env_AnalyticalResults` columns (12, all optional/nullable):** `ResultFraction`, `QCType`, `MethodDilutionKey`, `MethodID`, `MethodName`, `AnalysisDate`, `LimitType`, `LabName`, `PrepMethodID`, `PrepDate`, `ResultBasis`, `MethodSpeciation`. Text/code key parts default `""` never `None`; dates default `None`.
2. **The frozen 11-component unique key (never widened again):** `SiteID, Matrix, LocationID, SampleID, SampleDate, AnalyteCanonicalName, DepthIntervalText, SourceCell, ResultFraction, QCType, MethodDilutionKey`.
3. **`MethodDilutionKey` composite convention:** a deterministic load-time composite built by each reader from its format's run discriminators (Step-1/flat-profile composition: the mapped `dilution_factor` column verbatim; Step 2/WQX adds `StatisticalBaseCode` and folds `ResultBasis` when dual-reported; Step 3 extends with EQuIS `test_type`/`column_number`). **`ResultBasis` (wet/dry) is folded into this composite, NOT a 12th key component** (user decision, open-Q#5). Extending the per-reader *value recipe* later is safe — the frozen things are the key composition and column names, not the recipe.
4. **`Qualifier` = final/interpreted qualifier** where the format distinguishes lab vs. validator, else the lab qualifier (user decision, open-Q#4); `IsEstimated` derivation reads it; a separate `InterpretedQualifier` may be added later additively.
5. **Limit-units policy:** convert detection/reporting limits to result units at load, QA-WARN on unconvertible mismatch; no `DetectionLimitUnits` column (deferrable additively — open-Q#6). Convention only in Step 1; first enforcing code is Step 2's WQX reader.
6. **`SCHEMA_VERSION` 2.1 → 2.2** covering exactly this frozen set, via the existing `upgrade_schema.py` / `Env_SchemaVersion` machinery — no new migration framework (ADR-0018 precedent).
7. **The three frozen reader-seam boundaries** (spec §8 + Read-side impact — document explicitly so Step 3 doesn't change them):
   - The flat-row-dict list returned by `read_edd_file` is the **permanent reader contract**; `normalize_edd_rows` never changes for a new format — relational flattening happens inside per-dialect reader modules (readers may inject synthetic composed columns, e.g. a precomposed `MethodDilutionKey`, into row dicts).
   - **`LabEDDProfile` stays flat and 2-sheet-shaped permanently**; Step 3's richer draft-time model is a separate type that projects down to a flat profile at runtime.
   - **The canonical-read policy**: consumers of `Env_AnalyticalResults` must read through the shared canonical-read helper (QC-exclusion + fraction resolution); `build_current_event.py` is the reference implementation. Rerun disambiguation via `IsReportable` defers to Step 3.
8. **The Step-2 merge gate:** these ~11 analyte-pivoting consumers are NOT converted in Step 1 and MUST be audited/converted to the canonical-read helper before Step 2 ships a real WQX import: `dashboard_data_mart.py`, `export_summary.py`, `export_summary_tables.py`, `generate_event_report.py`, `compare_events.py`, `history_report.py`, `schedule_vs_actual.py`, `data_gaps.py`, `apply_screening.py`, `export_geojson.py`, `draft_plume_boundary.py`. (Safe interim: discriminators stay `""` until WQX data arrives.)
9. **Deferred to Step 3** (recorded so nobody re-derives them): `Env_QCResults` (full field list + proposed key live in the paper-mapping doc), VI fields / `Env_VIBuildingSurveys`, `CASNumber`, `QuantitationLimit`, `IsReportable`, EQuIS composite extension, NYSDEC.
10. `compute_unique_key()` extraction, `value_maps` generalization, `run_edd_import` schema-ensure fix, and `record_to_row` deletion as the accompanying code decisions.

- [ ] **Step 3: Add the ADR to the index**

Add a row for 0074 to the index table in `docs/adr/README.md` (match the existing row format).

- [ ] **Step 4: Commit**

```bash
git add docs/adr/0074-canonical-schema-expansion-step1.md docs/adr/README.md
git commit -m "docs(adr): ADR-0074 canonical schema expansion step 1 - frozen columns, 11-part key, conventions"
```

---

## Task 2: `compute_unique_key()` extraction + delete dead `record_to_row`

**Files:**
- Modify: `autogis/core/envmon/gdb_schema.py` (add `_norm_key_part` + `compute_unique_key` near `UNIQUE_KEYS`; delete `record_to_row` at ~L404-406)
- Modify: `autogis/core/envmon/import_to_gdb.py` (delete local `_norm_key_part` ~L114-121; import from `gdb_schema`; use `compute_unique_key` at ~L152)
- Create: `tests/envmon/test_gdb_schema_keys.py`

**Interfaces:**
- Consumes: `gdb_schema.UNIQUE_KEYS` (existing)
- Produces: `compute_unique_key(record_dict: dict, table_name: str) -> tuple` — pure, arcpy-free; **the exact key `append_records_idempotent` dedups on**. Tasks 4-5 test through it. Also `_norm_key_part(v)` re-homed in `gdb_schema.py` (same semantics: date→`"%Y-%m-%d"` string, integral float→int, str→`strip().upper()`, else pass-through).

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_gdb_schema_keys.py`:

```python
from __future__ import annotations

import datetime as dt

from autogis.core.envmon.gdb_schema import UNIQUE_KEYS, compute_unique_key


def _result_dict(**overrides) -> dict:
    d = {
        "SiteID": "S1", "Matrix": "GW", "LocationID": "MW-1",
        "SampleID": "MW-1-0626", "SampleDate": dt.date(2026, 6, 26),
        "AnalyteCanonicalName": "Benzene", "DepthIntervalText": "",
        "SourceCell": "",
    }
    d.update(overrides)
    return d


def test_compute_unique_key_matches_key_fields_order():
    key = compute_unique_key(_result_dict(), "Env_AnalyticalResults")
    assert len(key) == len(UNIQUE_KEYS["Env_AnalyticalResults"])


def test_compute_unique_key_normalizes_like_append():
    # str strip+upper, date -> YYYY-MM-DD string: identical rows re-imported
    # from differently-cased sources must collide.
    a = compute_unique_key(_result_dict(SampleID=" mw-1-0626 "),
                           "Env_AnalyticalResults")
    b = compute_unique_key(_result_dict(SampleID="MW-1-0626"),
                           "Env_AnalyticalResults")
    assert a == b
    assert "2026-06-26" in a


def test_compute_unique_key_missing_field_yields_none_part():
    # d.get(k) semantics preserved: absent key -> None passes through.
    d = _result_dict()
    del d["SourceCell"]
    key = compute_unique_key(d, "Env_AnalyticalResults")
    assert None in key


def test_record_to_row_is_gone():
    import autogis.core.envmon.gdb_schema as gs
    assert not hasattr(gs, "record_to_row")
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_gdb_schema_keys.py -v
```
Expected: FAIL — `ImportError: cannot import name 'compute_unique_key'`.

- [ ] **Step 3: Implement in `gdb_schema.py`**

In `autogis/core/envmon/gdb_schema.py`, immediately after the `UNIQUE_KEYS` dict (~L342), add (needs `import datetime as _dt` at the top of the module — `from datetime import date` is already there but keep both):

```python
def _norm_key_part(v):
    """Normalize one key part exactly as the idempotent-append dedup does."""
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        return v.strip().upper()
    return v


def compute_unique_key(record_dict: dict, table_name: str) -> tuple:
    """The exact key append_records_idempotent dedups on. Pure, arcpy-free —
    the load-bearing seam the synthetic key-distinctness tests exercise."""
    return tuple(_norm_key_part(record_dict.get(k))
                 for k in UNIQUE_KEYS[table_name])
```

Delete the dead `record_to_row` function (~L404-406) — zero callers anywhere (verify: `grep -rn "record_to_row" autogis/ tests/` returns nothing after the delete).

- [ ] **Step 4: Rewire `import_to_gdb.py`**

In `autogis/core/envmon/import_to_gdb.py`:
1. Delete its local `_norm_key_part` (~L114-121).
2. Add to the existing `from .gdb_schema import ...` line (or add a new import): `compute_unique_key, _norm_key_part` (`_existing_key_set` at ~L110 still calls `_norm_key_part` on cursor values — keep that call as-is via the re-homed import).
3. In `append_records_idempotent` (~L152), replace the inline key with:

```python
            key = compute_unique_key(d, table_name)
```

(The surrounding `d = _as_dict(rec)` / `d.setdefault("ImportBatchID", batch_id)` lines stay unchanged.)

- [ ] **Step 5: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_gdb_schema_keys.py -v
```
Expected: PASS (all 4).

- [ ] **Step 6: Full suite — no regressions**

```
python -m pytest -q
```
Expected: green. (`import_to_gdb` is imported arcpy-free by tests even though its cursor functions are arcpy-gated — the import rewiring must not break that.)

- [ ] **Step 7: Commit**

```bash
git add autogis/core/envmon/gdb_schema.py autogis/core/envmon/import_to_gdb.py tests/envmon/test_gdb_schema_keys.py
git commit -m "refactor(envmon): extract pure compute_unique_key into gdb_schema; drop dead record_to_row"
```

---

## Task 3: `value_maps` generalization on `LabEDDProfile`

**Files:**
- Modify: `autogis/core/envmon/edd_profile.py`
- Modify: `autogis/core/envmon/edd_importer.py` (`normalize_edd_rows` matrix lookup only, ~L133-140)
- Test: `tests/envmon/test_edd_profile.py` (extend existing file)

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `LabEDDProfile.value_maps: dict[str, dict[str, str]]` — canonical field name → raw code → canonical value; defaults `{}`; `matrix_map` is merged into `value_maps["matrix"]` in `__post_init__` (existing YAML profiles and direct constructions keep working unchanged)
  - `LabEDDProfile.map_value(field: str, raw: str) -> str` — returns the mapped value or `raw` unchanged. Task 4 calls it for `matrix`, `result_fraction`, `qc_type`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_edd_profile.py` (reuse that file's existing `_write_yaml`-style helpers/imports):

```python
def test_value_maps_defaults_empty_and_maps_pass_through(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)   # existing minimal fixture
    prof = LabEDDProfile.load(p)
    assert prof.map_value("qc_type", "TB") == "TB"        # unmapped: pass-through
    assert prof.map_value("result_fraction", "") == ""


def test_matrix_map_merged_into_value_maps(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)   # MINIMAL_YAML has matrix_map: {WG: GW, ...}
    prof = LabEDDProfile.load(p)
    assert prof.value_maps["matrix"] == prof.matrix_map
    assert prof.map_value("matrix", next(iter(prof.matrix_map))) \
        == prof.matrix_map[next(iter(prof.matrix_map))]


def test_value_maps_loaded_from_yaml(tmp_path):
    yaml_text = MINIMAL_YAML + """
    value_maps:
      qc_type:
        "TB": "TRIP_BLANK"
      result_fraction:
        "T": "Total"
    """
    p = _write_yaml(tmp_path, yaml_text)
    prof = LabEDDProfile.load(p)
    assert prof.map_value("qc_type", "TB") == "TRIP_BLANK"
    assert prof.map_value("result_fraction", "T") == "Total"
    assert prof.value_maps["matrix"]          # matrix_map still merged in
```

(Adjust the YAML-append indentation to match the existing `MINIMAL_YAML` textwrap style in that file.)

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_edd_profile.py -v -k value_maps or matrix_map_merged
```
Expected: FAIL — `AttributeError`/`TypeError` (no `value_maps` field, no `map_value`).

- [ ] **Step 3: Implement in `edd_profile.py`**

In the `LabEDDProfile` dataclass:

```python
    sample_sheet: str = "Samples"            # two_tab_xlsx only
    result_sheet: str = "Results"            # two_tab_xlsx only
    value_maps: dict[str, dict[str, str]] = field(default_factory=dict)
    path: Optional[Path] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        # matrix_map is the legacy spelling of value_maps["matrix"]; merge it
        # so all value lookups go through one place. matrix_map itself is
        # kept untouched for backward compatibility.
        if self.matrix_map and "matrix" not in self.value_maps:
            self.value_maps["matrix"] = self.matrix_map

    def map_value(self, field: str, raw: str) -> str:
        """Canonicalize a raw code via value_maps; pass through if unmapped."""
        return self.value_maps.get(field, {}).get(raw, raw)
```

In `LabEDDProfile.load`, add to the constructor kwargs:

```python
            value_maps=data.get("value_maps", {}),
```

- [ ] **Step 4: Switch `normalize_edd_rows`'s matrix lookup to the generalized path**

In `autogis/core/envmon/edd_importer.py` ~L133-140, replace:

```python
        matrix = profile.matrix_map.get(matrix_raw, matrix_raw)
        if matrix_raw and matrix_raw not in profile.matrix_map:
```

with:

```python
        matrix = profile.map_value("matrix", matrix_raw)
        if matrix_raw and matrix_raw not in profile.value_maps.get("matrix", {}):
```

(QA message text unchanged.)

- [ ] **Step 5: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_edd_profile.py tests/envmon/test_edd_importer.py -v
```
Expected: PASS — including all pre-existing matrix_map tests, untouched.

- [ ] **Step 6: Full suite — no regressions**

```
python -m pytest -q
```
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add autogis/core/envmon/edd_profile.py autogis/core/envmon/edd_importer.py tests/envmon/test_edd_profile.py
git commit -m "feat(edd_profile): generalize matrix_map into value_maps for key-entering code fields"
```

---

## Task 4: 12 new columns — `TABLE_SCHEMAS` + `AnalyticalResultRecord` + producers + round-trip

**Files:**
- Modify: `autogis/core/envmon/gdb_schema.py` (`TABLE_SCHEMAS["Env_AnalyticalResults"]` ~L49-64; `AnalyticalResultRecord` ~L374-389)
- Modify: `autogis/core/envmon/edd_importer.py` (`normalize_edd_rows` optional-field extraction ~L167-179 and record construction ~L225-265)
- Modify: `autogis/core/envmon/table_normalizer.py` — **no code change** (see Step 5)
- Test: `tests/envmon/test_gdb_schema_keys.py` (round-trip test), `tests/envmon/test_edd_importer.py` (field population)

**Interfaces:**
- Consumes: `LabEDDProfile.map_value` (Task 3), `result_parser.parse_excel_date` (existing)
- Produces: `AnalyticalResultRecord` gains, appended **after** `SourceCell` in declaration order, all defaulted:
  `ResultFraction: str = ""`, `QCType: str = ""`, `MethodDilutionKey: str = ""`, `MethodID: str = ""`, `MethodName: str = ""`, `AnalysisDate: Optional[date] = None`, `LimitType: str = ""`, `LabName: str = ""`, `PrepMethodID: str = ""`, `PrepDate: Optional[date] = None`, `ResultBasis: str = ""`, `MethodSpeciation: str = ""`.
  New optional canonical profile-column names resolvable by `normalize_edd_rows`: `result_fraction`, `qc_type`, `dilution_factor`, `method` (existing), `method_name`, `analysis_date`, `limit_type`, `lab_name`, `prep_method`, `prep_date`, `result_basis`, `method_speciation`. Tasks 5 and 7 rely on these exact field names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_gdb_schema_keys.py`:

```python
from dataclasses import asdict
from autogis.core.envmon.gdb_schema import (
    TABLE_SCHEMAS, AnalyticalResultRecord,
)

_NEW_FIELDS = [
    "ResultFraction", "QCType", "MethodDilutionKey", "MethodID",
    "MethodName", "AnalysisDate", "LimitType", "LabName",
    "PrepMethodID", "PrepDate", "ResultBasis", "MethodSpeciation",
]


def _full_record(**overrides) -> AnalyticalResultRecord:
    base = dict(
        ImportBatchID="B1", SiteID="S1", Matrix="GW", LocationID="MW-1",
        SampleID="MW-1-0626", ParentSampleID="",
        SampleDate=dt.date(2026, 6, 26), DepthTop_ft=None,
        DepthBottom_ft=None, DepthIntervalText="", AnalyticalGroup="",
        MethodGroup="", AnalyteName="Benzene",
        AnalyteCanonicalName="Benzene", AnalyteAbbreviation="Benz",
        ResultRawText="0.5", ResultNumeric=0.5, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="", IsNonDetect=0,
        IsDetected=1, IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=None,
        ScreeningLevelSource="", ExceedsScreeningLevel=None,
        DisplayText="0.5", DisplayColorClass="", SourceWorkbook="w",
        SourceSheet="s", SourceRow=2, SourceColumn="", SourceCell="",
    )
    base.update(overrides)
    return AnalyticalResultRecord(**base)


def test_new_fields_default_empty_or_none():
    rec = _full_record()   # legacy construction: no new kwargs
    d = asdict(rec)
    for f in _NEW_FIELDS:
        assert d[f] in ("", None), f
    # key discriminators specifically must be "" (idempotency), never None
    for f in ("ResultFraction", "QCType", "MethodDilutionKey"):
        assert d[f] == "", f


def test_field_projection_round_trip_every_new_field():
    # A dataclass attr whose name mismatches TABLE_SCHEMAS silently projects
    # to None on insert — assert exact name parity, both directions.
    rec = _full_record(
        ResultFraction="Total", QCType="FIELD_DUP", MethodDilutionKey="D5",
        MethodID="EPA 8260", MethodName="VOCs by GC/MS",
        AnalysisDate=dt.date(2026, 6, 27), LimitType="MDL", LabName="Pace",
        PrepMethodID="5030B", PrepDate=dt.date(2026, 6, 26),
        ResultBasis="DRY", MethodSpeciation="as N",
    )
    d = asdict(rec)
    schema_names = [f[0] for f in TABLE_SCHEMAS["Env_AnalyticalResults"]]
    # exact parity: every schema column has a dataclass attr and vice versa
    assert set(d) == set(schema_names)
    # every populated new field survives schema-ordered row projection
    row = [d.get(f) for f in schema_names]
    projected = dict(zip(schema_names, row))
    for f in _NEW_FIELDS:
        assert projected[f] == d[f], f
```

Append to `tests/envmon/test_edd_importer.py` (reuse that file's existing profile/fixture helpers — it already builds `LabEDDProfile` objects and row dicts for `normalize_edd_rows`; extend a copy of its minimal profile with the new column mappings and `value_maps`):

```python
def test_normalize_edd_rows_populates_new_fields(qa_and_dicts):
    # Build a profile mapping the new canonical columns (exact names below),
    # with value_maps normalizing fraction + qc_type codes.
    profile = _make_profile(  # existing helper/factory in this file
        columns={
            **_BASE_COLUMNS,
            "result_fraction": "Fraction", "qc_type": "QC",
            "dilution_factor": "Dil", "method": "Method",
            "method_name": "MethodName", "analysis_date": "AnalDate",
            "limit_type": "LimType", "lab_name": "Lab",
            "prep_method": "PrepMeth", "prep_date": "PrepDate",
            "result_basis": "Basis", "method_speciation": "Speciation",
        },
        value_maps={"result_fraction": {"T": "Total"},
                    "qc_type": {"TB": "TRIP_BLANK"}},
    )
    row = {**_BASE_ROW, "Fraction": "T", "QC": "TB", "Dil": "5",
           "Method": "EPA 8260", "MethodName": "VOCs by GC/MS",
           "AnalDate": "06/27/2026", "LimType": "MDL", "Lab": "Pace",
           "PrepMeth": "5030B", "PrepDate": "06/26/2026", "Basis": "DRY",
           "Speciation": "as N"}
    _, results = normalize_edd_rows([row], profile, "S1", "B1",
                                    *qa_and_dicts)
    r = results[0]
    assert r.ResultFraction == "Total"          # value-mapped
    assert r.QCType == "TRIP_BLANK"             # value-mapped
    assert r.MethodDilutionKey == "5"
    assert r.MethodID == "EPA 8260"
    assert r.MethodName == "VOCs by GC/MS"
    assert r.AnalysisDate is not None
    assert r.LimitType == "MDL"
    assert r.LabName == "Pace"
    assert r.PrepMethodID == "5030B"
    assert r.PrepDate is not None
    assert r.ResultBasis == "DRY"
    assert r.MethodSpeciation == "as N"


def test_normalize_edd_rows_unmapped_new_columns_default_empty(qa_and_dicts):
    # A profile with NO new column mappings (today's TestAmerica shape)
    # must produce "" discriminators / None dates — bit-identical dedup.
    profile = _make_profile(columns=_BASE_COLUMNS)
    _, results = normalize_edd_rows([dict(_BASE_ROW)], profile, "S1", "B1",
                                    *qa_and_dicts)
    r = results[0]
    assert (r.ResultFraction, r.QCType, r.MethodDilutionKey) == ("", "", "")
    assert r.AnalysisDate is None and r.PrepDate is None
```

(`_make_profile` / `_BASE_COLUMNS` / `_BASE_ROW` / `qa_and_dicts`: use whatever the existing test file's fixtures are actually named — mirror its established pattern rather than inventing parallel fixtures. The assertions above are the contract.)

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_gdb_schema_keys.py tests/envmon/test_edd_importer.py -v
```
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'ResultFraction'` / attribute errors.

- [ ] **Step 3: Implement schema + dataclass in `gdb_schema.py`**

In `TABLE_SCHEMAS["Env_AnalyticalResults"]` (~L49-64), change the closing of the list from `("DisplayText", T, 64), ("DisplayColorClass", T, 16)] + _SRC` to:

```python
        ("DisplayText", T, 64), ("DisplayColorClass", T, 16),
        # --- Step-1 canonical expansion (ADR-0074, SCHEMA_VERSION 2.2) ---
        ("ResultFraction", T, 32), ("QCType", T, 32),
        ("MethodDilutionKey", T, 64), ("MethodID", T, 64),
        ("MethodName", T, 128), ("AnalysisDate", DT, None),
        ("LimitType", T, 32), ("LabName", T, 128),
        ("PrepMethodID", T, 64), ("PrepDate", DT, None),
        ("ResultBasis", T, 16), ("MethodSpeciation", T, 32)] + _SRC,
```

In `AnalyticalResultRecord` (~L374-389), append after `SourceColumn: str; SourceCell: str`:

```python
    # --- Step-1 canonical expansion (ADR-0074). Key discriminators default
    # "" (never None — idempotency); dates are not key parts, default None.
    ResultFraction: str = ""
    QCType: str = ""
    MethodDilutionKey: str = ""
    MethodID: str = ""
    MethodName: str = ""
    AnalysisDate: Optional[date] = None
    LimitType: str = ""
    LabName: str = ""
    PrepMethodID: str = ""
    PrepDate: Optional[date] = None
    ResultBasis: str = ""
    MethodSpeciation: str = ""
```

- [ ] **Step 4: Populate from `normalize_edd_rows` in `edd_importer.py`**

In the `--- optional fields ---` block (~L167-179), after the existing `method` / `lab_sid` lines, add:

```python
        fraction   = profile.map_value(
            "result_fraction", profile.resolve_column(row, "result_fraction") or "")
        qc_type    = profile.map_value(
            "qc_type", profile.resolve_column(row, "qc_type") or "")
        # Step-1 composition: the mapped dilution_factor column verbatim.
        # Readers with richer run discriminators (Step 2/3) precompose a
        # value and map method_dilution_key-equivalent columns to it via the
        # profile — deterministic from source either way (ADR-0074).
        dilution   = (profile.resolve_column(row, "dilution_factor") or "").strip()
        method_name = profile.resolve_column(row, "method_name") or ""
        analysis_date = parse_excel_date(
            profile.resolve_column(row, "analysis_date") or "")
        limit_type = profile.resolve_column(row, "limit_type") or ""
        lab_name   = profile.resolve_column(row, "lab_name") or ""
        prep_method = profile.resolve_column(row, "prep_method") or ""
        prep_date  = parse_excel_date(
            profile.resolve_column(row, "prep_date") or "")
        result_basis = profile.resolve_column(row, "result_basis") or ""
        speciation = profile.resolve_column(row, "method_speciation") or ""
```

In the `AnalyticalResultRecord(...)` construction (~L225-265), after `SourceCell="",` add:

```python
            ResultFraction=fraction,
            QCType=qc_type,
            MethodDilutionKey=dilution,
            MethodID=method,
            MethodName=method_name,
            AnalysisDate=analysis_date,
            LimitType=limit_type,
            LabName=lab_name,
            PrepMethodID=prep_method,
            PrepDate=prep_date,
            ResultBasis=result_basis,
            MethodSpeciation=speciation,
```

(`method` is already resolved at ~L169 and previously unused in the record — it now lands in `MethodID`. `parse_excel_date` is already imported.)

- [ ] **Step 5: `table_normalizer.py` — confirm no diff needed**

The workbook path (`normalize_matrix_table` ~L194) has **no source columns** for any new field; because every new dataclass field is defaulted, its exhaustive-kwargs construction and all ~13 test-factory helpers that build `AnalyticalResultRecord` (e.g. in `tests/envmon/test_export_summary.py`, `tests/test_apply_screening.py`, `tests/test_compare_events.py`, `tests/test_history_report.py`, `tests/test_data_gaps.py`, `tests/test_export_geojson.py`, `tests/test_schedule_vs_actual.py`, `tests/envmon/conftest.py`, …) compile and behave identically with zero changes — that IS the update, by design (spec Approach: "any new required field breaks both producers and every factory", hence defaults). Prove it with the full suite in Step 7; do not edit those files unless the suite says otherwise.

- [ ] **Step 6: Run the new tests**

```
python -m pytest tests/envmon/test_gdb_schema_keys.py tests/envmon/test_edd_importer.py -v
```
Expected: PASS.

- [ ] **Step 7: Full suite — proves producer/factory back-compat**

```
python -m pytest -q
```
Expected: green with no edits outside the files in this task's header.

- [ ] **Step 8: Commit**

```bash
git add autogis/core/envmon/gdb_schema.py autogis/core/envmon/edd_importer.py tests/envmon/test_gdb_schema_keys.py tests/envmon/test_edd_importer.py
git commit -m "feat(envmon): add 12 frozen Step-1 columns to Env_AnalyticalResults + wire EDD producer (ADR-0074)"
```

---

## Task 5: 11-component `UNIQUE_KEYS` + key-distinctness + backward-compat + SCHEMA_VERSION 2.2

**Files:**
- Modify: `autogis/core/envmon/gdb_schema.py` (`UNIQUE_KEYS` ~L337-339)
- Modify: `autogis/core/envmon/upgrade_schema.py` (L13)
- Test: `tests/envmon/test_gdb_schema_keys.py` (extend), `tests/envmon/test_upgrade_schema.py` (extend — if that file doesn't exist, put the version assert in `test_gdb_schema_keys.py`)

**Interfaces:**
- Consumes: `compute_unique_key` (Task 2), the new record fields (Task 4)
- Produces: `UNIQUE_KEYS["Env_AnalyticalResults"]` == the frozen 11 components in this exact order; `upgrade_schema.SCHEMA_VERSION == "2.2"`. The arcpy append/upgrade paths pick both up with zero further code (`append_records_idempotent` and `_existing_key_set` read `UNIQUE_KEYS`; `upgrade_gdb_schema` reads `SCHEMA_VERSION` and `TABLE_SCHEMAS`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_gdb_schema_keys.py`:

```python
def test_unique_key_is_the_frozen_11(): 
    assert UNIQUE_KEYS["Env_AnalyticalResults"] == [
        "SiteID", "Matrix", "LocationID", "SampleID", "SampleDate",
        "AnalyteCanonicalName", "DepthIntervalText", "SourceCell",
        "ResultFraction", "QCType", "MethodDilutionKey",
    ]


def _key(**ov):
    d = _result_dict(ResultFraction="", QCType="", MethodDilutionKey="")
    d.update(ov)
    return compute_unique_key(d, "Env_AnalyticalResults")


def test_fraction_pair_is_distinct():
    # WQX Total vs Dissolved of the same sample/analyte — the collision that
    # motivated this whole spec — must produce distinct keys.
    assert _key(ResultFraction="Total") != _key(ResultFraction="Dissolved")


def test_qc_flagged_row_distinct_from_parent():
    assert _key(QCType="") != _key(QCType="FIELD_DUP")


def test_dilution_rerun_distinct():
    assert _key(MethodDilutionKey="") != _key(MethodDilutionKey="D5")


def test_legacy_shape_key_unchanged():
    # Records in today's shape (discriminators absent -> defaulted "") must
    # produce the OLD 8-part key extended by three "" parts — same relative
    # uniqueness, so re-imports of pre-2.2 data still dedup identically.
    legacy = compute_unique_key(_result_dict(), "Env_AnalyticalResults")
    explicit = _key()
    # _result_dict has no discriminator keys -> None; records always carry ""
    assert explicit[:8] == legacy[:8]
    assert explicit[8:] == ("", "", "")


def test_backward_compat_testamerica_fixture_dedup_identical():
    # Run the existing TestAmerica EDD fixture through the real normalizer
    # and the widened key: every record must carry "" discriminators, and
    # distinct-key count must equal the record count (no new collisions,
    # no new splits).
    from dataclasses import asdict as _as
    from autogis.core.envmon.edd_importer import normalize_edd_rows
    # Reuse the fixture-loading pattern from tests/envmon/test_edd_importer.py
    # (tests/envmon/fixtures/edd/testamerica_simple.csv + the testamerica
    # profile) — same profile, same csv, same qa/dict fixtures.
    samples, results = _normalize_testamerica_fixture()
    keys = [compute_unique_key(_as(r), "Env_AnalyticalResults")
            for r in results]
    assert len(set(keys)) == len(keys)
    assert all(k[8:] == ("", "", "") for k in keys)
```

(`_normalize_testamerica_fixture()` — small local helper that loads `autogis/config/lab_profiles/testamerica.yaml` + `tests/envmon/fixtures/edd/testamerica_simple.csv` exactly as `tests/envmon/test_edd_importer.py` already does; copy that file's established loading code.)

Add the version pin (in `tests/envmon/test_upgrade_schema.py` if present, else here):

```python
def test_schema_version_is_2_2():
    from autogis.core.envmon.upgrade_schema import SCHEMA_VERSION
    assert SCHEMA_VERSION == "2.2"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_gdb_schema_keys.py -v
```
Expected: `test_unique_key_is_the_frozen_11`, the distinctness trio, and the version pin FAIL (8-part key, version "2.1"); note `test_fraction_pair_is_distinct` fails precisely because today the pair COLLIDES — the bug being fixed.

- [ ] **Step 3: Widen the key in `gdb_schema.py`**

Replace the `Env_AnalyticalResults` entry in `UNIQUE_KEYS` (~L337-339) with:

```python
    "Env_AnalyticalResults": ["SiteID", "Matrix", "LocationID", "SampleID",
                              "SampleDate", "AnalyteCanonicalName",
                              "DepthIntervalText", "SourceCell",
                              "ResultFraction", "QCType",
                              "MethodDilutionKey"],
```

- [ ] **Step 4: Bump `SCHEMA_VERSION` in `upgrade_schema.py` (L13)**

```python
SCHEMA_VERSION = "2.2"
```

(Nothing else — `upgrade_gdb_schema` + `Env_SchemaVersion` + the wired `upgrade-schema` CLI already handle the rest; the 12 new columns are picked up additively by `create_or_update_gdb_schema`.)

- [ ] **Step 5: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_gdb_schema_keys.py -v
```
Expected: PASS (all).

- [ ] **Step 6: Full suite — no regressions**

```
python -m pytest -q
```
Expected: green (workbook-path fixtures in `tests/envmon/conftest.py` and the import tests must be unaffected because their records all carry `""` discriminators).

- [ ] **Step 7: Commit**

```bash
git add autogis/core/envmon/gdb_schema.py autogis/core/envmon/upgrade_schema.py tests/envmon/test_gdb_schema_keys.py
git commit -m "feat(envmon): widen Env_AnalyticalResults dedup key to frozen 11 components; SCHEMA_VERSION 2.2 (ADR-0074)"
```

---

## Task 6: `run_edd_import` schema-ensure fix

**Files:**
- Modify: `autogis/core/envmon/edd_importer.py` (stub block ~L275-292; `run_edd_import` ~L313-318)
- Test: `tests/envmon/test_edd_importer.py` (extend — mirror its existing `run_edd_import` lifecycle test at ~L265-308, which monkeypatches the module-level stubs)

**Interfaces:**
- Consumes: `gdb_schema.create_or_update_gdb_schema` (existing, arcpy-gated)
- Produces: `run_edd_import` self-heals an un-upgraded GDB exactly like `run_import` (`import_to_gdb.py:279`) — without this, `_existing_key_set`'s SearchCursor on the three new key columns crashes every EDD import against a pre-2.2 GDB.

- [ ] **Step 1: Write the failing test**

Append to `tests/envmon/test_edd_importer.py`, following the exact monkeypatch pattern of its existing `run_edd_import` lifecycle test (~L265-308) — patch every stub that test patches, plus the new one:

```python
def test_run_edd_import_ensures_schema_first(monkeypatch, tmp_path, ...):
    calls = []
    monkeypatch.setattr(edd_importer, "create_or_update_gdb_schema",
                        lambda gdb, qa=None: calls.append("schema"))
    monkeypatch.setattr(edd_importer, "create_edd_import_batch",
                        lambda *a, **k: (calls.append("batch"), "B1")[1])
    monkeypatch.setattr(edd_importer, "append_records_idempotent",
                        lambda *a, **k: (calls.append("append"), (0, 0))[1])
    monkeypatch.setattr(edd_importer, "finalize_batch", lambda *a, **k: None)
    monkeypatch.setattr(edd_importer, "write_qa_to_gdb", lambda *a, **k: 0)
    # ... invoke run_edd_import with the fixture csv/profile exactly as the
    # existing lifecycle test does ...
    assert calls[0] == "schema"          # schema ensured before anything else
    assert "batch" in calls and "append" in calls
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/envmon/test_edd_importer.py -k ensures_schema -v
```
Expected: FAIL — `AttributeError: module ... has no attribute 'create_or_update_gdb_schema'`.

- [ ] **Step 3: Implement**

In `edd_importer.py`, add to the module-level forwarding-stub block (~L275-292, same shape as the four existing stubs so it stays monkeypatchable and arcpy-free at import time):

```python
def create_or_update_gdb_schema(gdb_path, qa=None):  # pragma: no cover
    from autogis.core.envmon.gdb_schema import create_or_update_gdb_schema as _f
    return _f(gdb_path, qa=qa)
```

In `run_edd_import` (~L313-318), immediately after `gdb_path = Path(gdb_path)` and **before** `create_edd_import_batch`:

```python
    # Self-heal the GDB schema (mirrors run_import, import_to_gdb.py:279):
    # the widened key columns must exist before _existing_key_set reads them.
    create_or_update_gdb_schema(gdb_path)
```

- [ ] **Step 4: Run test to confirm it passes**

```
python -m pytest tests/envmon/test_edd_importer.py -k ensures_schema -v
```
Expected: PASS. Also confirm the module still imports arcpy-free: `python -c "import autogis.core.envmon.edd_importer"`.

- [ ] **Step 5: Full suite — no regressions**

```
python -m pytest -q
```
Expected: green — the pre-existing lifecycle test must be updated ONLY if it asserts an exact stub-call sequence (add the schema stub patch there too if it fails on the new unpatched call).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/edd_importer.py tests/envmon/test_edd_importer.py
git commit -m "fix(edd_importer): ensure GDB schema at top of run_edd_import (mirrors run_import)"
```

---

## Task 7: Canonical-read helper + `build_current_event.py` reference conversion

**Files:**
- Create: `autogis/core/envmon/canonical_read.py`
- Create: `tests/envmon/test_canonical_read.py`
- Modify: `autogis/core/envmon/build_current_event.py` (`LONG_FIELD_MAP` ~L357-368; `build_current_event_wide` ~L402-408)

**Interfaces:**
- Consumes: row dicts shaped like `read_long_results` output (plain dicts with `LocationID`, `SampleID`, `SampleDate`, `AnalyteCanonicalName`, `DepthIntervalText`, plus new `ResultFraction`, `QCType`), `QACollector`
- Produces:
  `canonical_result_rows(rows: Sequence[dict], qa: QACollector, fraction_preference: Sequence[str] = ("Total", "Dissolved")) -> list[dict]`
  — Step-1 frozen behavior ONLY: (1) exclude rows whose `QCType` is non-empty; (2) per result group, resolve to a single fraction. Rerun disambiguation via `IsReportable` is **Step 3** — multiple `MethodDilutionKey` rows within the chosen fraction pass through (downstream `build_wide_rows` already QA-warns `multiple_results_after_rules`). This is the ONE shared read policy the Step-2 merge gate converts the other ~11 consumers to (see ADR item 8) — those conversions are **not** done here.

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_canonical_read.py`:

```python
from __future__ import annotations

from autogis.core.common.qa import QACollector
from autogis.core.envmon.canonical_read import canonical_result_rows


def _row(**ov) -> dict:
    d = {"LocationID": "MW-1", "SampleID": "MW-1-0626",
         "SampleDate": "2026-06-26", "AnalyteCanonicalName": "Arsenic",
         "DepthIntervalText": "", "ResultFraction": "", "QCType": "",
         "NumericValue": 1.0}
    d.update(ov)
    return d


def test_qc_rows_excluded():
    qa = QACollector()
    rows = [_row(), _row(QCType="TRIP_BLANK", NumericValue=0.0)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1 and out[0]["QCType"] == ""


def test_total_dissolved_pair_resolves_to_total():
    qa = QACollector()
    rows = [_row(ResultFraction="Total", NumericValue=2.0),
            _row(ResultFraction="Dissolved", NumericValue=1.5)]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1 and out[0]["ResultFraction"] == "Total"
    assert any(r.category == "fraction_resolved" for r in qa.records)


def test_single_fraction_untouched_even_if_unpreferred():
    qa = QACollector()
    rows = [_row(ResultFraction="Dissolved")]
    assert canonical_result_rows(rows, qa) == rows


def test_unpreferred_multi_fraction_falls_back_deterministically():
    qa = QACollector()
    rows = [_row(ResultFraction="Suspended"),
            _row(ResultFraction="Extractable")]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 1
    assert out[0]["ResultFraction"] == "Extractable"   # sorted()[0]


def test_legacy_rows_pass_through_unchanged():
    # Pre-2.2 rows (both discriminators "") — including rows where the keys
    # are absent entirely — must pass through untouched: no behavior change
    # until Step 2 populates real fractions.
    qa = QACollector()
    legacy = {"LocationID": "MW-2", "SampleID": "S", "SampleDate": "d",
              "AnalyteCanonicalName": "Lead", "DepthIntervalText": ""}
    rows = [_row(), legacy]
    assert canonical_result_rows(rows, qa) == rows
    assert not qa.records


def test_groups_are_independent():
    # A Total/Dissolved pair on one analyte must not affect another
    # analyte's single row in the same sample.
    qa = QACollector()
    rows = [_row(ResultFraction="Total"), _row(ResultFraction="Dissolved"),
            _row(AnalyteCanonicalName="Lead")]
    out = canonical_result_rows(rows, qa)
    assert len(out) == 2
```

(Adjust `qa.records` / `r.category` access to the real `QACollector` API — same accessors the other envmon tests use.)

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_canonical_read.py -v
```
Expected: FAIL — `ModuleNotFoundError: ... canonical_read`.

- [ ] **Step 3: Implement `canonical_read.py`**

Create `autogis/core/envmon/canonical_read.py`:

```python
"""Shared canonical-read policy for the widened Env_AnalyticalResults grain.

After Step 1, one (sample, analyte, depth) may legitimately hold multiple
rows split by ResultFraction / QCType / MethodDilutionKey. Every consumer
that pivots or groups results by analyte must read through this helper or
it will double-count / silently drop data the moment Step 2 imports real
WQX fractions (ADR-0074). Step-1 policy: drop lab/field-QC-flagged rows,
resolve each group to a single fraction. MethodDilutionKey rerun
disambiguation (IsReportable) is deferred to Step 3.

arcpy-free: operates on plain row dicts.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

#: Default fraction preference, most-canonical first. "" (legacy /
#: unfractionated) never competes: single-fraction groups pass through.
DEFAULT_FRACTION_PREFERENCE: tuple[str, ...] = ("Total", "Dissolved")


def _group_key(r: dict) -> Tuple:
    return (r.get("LocationID"), r.get("SampleID"), str(r.get("SampleDate")),
            r.get("AnalyteCanonicalName"),
            str(r.get("DepthIntervalText") or ""))


def canonical_result_rows(
    rows: Sequence[dict],
    qa: QACollector,
    fraction_preference: Sequence[str] = DEFAULT_FRACTION_PREFERENCE,
) -> List[dict]:
    """Return rows filtered to the canonical-read policy (order preserved)."""
    kept: List[dict] = []
    qc_dropped = 0
    for r in rows:
        if (r.get("QCType") or ""):
            qc_dropped += 1
            continue
        kept.append(r)
    if qc_dropped:
        qa.add(SEV_INFO, "qc_rows_excluded",
               f"{qc_dropped} QCType-flagged row(s) excluded by the "
               "canonical-read policy.")

    fractions_by_group: Dict[Tuple, set] = defaultdict(set)
    for r in kept:
        fractions_by_group[_group_key(r)].add(r.get("ResultFraction") or "")

    chosen: Dict[Tuple, str] = {}
    for key, fracs in fractions_by_group.items():
        if len(fracs) == 1:
            continue                      # nothing to resolve
        pick = next((p for p in fraction_preference if p in fracs),
                    sorted(fracs)[0])
        chosen[key] = pick
        qa.add(SEV_WARNING if pick not in fraction_preference else SEV_INFO,
               "fraction_resolved",
               f"{key[0]} {key[3]}: fractions {sorted(fracs)} resolved to "
               f"'{pick}' by the canonical-read policy.",
               location_id=key[0], analyte_name=key[3])

    out = [r for r in kept
           if _group_key(r) not in chosen
           or (r.get("ResultFraction") or "") == chosen[_group_key(r)]]
    return out
```

(Match `qa.add(...)` keyword names to the real `QACollector.add` signature — same call shape `edd_importer.py` uses.)

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_canonical_read.py -v
```
Expected: PASS.

- [ ] **Step 5: Convert `build_current_event.py` (the reference consumer)**

1. In `LONG_FIELD_MAP` (~L357-368) append two entries:

```python
    ("ResultFraction", "ResultFraction"), ("QCType", "QCType"),
```

2. In `build_current_event_wide` (~L402), immediately after `rows = read_long_results(gdb, site_id, matrix)` and before the `if not rows:` check:

```python
    from .canonical_read import canonical_result_rows
    rows = canonical_result_rows(rows, qa)
```

(Import at top of file with the other relative imports is fine too — keep it consistent with the module's style.)

Note: `read_long_results` now SearchCursors two new columns, so this LOCAL tool requires a 2.2-upgraded GDB — which every import path now self-heals (Tasks 5-6) and `upgrade-schema` provides for existing GDBs. No extra handling.

3. Add a pure integration test to `tests/envmon/test_canonical_read.py` proving the confirmed-broken pivot is fixed (spec Testing #5) — synthetic Total/Dissolved pair through the same pipeline stage order as `build_current_event_wide`:

```python
def test_pivot_no_longer_drops_or_double_counts_fractions():
    from autogis.core.envmon.build_current_event import build_wide_rows
    qa = QACollector()
    pair = [
        _row(ResultFraction="Total", NumericValue=2.0, IsDetected=1,
             DisplayText="2.0"),
        _row(ResultFraction="Dissolved", NumericValue=1.5, IsDetected=1,
             DisplayText="1.5"),
    ]
    canonical = canonical_result_rows(pair, qa)
    wide = build_wide_rows(canonical, ["Arsenic"], qa)
    assert len(wide) == 1
    assert wide[0]["results"]["Arsenic"]["DisplayText"] == "2.0"   # Total won
    # and the old silent-overwrite warning did NOT fire
    assert not any(r.category == "multiple_results_after_rules"
                   for r in qa.records)
```

- [ ] **Step 6: Run tests, then full suite**

```
python -m pytest tests/envmon/test_canonical_read.py -v
python -m pytest -q
```
Expected: PASS / green. Also confirm arcpy-free import: `python -c "import autogis.core.envmon.canonical_read"`.

- [ ] **Step 7: Commit**

```bash
git add autogis/core/envmon/canonical_read.py autogis/core/envmon/build_current_event.py tests/envmon/test_canonical_read.py
git commit -m "feat(envmon): shared canonical-read helper (QC exclusion + fraction resolution); convert build_current_event (ADR-0074)"
```

---

## Step-2 merge gate (named, NOT converted here)

These ~11 analyte-pivoting consumers of `Env_AnalyticalResults` keep working unchanged while discriminators stay `""`, but **must be audited and converted to `canonical_result_rows` before Step 2 ships a real WQX import** (recorded in ADR-0074 item 8): `dashboard_data_mart.py`, `export_summary.py`, `export_summary_tables.py`, `generate_event_report.py`, `compare_events.py`, `history_report.py`, `schedule_vs_actual.py`, `data_gaps.py`, `apply_screening.py`, `export_geojson.py`, `draft_plume_boundary.py`. Do not convert any of them in Step 1.

---

## Self-Review

**Spec coverage (AMENDMENT = authoritative):**
- ADR with all frozen decisions + 3 reader-seam boundaries → Task 1
- 12 columns, `""`/`None` defaults, dataclass + `TABLE_SCHEMAS` + both producers + factories → Task 4 (table_normalizer + factories intentionally zero-diff via defaults, verified by suite; edd_importer explicitly wired)
- Frozen 11-component key → Task 5; `compute_unique_key()` extraction → Task 2; `value_maps` → Task 3; `run_edd_import` schema-ensure → Task 6; `SCHEMA_VERSION` 2.2 → Task 5; canonical-read helper + `build_current_event` reference conversion → Task 7; `record_to_row` deletion → Task 2; Step-2 merge gate named, not built → gate section + ADR item 8.
- Spec Testing plan: key distinctness via `compute_unique_key` (T5), TestAmerica backward-compat (T5), field-projection round-trip (T4), schema-ensure test (T6), Total/Dissolved pivot test (T7). `Env_QCResults`/VI round-trips correctly ABSENT (Step 3 per AMENDMENT).
- Deferred list honored: no `Env_QCResults`, no VI, no `CASNumber`/`QuantitationLimit`/`IsReportable`, no EQuIS composite extension, no NYSDEC anywhere in the tasks.

**Type consistency checked:** `compute_unique_key(dict, str) -> tuple` used identically in Tasks 2/5; `map_value(field, raw)` defined in Task 3, consumed in Task 4; dataclass field names exactly match `TABLE_SCHEMAS` entries (round-trip test enforces set-equality); `canonical_result_rows(rows, qa, fraction_preference)` consistent between Task 7 steps; Task 2's `_result_dict` (no discriminators → `None` key parts) deliberately contrasted with real records (`""`) in Task 5's `test_legacy_shape_key_unchanged`.

**Known approximations (implementer notes, not gaps):**
- Tests that extend `tests/envmon/test_edd_importer.py` / `test_edd_profile.py` reference that file's existing fixtures by role (`_make_profile`, `MINIMAL_YAML`, the lifecycle-test monkeypatch pattern) rather than guessed exact names — the assertions given are the contract; reuse the file's real helpers.
- `qa.add(...)`/`qa.records`/`r.category` accessor spellings: match the real `QACollector` API (same call shape as `edd_importer.py`).
- ADR number `0074` verified free as of 2026-07-09 (branch max 0072, PR #209 claims 0073) — re-verify at execution (Task 1 Step 1); collisions recur in this repo.
- Task 4's Step-1 `MethodDilutionKey` composition is intentionally just the mapped `dilution_factor` value — richer composition is a per-reader recipe (Step 2/3), and the ADR records that extending the recipe is safe while the column name/key composition are frozen.
