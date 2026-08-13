# ADR-XXXX: Open-issue fix batch (2026-08-13) — the answer must not depend on who asks first

**Status:** Proposed

**Date:** 2026-08-13

> **Number assigned at merge.** Filed as an `XXXX-` placeholder per
> `docs/adr/README.md` § File naming, because #492 is exactly what happens when
> a branch guesses. At merge: take the next free number after checking both
> `docs/adr/` and the files of every other open PR, rename the file, fix the
> H1, and replace the `XXXX` row in the index.

## Context

A scheduled housekeeping pass took the open-issue backlog in significance
order. Six of the eight members share one failure class, distinct from the
neighbouring batches:

- **ADR-0124**: doing something *plausible* instead of admitting you cannot
  do the right thing.
- **ADR-0126**: a lookup that structurally *cannot succeed*, answering anyway.
- **ADR-0127**: two copies of one chain that drifted apart.
- **This batch**: **the answer depends on arrival order, or on a predicate
  narrower than the thing it gates.** Nothing is wrong on any single run. Run
  it twice, or hand it an input the predicate never considered, and the
  deliverable changes with no error and no QA record.

Members:

- **#473** `select_prior_water_levels` broke a same-date tie with a strict
  `>`, so the row an `arcpy.da.SearchCursor` happened to yield first won.
  `SearchCursor` guarantees no ordering, so `Dash_GWLevelSummary.PriorGWE_ft`,
  `Delta_ft`, `Trend` and `Dash_WellStatus.GWEDelta_ft` could swing between
  runs over unchanged data — and `Trend` could flip across
  `_RISING_THRESHOLD`. Reachable since #457/ADR-0126 gave Survey123 water
  levels a real `EventDate`: a field submission and a workbook import for the
  same well and day now collide where the Survey123 row previously carried a
  NULL date and could not.
- **#470** `gen-map-series` indexed a folder of figure specs by
  `figure_spec_id`, so two files declaring one id collapsed to whichever
  sorted last. The dropped spec never became a job, so the printed job count
  was *reduced to match* — a truthful-looking plan for a packet missing a
  figure. Same class as #459/#466: a lookup that cannot represent its input,
  answering confidently anyway.
- **#471** The cross-APRX combined appendix wrote a fixed
  `Appendix_Combined.pdf`, bypassing the module's own no-silent-overwrite
  policy that versioned every *individual* figure. A second run preserved the
  intermediates as `_v2`/`_v3` and destroyed the one file the client receives
  — and a partial second run replaced it with a shorter appendix under the
  same name. Worse than an ordinary overwrite: the `_v2` suffixes around it
  make the directory look like nothing was lost.
- **#493 (residual)** `list_connection_profiles` required `url` **and**
  `username`. ArcGIS API for Python persists "any combination of" `url`,
  `username`, `key_file`, `cert_file`, `client_id`, so a PKI or OAuth profile
  — which `GIS(profile=...)` accepts and which carries no username — was
  absent from the dropdown entirely. (The non-UTF-8 and percent-encoded-URL
  halves of #493 shipped in 6bc7a82/1d3b9bc.)
- **#474** `layer_definition_queries` keys come straight from YAML, so an
  unquoted `2026:` or `no:` arrives as an int/bool. Such a key can never equal
  `lyr.name`, so the query was silently never applied — *and then*
  `sorted(missing)`, the reporting that exists to catch exactly that, raised
  `TypeError` out of the CLI with no QA record. Second half: a malformed
  values YAML escaped `load_layout_text_yaml` as a raw `yaml.ParserError`
  while a wrong *shape* got a message naming the file.
- **#477** Thirteen tools carried a `Roadmap #` in the README and
  `roadmap_id=""` in `TOOL_REGISTRY`, so `envmon list-tools --verbose` —
  the in-product answer to "which spec section describes this tool" —
  under-reported while a second hand-maintained surface had the answer. The
  inverse of #458 and the last unpinned direction of the same drift.

Two members are CI/config rather than code:

- **#491** `sonar.sources=autogis` holds `autogis/adapters/gui/**` to a
  new-code coverage gate CI is structurally unable to satisfy: CI installs
  `.[dev]`, PySide6 lives in the `gui` extra, so every GUI test self-skips via
  `pytest.importorskip` and the GUI modules report 0%. Every GUI-only PR
  failed the SonarCloud check by construction (live on #490) with a green
  suite and an independent APPROVE.

## Decisions

1. **A tie gets a total order, and the tie itself gets disclosed.**
   `_prior_pick_key` orders candidates by `(EventDate, ImportBatchID,
   SourceRow, elevation)`. `EventDate` first, so the latest measurement still
   wins exactly as before and the tiebreak only ever decides a tie;
   `ImportBatchID` sorts lexically by timestamp in this schema, making "last
   import wins" the rule — defensible and explainable to an operator. Every
   component is coerced to a sortable type because all four columns are
   nullable and a `None` beside a `str` aborts the whole mart build. A tie
   also emits a `LOG.warning` naming the well, the date and both elevations:
   a duplicated measurement date is itself something a reviewer should see,
   so resolving it silently would leave half the defect in place.

2. **Refuse a duplicate `figure_spec_id` rather than pick one.** The two
   files are typically *different* figures whose id survived a copy-paste, and
   `figure_spec_id` also flows into `register_exports` and the
   `Env_CalloutBoxes` definition query — so there is no reading under which a
   duplicate is fine. The `UsageError` names both file paths.

3. **One overwrite policy, one implementation.** `_versioned` becomes public
   `versioned_path`, and `gen-map-series` routes its combined appendix through
   it. A `--overwrite` flag is threaded to both the per-figure exports and the
   appendix, matching how `ExportFigures` exposes it. Per ADR-0077 the arcpy
   call site was doc-verified: `PDFDocumentCreate(pdf_path)` is unchanged and
   not deprecated at the Pro 3.5 compliance floor or at latest, and Esri's own
   example `os.remove()`s an existing file before creating — confirming the
   path must be free, which is what `versioned_path` guarantees.

4. **Completeness is per authentication mode, not username-only.** A profile
   counts when it has `url` plus one of: `username`, `key_file` + `cert_file`,
   or `client_id`. `url` alone still fails — that is the half-written section
   a failed `store_credential` leaves behind, with nothing to log in with.

5. **Coerce YAML mapping keys at the boundary.** `str(k)` on
   `layer_definition_queries` fixes both halves of #474.1 at once — the query
   now lands *and* a genuinely-absent layer is still reported — and it is the
   rule `_name_list` already applies to the sibling spec fields. A parse error
   is wrapped in `ValueError` naming the file, so one file and one class of
   mistake get one kind of answer (the `_load_json_option` trust-boundary
   convention).

6. **Populate only ids the catalog can answer, and pin the direction.**
   Eleven `roadmap_id`s were verified one at a time against
   `docs/envmon-feature-roadmap.md` — each section's `**Tool name:**` line
   confirmed to name *this* tool — then populated. `import-rtk-survey` (8.3)
   and `validate-rtk-survey` (8.4) stay empty: the catalog carries two
   headings for each number (#476), and while the tool *name* disambiguates,
   the number a reader resolves from `list-tools --verbose` would still mean
   two things. Three further rows are exempted because the README cites a
   catalog section while the seed carries the original ten-tool number
   (`validate-db` 3.1/8, `gw-contours` 4.2/5) or because the README's number
   heads no catalog section at all (`build-event` 4 — `BuildCurrentEvent` has
   no catalog entry). Which vocabulary the README column should speak is an
   owner call about the README, not a registry fix. Every exemption carries
   its reason inline and is itself asserted still-live.

7. **Exempt from the coverage gate exactly what CI cannot measure — and pin
   the list to its reason.** `sonar.coverage.exclusions` names the four
   modules that import PySide6 at module load, deliberately *not*
   `autogis/adapters/gui/**`: the rest of the GUI adapter is PySide6-free by
   design (`config_builder.py`, `executor.py`, `runner.py`, …), runs in CI,
   and stays under the gate. `tests/test_sonar_coverage_exclusions.py` derives
   the list from the source via `ast` and asserts both directions, so a new
   widgets module cannot silently reintroduce the false red and a module that
   stops importing PySide6 loses its exemption. Option 2 from #491 (install
   the `gui` extra in CI) was not taken: it reverses the documented
   "GUI self-skips in CI" decision at `ci.yml:19-20` and adds Qt to a Windows
   runner whose minutes bill at 2x — an owner call, not a housekeeping one.

## Consequences

- **Behavior breaks (intended):** `gen-map-series` now *refuses* a spec folder
  with a duplicate `figure_spec_id` instead of silently exporting a short
  packet; a re-run into a populated `--out-dir` now writes
  `Appendix_Combined_v2.pdf` instead of destroying the first appendix (pass
  `--overwrite` for the old behavior); `select_prior_water_levels` may now
  return a *different* row than a given past run did for a well with a
  duplicated date — that run's answer was arbitrary.
- The connection-profile dropdown grows PKI/OAuth profiles that were
  previously hidden. No profile that appeared before disappears.
- `list-tools --verbose` prints a catalog section for eleven more tools.
- No arcpy call signature changed; the only arcpy-adjacent edit is the path
  argument computed for `PDFDocumentCreate`.
- Closed as already-fixed rather than re-fixed: **#469** (job and step
  `timeout-minutes` landed in 5d12dd9) and **#492** (ADR renumbered to 0130 in
  a70092d).
- Deliberately *not* addressed, and surfaced to the owner instead: **#476**
  (renumbering a spec catalog section is a decision about the spec's
  authority), and the README `Roadmap #` column mixing two numbering
  vocabularies.
