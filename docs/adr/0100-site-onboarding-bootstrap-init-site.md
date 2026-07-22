# ADR-0100: Site onboarding bootstrap — `envmon init-site` (Phase 3, first slice)

**Status:** Accepted

**Date:** 2026-07-22

## Context

Production roadmap Phase 3 (Site onboarding bootstrap; ADR-0087) calls for
`envmon init-site` to "copy versioned templates, create the site/schedule/
parser/figure-spec skeleton, identify unverified anchors and missing regulatory
content, and run existing validators. The first slice is a CLI with `--dry-run`,
not a new wizard framework." Phases 1–2 (qualification runner, event-status)
have shipped, so Phase 3 is the next sanctioned item.

Standing up a new site today means hand-assembling four config files across four
directories (`config/sites`, `config/event_configs`, `config/parser_profiles`,
`config/figure_specs`), each with many `_TODO` value anchors the operator must
fill. There is no versioned starting point.

Design spec: `docs/superpowers/specs/2026-07-22-site-onboarding-bootstrap-design.md`.

## Decision

Add a headless (arcpy-free) `envmon init-site` command and one core module
`autogis/core/envmon/init_site.py`, plus four versioned template files under
`autogis/config/_templates/site_skeleton/`.

Key decisions:

1. **"schedule" == the existing event config.** There is no separate schedule
   schema, and ADR-0087 explicitly rejected adding a scheduler under YAGNI. The
   "schedule" artifact is `config/event_configs/` (whose `event_config.example.yaml`
   was already a copy-and-fill template). This slice invents no schedule schema.

2. **Scaffold all four families in slice 1** so the directory structure is fully
   assembled (the Phase 3 gate: "handed to an operator without manually assembling
   its structure"). The parser/figure files are DRAFT/`_TODO` skeletons.

3. **Reuse existing loaders as validators.** `SiteConfig.load`, `load_event_config`,
   `ParserProfile.load`, `FigureSpec.load` already validate structure (required
   keys present). Templates carry every required key with `_TODO` *values*, so
   they pass structural validation while the `_TODO` scan surfaces the human work.
   No new validation logic.

4. **Sentinel substitution tokens `__SITE_ID__` / `__SITE_NAME__`, replaced with
   `str.replace`** — not `{site_id}` and not the shared `harvest/templates.render()`.
   Figure specs and parser profiles legitimately carry `{site_id}` / `{figure_spec_id}`
   as *runtime* placeholders (def-queries, filename patterns) resolved by the figure
   engine per invocation; init-site must leave those intact, and `render()`'s regex
   would both misfire (`_unknown`) on them and could corrupt `{{...}}`. Two
   `str.replace` calls are simpler and correct on edge cases.

5. **Overwrite guard is the data-loss boundary.** An existing target file is never
   overwritten without `--force`; blocked files are reported and the command exits
   non-zero. `site_id` is validated at the CLI boundary (letters/digits/`-`/`_`
   only) to block `../` path traversal into `--dest`.

## Consequences

- New headless tool visible via `envmon list-tools` (registered in
  `capabilities._REGISTRY_SEED`, domain `admin`, CLOUD).
- Focused arcpy-free tests in `tests/envmon/test_init_site.py` (7) pin template
  validity, substitution, anchor scan, overwrite guard, dry-run, path-traversal
  rejection, and exit codes. Full headless suite green (2343 passed).
- Templates are DRAFT/`_TODO` skeletons — the DRAFT banner and `_TODO` markers
  stay per the pre-production-stub invariant until an operator verifies a real
  site.
- Deferred (YAGNI / roadmap governance): wizard/TUI, interactive prompts,
  branching, batch multi-site onboarding, and regulatory-completeness rules
  beyond the `_TODO` anchor scan.

## Notes

Numbered ADR-0100 against `origin/main` (max 0098) and open PRs (PR #277 uses
0099). Authored autonomously overnight on 2026-07-22 with the owner unavailable
and explicit permission to write YAMLs and exercise judgement; judgement calls
logged in `docs/adr/logs/2026-07-22-agent-decisions.md`.
