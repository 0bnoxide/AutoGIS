# Lab EDD Profile Drafting & Management Tooling — Design (Slice 1: Core + CLI)

**Date:** 2026-07-08
**Status:** Proposed
**Tool:** extends Tool 2.3 (Lab EDD Importer, ADR-0016)
**Slice:** 1 of 2 — core logic + CLI only. GUI browser/drafting dialog is Slice 2
(separate spec, built after this lands so it can reuse the core function).

---

## Problem

`LabEDDProfile` (ADR-0016) already gives every lab a per-lab YAML mapping into the
unified `Env_Samples` / `Env_AnalyticalResults` schema — the "unified schema" target
already exists. The gap is in *building and managing* the profiles themselves:

- Exactly one profile is checked in (`autogis/config/lab_profiles/testamerica.yaml`),
  hand-authored. Every new lab means manually reading their EDD export and writing
  the column-mapping YAML from scratch.
- `draft-parser-profile` (Tool 2.1) already does heuristic drafting for the *other*
  profile type (`ParserProfile`, field-data workbooks) — there is no equivalent for
  `LabEDDProfile`.
- There's no way to list what profiles exist, or validate one is well-formed, without
  opening each YAML by hand and reading `edd_profile.py` to know what "well-formed"
  means. (`validate_edd_profile()` already exists as a function — it's just not
  exposed anywhere.)
- The flat `lab_profiles/` directory has no room to carry a reference sample
  alongside a profile, which makes profiles hard to sanity-check against the real
  export format they were drafted from.

## Non-goals

- **AI-assisted drafting.** Falls under CLAUDE.md's §11 phase-gated group (deferred
  pending the LLM seam design). Not reopened by this work. The core function's
  interface is deliberately structured so an AI-assisted drafter could later replace
  or augment the synonym-matching step without changing its callers — but nothing
  AI-related ships here.
- **GUI browser / interactive drafting dialog.** Slice 2. This spec covers only the
  headless core + CLI.
- **Per-lab subdirectory contents beyond profile + one sample fixture.** No fixture
  versioning, no multi-format-per-lab support yet.

---

## Approach

**Chosen: synonym-list header matching**, same heuristic spirit as
`draft-parser-profile`'s structure detection (`excel_workbook_inspector.py`) — no new
dependency, deterministic, easy to unit test against a field set this small: 9
required canonical columns (`_REQUIRED_COLUMNS` in `edd_profile.py`: `sample_id`,
`location_id`, `event_date`, `matrix`, `analyte`, `result`, `units`, `qualifier`,
`reporting_limit`) plus 4 optional resolvable fields the importer also looks up
(`method`, `lab_sample_id`, `depth_top_ft`, `depth_bot_ft` — see `edd_importer.py`
lines 168-176). The drafter must cover all 13, distinguishing required vs optional
in its output.

**Rejected: fuzzy string matching (`difflib.get_close_matches`).** Adds
nondeterminism and a harder-to-test surface for marginal gain over an explicit
synonym list, given the canonical field set is small and stable.

**Rejected: drafting the mapping without any per-field confidence signal**, i.e. just
listing detected headers as a comment and leaving 100% of the mapping to the human.
Rejected because the synonym list is cheap to write and testable, and gives real
value on the (likely common) case where a lab's headers closely match another lab's
— see Known Limitation below for where this still falls short.

### Known limitation — synonym coverage

The synonym lists are the load-bearing content here, and this project has exactly
one real lab format to validate against (TestAmerica). Coverage will be thin for labs
not yet seen (Eurofins, Pace, etc.) until their real exports are used to extend the
synonym lists. This is expected and acceptable for a v1 — the tool's value is in
cutting authoring time for *most* fields on *most* labs, not 100% auto-mapping. Do
not treat a fully-CONFIRMED draft as validated; a human must still review before use
(same posture as `draft-parser-profile`'s `_TODO: REVIEW EVERY ANCHOR`).

---

## Confidence model

Two tiers, applied per canonical field during matching:

- **CONFIRMED** — exactly one header in the sample file matches a known synonym for
  this field (case/whitespace-normalized comparison).
- **NEEDS_REVIEW** — either zero headers matched, or more than one header matched
  ambiguously. In both cases the field is left unmapped in the output profile; for
  the ambiguous case, all candidate header names are recorded so a reviewer (CLI: a
  `_TODO` comment listing them; GUI in Slice 2: a dropdown) doesn't have to re-derive
  them by hand.

No finer granularity (no numeric confidence score, no "probably wrong" tier) — this
is deliberately coarse. Fields are either safe to trust or they aren't.

---

## Architecture

```
autogis/
  core/envmon/
    edd_profile_draft.py     ← NEW: draft_edd_profile(), DraftedProfile, DraftedField
                                 pure Python, no arcpy/PySide6 — reused by CLI and
                                 (later) the GUI
    edd_profile.py           ← unchanged; validate_edd_profile() already exists here
  adapters/
    cli.py                   ← add draft-edd-profile, list-lab-profiles,
                                 validate-lab-profile under envmon group
  config/
    lab_profiles/
      testamerica/            ← RESTRUCTURED from testamerica.yaml
        profile.yaml
        sample_fixture.csv    ← NEW: redacted/synthetic sample in TestAmerica's
                                 real export shape
tests/
  envmon/
    test_edd_profile_draft.py  ← NEW: arcpy-free
  test_cli_lab_profiles.py     ← NEW: CLI success/error paths
```

### `edd_profile_draft.py` — public API

```python
@dataclass(frozen=True)
class DraftedField:
    canonical_name: str
    status: Literal["CONFIRMED", "NEEDS_REVIEW"]
    matched_column: Optional[str]        # set iff CONFIRMED
    candidates: list[str]                # >1 iff ambiguous; empty iff zero-match

@dataclass(frozen=True)
class DraftedProfile:
    format: Literal["flat_csv", "two_tab_xlsx"]
    fields: list[DraftedField]
    sample_sheet: Optional[str] = None   # two_tab_xlsx only
    result_sheet: Optional[str] = None   # two_tab_xlsx only

def draft_edd_profile(sample_path: Path) -> DraftedProfile:
    """Inspect a sample EDD file and propose a column mapping.

    Detects flat_csv vs two_tab_xlsx from the file extension and (for xlsx)
    sheet layout. Matches each canonical field's synonym list against the
    file's header row(s); see confidence model above.
    """

def drafted_profile_to_yaml_dict(drafted: DraftedProfile, profile_id: str,
                                  lab_name: str) -> dict:
    """Assemble a LabEDDProfile-shaped dict from a DraftedProfile, ready for
    yaml.dump(). NEEDS_REVIEW fields get an empty mapping plus a `_TODO`
    entry listing the field and its candidates (or "no match found")."""
```

### `two_tab_xlsx` handling (per-sheet attribution)

Unlike `flat_csv` (one header row), `two_tab_xlsx` splits sample metadata and
results across two sheets. `draft_edd_profile()` must:

1. Detect both sheets (using the same default `Samples`/`Results` sheet-name
   convention as `LabEDDProfile.sample_sheet`/`result_sheet`, falling back to
   the first two sheets if those names aren't found — flagged as NEEDS_REVIEW
   at the profile level, not per-field, if the fallback is used).
2. Match each canonical field's synonyms against **each sheet's header row
   independently** — not a merged header set — since a column named
   `Sample_ID` could plausibly appear on both sheets with different meaning,
   and the drafted profile's `columns` mapping doesn't currently distinguish
   which sheet a column comes from (matching `LabEDDProfile.resolve_column`'s
   existing behavior, which looks up by name only after the importer's
   `_read_two_tab_xlsx` has already merged the rows).
3. Record which sheet each matched column was found on internally (for
   correctness of matching, e.g. to avoid matching a `Results`-only field
   against a `Samples`-sheet column that happens to share a name) — this
   detail does not need to appear in the output YAML, since `LabEDDProfile`'s
   own merge-then-lookup model doesn't carry sheet identity either.

---

## CLI commands

All three headless (no arcpy), added under `autogis envmon`.

### `draft-edd-profile`

```
autogis envmon draft-edd-profile SAMPLE_FILE --output PATH \
  [--profile-id ID] [--lab-name NAME]
```

`--profile-id` defaults to `"DRAFT"` (same default as `draft-parser-profile`).
`--lab-name` defaults to the sample file's stem (e.g. `eurofins_export.csv` →
`"eurofins_export"`) — a placeholder good enough to edit later, not worth a
required flag for a one-shot draft command.

Follows `draft-parser-profile`'s actual pattern: writes the YAML, then echoes a
one-line `click.echo` summary (e.g. `"Draft profile written: {out} (N field(s)
need review)"`) — `_render_qa` is not used here, matching `draft-parser-profile`,
which only invokes it conditionally for separate inspection QA records, not for
its own summary line. NEEDS_REVIEW fields appear as `_TODO` entries in the written
YAML, same convention as `propose_parser_profile`.

### `list-lab-profiles`

```
autogis envmon list-lab-profiles [--dir PATH]
```

Scans `lab_profiles/*/profile.yaml` (default) or `--dir`, loads each via
`LabEDDProfile.load()`, prints a table: `lab_name | profile_id | format |
path`. A profile that raises on load is listed with `status=ERROR` and the
exception message rather than crashing the whole listing — one broken
profile shouldn't hide the rest.

### `validate-lab-profile`

```
autogis envmon validate-lab-profile PROFILE_YAML
```

Thin exposure: `LabEDDProfile.load()` then `validate_edd_profile()`, rendered
via the existing `_render_qa(qa, report, fail_on)` helper (positional, no
defaults — pass `None`/`"error"` explicitly) — same pattern as every other
`validate-*` command in `cli.py`.

---

## Directory restructure

- `autogis/config/lab_profiles/testamerica.yaml` →
  `autogis/config/lab_profiles/testamerica/profile.yaml`
- Add `autogis/config/lab_profiles/testamerica/sample_fixture.csv` — a
  redacted/synthetic sample in TestAmerica's real export shape, serving both
  as human-readable documentation of the expected format and as a test
  fixture for `test_edd_profile_draft.py` / `test_cli_lab_profiles.py`.
- **Fallout checked:** widened grep (`lab_profiles`, across `.py`/`.yaml`/`.md`)
  found no executable code or test that hardcodes the flat path. Historical
  docs (`docs/adr/0016-lab-edd-importer-design.md`,
  `docs/superpowers/plans/2026-06-25-lab-edd-importer.md`,
  `docs/superpowers/specs/2026-06-25-lab-edd-importer-design.md`) reference
  the old flat-file convention — these are left as-is; they're durable
  records of the decision at the time, not living documentation.
  `docs/superpowers/specs/2026-06-27-run-env-job-queue-design.md` has one
  non-executable example string using the old path — harmless, not updated.
- `list-lab-profiles` and `validate-lab-profile` are written against the new
  `<lab>/profile.yaml` shape from the start (no dual-path support needed —
  there's only one real profile to migrate).
- **Second consumer to not break:** `batch_workbook_importer.py` also loads
  `LabEDDProfile` via an explicit `profile_path` supplied per manifest row —
  unaffected by this restructure since it never assumes the flat layout, but
  the implementation plan should include it as an explicit regression check.

---

## Testing plan

- **`test_edd_profile_draft.py`**: synonym matching (CONFIRMED case), zero-
  match and ambiguous-match NEEDS_REVIEW cases, format detection (flat_csv vs
  two_tab_xlsx from extension/sheet layout), two-sheet per-sheet matching,
  using small synthetic CSV/XLSX fixtures built inline (not the TestAmerica
  fixture — that one's for round-trip/documentation).
- **`test_cli_lab_profiles.py`**: all 3 commands' success paths, plus error
  paths — malformed/empty sample file for `draft-edd-profile`, a directory
  with one broken profile for `list-lab-profiles`, a profile missing a
  required column mapping for `validate-lab-profile`.
- **Round-trip check**: the migrated `testamerica/profile.yaml` still loads
  via `LabEDDProfile.load()` and passes `validate_edd_profile()` cleanly
  post-restructure (regression test — this profile is real and used by
  existing `import-edd` tests/examples).

---

## Error handling

- `draft_edd_profile()` raises a clear `ValueError` on an unreadable/empty
  sample file (no rows, no header) — the CLI wraps it as a `click.ClickException`
  per the existing convention (compare `import_edd_cmd`'s `--event-date`
  parsing).
- `list-lab-profiles` never raises on an individual bad profile — see above.
- `validate-lab-profile` surfaces `LabEDDProfile.load()` failures (e.g.
  missing YAML keys) as a `click.ClickException`, and QA failures via the
  normal `_render_qa` exit-code convention (`--fail-on`).

---

## Out of scope / future work (Slice 2 and beyond)

- **Slice 2 (separate spec):** GUI "Lab Profile Browser" — lists profiles
  with hover-tooltip mapped-field summaries (e.g. "9/9 fields mapped" or "3
  fields still _TODO: ..."), plus a "Draft New Profile..." dialog that runs
  `draft_edd_profile()` on a background QThread worker (same pattern as the
  executor) and presents an editable mapping table with NEEDS_REVIEW rows
  flagged (color, like the QA-results table), letting the user pick among
  ambiguous candidates or type a column name before saving. Both reuse this
  slice's core function and CLI-equivalent save logic (mirroring the
  `config_builder.py` / `config_builder_dialog.py` pure-logic-module / Qt-dialog
  split, ADR-0065 — note that split is precedent for keeping Qt out of the core
  function, not for proven CLI+GUI sharing, since `config_builder.py` today is
  only consumed by the dialog/app/tests, not any CLI command).
- **AI-assisted drafting** — deferred per §11 gate, not reopened here.
- **Synonym list expansion** — grows organically as real EDD formats from
  new labs are used to draft profiles; no upfront attempt to guess synonyms
  for labs not yet seen.

---

## 2026-07-08 update — superseded by broader scope

This Slice 1 design is being reconsidered in light of a same-day scope expansion:
the user wants a discipline-agnostic, multi-format result-ingestion architecture
(environmental water/soil now, industrial hygiene/air monitoring as future
disciplines; commercial lab EDDs through regulatory/governmental formats like EPA
WQX, EQUIS, state Mining EDD, NYSDEC EDD; CSV/XML/JSON/XLS/XLSX). Real-world format
examples are being catalogued at
`C:\Users\ichbi\OneDrive\Desktop\Analytical Report Format Examples` to ground a new
design pass. This document is kept as a record of the narrower Slice 1 design and
its review; it is NOT yet approved or superseded — that decision is pending the
broader-scope brainstorm. Do not begin implementation from this spec until scope is
reconciled with the new direction.
