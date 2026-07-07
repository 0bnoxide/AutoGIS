# ADR-0064: AGOL publish-layer hardening (traceback, name pre-check, source typing)

**Status:** Accepted

**Date:** 2026-07-06

## Context

A real debugging session (2026-07-06, issue #180) hit an opaque GUI HALT from
`agol publish-layer`:

    [ERROR] publish failed for 'Test Upload': can only concatenate str (not "NoneType") to str

The root causes were all external (lapsed AGOL subscription 403, an empty test
GDB, a hosted-service name collision), but diagnosis took hours because
`publish_or_overwrite_layer` in `autogis/core/agol/publish.py`:

1. discarded the traceback in both `except` handlers — a bare `TypeError`
   message carries no file/line;
2. called `item.publish()` with no `publish_parameters`, letting arcgis derive
   the service name from the title and crash inside
   `Item._check_publish_status` (arcgis 2.4.3, `arcgis/gis/__init__.py:19011`
   concatenates a null `serviceItemId`) when AGOL synchronously rejects the
   publish — commonly because the derived name is already taken, including by
   a soft-deleted "ghost" service still reserving the name in the Recycle Bin;
3. hardcoded `"type": "File Geodatabase"` in `item_props` with no source
   validation, silently mislabeling shapefile zips (and anything else) even
   though the CLI `--source` help advertised more than FGDB zips.

## Decision

Three boundary-level hardening changes in `publish_or_overwrite_layer`, all
stdlib (`traceback`, `re`, `zipfile`), no new dependencies:

1. **Keep the frames.** Both `except` handlers now log
   `{exc!r}\n{traceback.format_exc()}` into the QA record instead of `{exc}`.
2. **Pre-check the service name and pass it explicitly.** The create path
   derives `service_name = re.sub(r"[\W_]+", "_", config.title)`, calls
   `gis.content.is_service_name_available(service_name, "featureService")`,
   and fails fast with a clear `publish_name_taken` QA error (mentioning the
   Recycle-Bin ghost case) instead of letting arcgis crash. The publish call
   passes `publish_parameters={"name": service_name}` so the checked name is
   the used name. We hard-error rather than auto-suffix a unique token —
   silently renaming a hosted service is worse than telling the user.
3. **Detect and validate the source type.** `_source_item_type()` maps the
   source to its AGOL item type: a zip containing `*.gdb/` members is
   `File Geodatabase`, a zip containing `.shp` members is `Shapefile`,
   `.json`/`.geojson` is `GeoJson`; anything else (including an invalid zip)
   fails fast with a `publish_source_unsupported` QA error before any upload.

## Consequences

### Positive consequences

- The `str + None` failure class becomes a ~30-second diagnosis (traceback in
  the QA record) and its most common trigger (name collision) is caught
  before arcgis is even called, with an actionable message.
- Shapefile zips now publish with the correct item type; unrecognized sources
  are rejected at our boundary instead of failing confusingly downstream.
- Name pre-check happens before `content.add`, so a name collision no longer
  leaves an orphaned File-Geodatabase item on AGOL.

### Negative consequences

- QA error messages are longer (full traceback text) — acceptable for a
  diagnostic surface.
- One extra AGOL round-trip (`is_service_name_available`) per create-path
  publish.
- `.json` and `.geojson` are both uploaded as `GeoJson`; an Esri-JSON
  FeatureSet would need content sniffing — deferred until someone actually
  publishes one (noted with a `ponytail:` comment).

## Alternatives considered

- **Auto-suffix a unique token on name collision** — rejected: silently
  publishing under a different service name than the title implies is a
  surprise; a clear error is the minimum bar and the lazier correct behavior.
- **`logging.exception` instead of embedding the traceback in the QA record**
  — the QA record is what the GUI/CLI surfaces to the user; a log line the GUI
  never shows would not have shortened the original debugging session.
- **Cleanup-on-failure of the orphaned FGDB item** — deferred (issue #180
  marks it optional); the name pre-check already removes the most common
  orphan trigger, and deleting user content on an exception path is riskier
  than leaving it.

## Related decisions

- Issue #180 (origin of all three findings)
- [AGOL publish str+None diagnosis memory entry] — the debugging session that
  motivated this ADR
