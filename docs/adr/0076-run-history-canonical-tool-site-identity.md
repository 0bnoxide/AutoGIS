# ADR-0076: Canonical tool and site identity in CLI run history

**Status:** Accepted

**Date:** 2026-07-09

## Context

ADR-0054 records every CLI leaf through `RecordingCommand`, but the record used
the leaf context's `info_name` and only looked for a `site_id` parameter. That
made nested `manage-callout-overrides` runs appear as `list`, `clear`, `lock`,
or `unlock`, while commands using `--site` or a `site_config` path recorded an
empty site. `evaluate_readiness` matches exact tool and site values, so those
records could not satisfy readiness.

The same audit found the GUI's hand-maintained `UNREACHABLE` policy still
classified the four override commands as dead ends after ADR-0070 made them
executable.

## Decision

1. Record the command immediately below the CLI surface group (`envmon` or
   `agol`) as `tool_name`. Ordinary leaves keep their name; nested override
   leaves record `manage-callout-overrides`, matching the capability registry
   and readiness vocabulary.
2. Resolve `site_id` from the common parameter shapes in order: `site_id`,
   `site`, then the `site_id` value inside a site-config path — either the
   `site_config` dest or the `site_path` dest that the `--site <path>` /
   `--site-config` commands (`build-survey-form`, `create-sampling-event`,
   `build-fieldmaps`) bind to. Config extraction is best-effort; a missing or
   invalid config still produces a record with a blank site rather than
   breaking observability.
3. Remove the four override leaves from GUI `UNREACHABLE`. Keep the
   `optimize-callouts` compatibility alias unreachable because it still
   redirects to the `BuildCallouts` toolbox parameter.

## Consequences

- Nested override and site-config CLI runs now use identities that readiness
  can query.
- GUI users can run the override CRUD commands with a configured Pro Python.
- Multi-site manifest batches still have no single scalar site identity; this
  ADR does not invent one for the current `RunRecord` schema.

## Related decisions

- [ADR-0054](0054-cli-seam-run-recording-recording-command.md)
- [ADR-0062](0062-gui-local-tool-support.md)
- [ADR-0070](0070-callout-placement-cli-wiring.md)
- [2026-07-09 agent decisions](logs/2026-07-09-agent-decisions.md)
