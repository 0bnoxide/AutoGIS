# Site onboarding bootstrap (`envmon init-site`) — design

**Date:** 2026-07-22
**Phase:** Production roadmap Phase 3 (first slice)
**Status:** Proposed

## Purpose

Give an operator a one-command way to stand up a new site's config skeleton so
they never hand-assemble the directory structure. The command copies versioned
templates into the four config families, substitutes the site identity, surfaces
every `_TODO` anchor the operator must complete, and runs the existing loaders to
prove the generated files are structurally valid.

Roadmap text: *"Add `envmon init-site` to copy versioned templates, create the
site/schedule/parser/figure-spec skeleton, identify unverified anchors and missing
regulatory content, and run existing validators. The first slice is a CLI with
`--dry-run`, not a new wizard framework."*

**"schedule" clarification:** there is no separate schedule schema in the
codebase, and ADR-0087 explicitly *rejected* adding a scheduler under YAGNI. The
"schedule" artifact is the existing **event configuration**
(`config/event_configs/`, whose `event_config.example.yaml` is already a
copy-and-fill template). This slice does not invent a schedule schema.

## Scope (first slice)

Scaffold all four config families:

| Family | Output file | Existing loader (validator) |
|---|---|---|
| site | `sites/<ID>.yaml` | `SiteConfig.load` |
| event ("schedule") | `event_configs/<ID>_event_config.yaml` | `load_event_config` |
| parser profile | `parser_profiles/<ID>_DataTables.yaml` | `ParserProfile.load` |
| figure spec | `figure_specs/<ID>_GW_Analytical.yaml` | `FigureSpec.load` |

### Deliberately out of scope (YAGNI / roadmap governance)

- No wizard framework, interactive prompts, or TUI.
- No new "schedule" schema, workflow language, or scheduler (ADR-0087 rejected).
- No branching logic, no multi-site batch onboarding.
- "Missing regulatory content" detection beyond the `_TODO` anchor scan — the
  templates carry `_TODO` markers where regulatory values (screening-level
  reference, state, coordinate system, plausibility window) belong; deeper
  regulatory-completeness rules are a later slice.

## Command

```
envmon init-site --site-id H281 --site-name "H281 Glasgow" \
    [--dest autogis/config] [--force] [--dry-run]
```

- `--site-id` (required): site identifier, e.g. `H281`. Used in filenames and as
  the `{site_id}` substitution.
- `--site-name` (required): human-readable name, `{site_name}` substitution.
- `--dest` (default = the packaged `autogis/config` dir): config root to write
  under. Lets an operator scaffold into a working copy.
- `--force`: overwrite existing target files. Absent = refuse to clobber.
- `--dry-run`: render + validate + anchor-scan in memory, write nothing, print
  the plan.

Headless (Tool-1 class, openpyxl-free, arcpy-free). Wired into the `envmon`
CLI group like the other headless commands.

## Architecture

One new arcpy-free core module `autogis/core/envmon/init_site.py`, plus CLI
wiring and template files. No new dependencies.

### Data flow

```
init-site --site-id --site-name --dest --force --dry-run
      │
      ▼
plan_site_skeleton(site_id, site_name, dest)         # pure: no I/O
      │   → list[SkeletonFile(target_path, rendered_text, family)]
      ▼
for each SkeletonFile:
    - overwrite guard (skip write if exists and not --force → QA ERROR)
    - dry-run: keep in memory only
    - else: write target_path (mkdir -p parent)
      │
      ▼
validate_skeleton(files)   → per-family loader run → PASS / ConfigError
scan_anchors(files)        → list[(file, line, marker_text)] for every _TODO
      │
      ▼
render report (human) + QA collector; exit code from QA severity
```

### Components

- **Templates** — `autogis/config/_templates/site_skeleton/`: four `*.yaml`
  files derived from the existing loadable example configs (H281 site, H272
  parser, `event_config.example`, CKG figure spec), with site-specific values
  genericized to `{site_id}` / `{site_name}` / `_TODO` placeholders. Every
  loader-required key is present so structural validation passes; every value an
  operator must supply is a `_TODO` marker.
- **Substitution** — two `str.replace` calls for two sentinel tokens
  `__SITE_ID__` and `__SITE_NAME__`. Sentinels (not `{site_id}`) are required
  because figure specs and parser profiles legitimately carry `{site_id}` /
  `{figure_spec_id}` as **runtime** placeholders (def-queries, filename
  patterns) that the figure engine resolves per-invocation and that init-site
  must leave intact. `__SITE_ID__` cannot collide with those. No template
  engine, no regex; test 1 asserts no residual `__SITE_ID__` / `__SITE_NAME__`
  survives rendering.
- **`plan_site_skeleton(site_id, site_name, dest)`** — pure function returning
  the list of `(target_path, rendered_text, family)`; no filesystem side
  effects, so it is trivially testable and drives both real and `--dry-run`
  paths.
- **`scan_anchors(text)`** — `_TODO` line scan (the anchor convention already
  used across every config). Returns `(line_no, snippet)`.
- **`validate_skeleton(files)`** — dispatches each family to its existing loader;
  a `ConfigError` becomes a QA ERROR naming the file. Reuses `QACollector`.

### Error handling / data-loss

- **Overwrite guard is the data-loss boundary** — an existing target file is
  never overwritten unless `--force`; without it the file is left untouched and
  reported as a QA ERROR (`init_site_target_exists`). This is not simplified
  away.
- Missing `--dest` dir components are created (`mkdir -p`). `--dest` itself must
  exist or be creatable.
- Validation failure of a generated file is a QA ERROR (surfaces a broken
  template in tests), not a silent pass.

## Testing (arcpy-free, dev venv)

`tests/envmon/test_init_site.py`:

1. `plan_site_skeleton` produces four files with `__SITE_ID__` / `__SITE_NAME__`
   substituted and no residual sentinel token in any rendered file. (Runtime
   `{site_id}` tokens in the figure/parser skeletons are preserved, not touched.)
2. Every generated file passes its existing loader (`SiteConfig.load`, etc.) —
   this pins the templates as structurally valid.
3. `scan_anchors` finds the known `_TODO` markers in the rendered site config.
4. Overwrite guard: a pre-existing target is not clobbered without `--force` and
   is reported; `--force` overwrites.
5. `--dry-run` writes nothing (assert dest dir unchanged) yet still reports plan,
   anchors, and validation.
6. CLI smoke: `init-site --dry-run` exits 0 and lists the four families.

## Migration / rollback / security

- No schema change to existing configs; purely additive (new command, new
  template dir). Rollback = revert the PR.
- No data-loss path (overwrite guarded). No secrets in templates (placeholders
  only). No network, no arcpy.
- **Path-injection guard:** `site_id` flows into filenames under `--dest`, so it
  is validated at the CLI boundary against `^[A-Za-z0-9_-]+$` (reject via
  `click.BadParameter`) before any path is built — blocks `../` traversal and
  separators. Trust-boundary validation is not simplified away (ponytail
  exemption).

## Decision record

Ships a new headless tool + template set → an ADR is added at merge time
(tool-batch scope per CLAUDE.md), referencing this spec and ADR-0087 (roadmap
ordering).

## Slice 2 — identify missing regulatory content (2026-07-22)

The Phase 3 text also calls for identifying "missing regulatory content."
Screening levels are the site's regulatory content, but they are passed
explicitly to the tools (`--screening-levels PATH`) with no per-site file
convention, so init-site does not (and should not, without a structural
decision) scaffold them. Instead the command now **reports** the gap:
`regulatory_gaps()` (core) returns the un-scaffolded regulatory items and the
CLI prints a "Regulatory content to configure (NOT scaffolded)" section — so an
operator can't unknowingly push a site to production with no exceedance
criteria. Introducing a per-site screening-levels convention is deferred as a
structural decision for the owner.
