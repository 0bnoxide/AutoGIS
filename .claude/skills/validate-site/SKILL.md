---
name: validate-site
description: Run the headless AutoGIS validation suite (config + units) for a named site config or a config path. Usage: /validate-site <site-name-or-config-path>
---

# validate-site

Validate a per-site AutoGIS config bundle using the headless (arcpy-free) tools.

## Resolve the target

The argument is either a path to a site-config YAML or a short name.

1. If the argument is a path that exists, use it as `<site_config>`.
2. Otherwise treat it as a name and look under `autogis/config/`:
   - exact: `autogis/config/<arg>.yaml`
   - else glob `autogis/config/*<arg>*.yaml` (case-insensitive) and pick the
     single match; if more than one matches, list them and ask which.

Standard cross-file inputs (pass them when present):
- analyte dictionary: `autogis/config/analyte_dictionary.yaml`
- screening levels: `autogis/config/screening_levels.yaml`

## Run the pipeline

Use the installed console script `autogis` (fall back to
`python -m autogis.adapters.cli` if `autogis` is not on PATH).

1. **Config bundle** — stop and report if this fails:
   ```
   autogis envmon validate-config <site_config> \
     --analytes autogis/config/analyte_dictionary.yaml \
     --screening autogis/config/screening_levels.yaml
   ```
   Add `--profile <p>` / `--figure <f>` if the site has parser profiles or figure
   specs you want cross-checked.

2. **Units** — convertibility of analyte/screening units:
   ```
   autogis envmon validate-units \
     --analytes autogis/config/analyte_dictionary.yaml \
     --screening autogis/config/screening_levels.yaml
   ```

## Report

Summarize per stage: which QA records are CRITICAL/ERROR/WARNING and the final
`Status:` line. If stage 1 fails (exit 1), do not run stage 2 — a broken config
makes the units check meaningless.

> `validate-db` (GDB schema/integrity, Tool 8) is **ArcGIS Pro only** — it needs
> arcpy and is not part of this headless skill. Run it from the `.pyt` toolbox or
> `autogis envmon validate-db <gdb>` inside Pro.
