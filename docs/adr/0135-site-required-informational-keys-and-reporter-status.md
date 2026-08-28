# ADR-0135: Site-config required keys narrowed to consumed keys; Reporter declared future-use

**Status:** Accepted

**Date:** 2026-08-28

## Context

Issue #450 reported two "implemented but not connected" findings from the
2026-08-03 wiring-gap survey:

1. `SITE_REQUIRED` (`core/common/config.py`) listed twelve keys, so
   `SiteConfig.load` hard-failed without them. Nine of them —
   `project_number`, `address`, `city`, `state`, `coordinate_system`,
   `default_gdb`, `default_aprx_template`, `soil_borings_fc`,
   `site_boundary_fc` — had no consumer that needs them *present*. Every site
   config had to supply nine values that nothing reads, and `envmon init-site`
   generates `_TODO` placeholders an operator must fill before the config will
   load at all.
2. `core/common/reporting.py` `Reporter` carried a docstring claiming it is
   "the one channel through which [results] are emitted" while `record_result`
   took a result, returned it, and did nothing else. Its only caller is
   `tests/test_reporting.py`.

The issue asked for a decision, not a bug fix: "either wire the keys, or move
them out of `SITE_REQUIRED` into an optional/informational block", and "either
wire `Reporter` in, or mark it future-use the way `seen.py` does".

The 2026-08-08 autonomous session
(`docs/adr/logs/2026-08-08-agent-decisions.md`) explicitly declined to act on
#450, recording that "deleting shipped config keys or relaxing load validation
is an owner call, not a bug fix. Left open, reported." That judgment stood
until the owner directed this session to pick open issues to fix and to carry
the result to merge. This ADR exists because that direction resolves *who
decides*, not *what was decided* — the latter is recorded here.

Evidence gathered before choosing: every reader of a dropped key in `autogis/`
(including `adapters/toolbox.pyt`) reaches it through `.get()` with a default,
never by attribute. `cli.py:3019` reads
`str(cfg.get("coordinate_system") or "")` and additionally guards against an
unfilled `_TODO` value, then passes `spatial_reference=None`, for which
`fieldmaps_plan` has a designed `unknown_crs` QA warning. The code already
tolerated these keys being absent or unfilled; only the loader did not.

## Decision

1. `SITE_REQUIRED` narrows to the keys the suite actually depends on:
   `site_id`, `site_name`, `monitoring_wells_fc`. The other nine become
   informational — still scaffolded by `init-site`, still readable via
   `__getattr__`/`.get` when present, no longer load-blocking. Their unused
   typed accessors are deleted.
1a. **Loading and validating are decoupled.** `config_validation` gets its own
   `SITE_RECOMMENDED` list carrying those nine keys, and `validate_site`
   reports each absent one as a `SEV_WARNING`/`missing_recommended_key`.
   Narrowing the load gate alone would have silently deleted nine checks from
   `envmon validate-config`, because both had been reading one constant. That
   matters most for `coordinate_system`, which *is* consumed
   (`adapters/cli.py` `build-fieldmaps`): without it the run degrades to
   `spatial_reference=None`, whose only other signal is an `unknown_crs`
   warning raised inside `provision_fieldmaps_layers` — an arcpy-only LOCAL
   path a headless operator never reaches. `validate-config` is the sole
   arcpy-free place that gap is visible, so it keeps reporting.
2. `Reporter` declares its unwired future-use status in its own docstring, the
   way `core/common/seen.py` does, and `record_result` appends to
   `Reporter.results` instead of silently discarding its argument.

`monitoring_wells_fc` stays required because it is genuinely consumed
(`fieldmaps_plan.py`, `toolbox.pyt:959`); this matches the set #450 itself
identified as unconsumed.

## Consequences

### Positive consequences

- A new site config loads with three keys instead of twelve. Onboarding no
  longer requires filling nine `_TODO` placeholders that nothing reads.
- The loader's failure surface now means something: a `ConfigError` from
  `SiteConfig.load` names a key the suite will actually use.
- `Reporter` no longer advertises a guarantee it does not provide. A future
  caller wiring a tool through it gets a recorded result rather than silent
  data loss — the failure mode the docstring previously invited.

### Negative consequences

- The nine keys drop from `SEV_ERROR` to `SEV_WARNING` in
  `envmon validate-config`, so a config missing all of them now exits 0 where
  it previously exited 1. That is the intended meaning of "informational" —
  the config genuinely loads and runs — but a pipeline that gated on
  `validate-config`'s exit code alone will stop catching them. The records are
  still emitted and still visible in the report.
- Two lists now describe one set of keys (`SITE_REQUIRED` in `config.py`,
  `SITE_RECOMMENDED` in `config_validation.py`). They are deliberately
  separate because they answer different questions — *can this load?* versus
  *is this complete?* — but a key added to the site schema has to be placed in
  the right one, and nothing enforces that mechanically.
- `Reporter.results` grows unbounded for as long as a Reporter instance lives.
  Acceptable while the class is unwired and single-run scoped; a caller
  wiring it into long-running work must revisit it.

## Alternatives considered

- **Wire the nine keys into consumers.** Rejected: it would invent consumers
  for values no deliverable needs, which is the opposite of the reported
  defect. `coordinate_system` and `default_gdb` already have the consumers
  they need, via `.get()`.
- **Delete the nine keys from the shipped template.** Rejected: they carry
  real project metadata an operator may want recorded (project number, site
  address), and `default_layout_text` renders some of it onto figures.
  Informational-but-present is the honest state.
- **Leave `SITE_REQUIRED` alone and only fix the docstring.** Rejected: it
  keeps a hard load failure on nine values nothing reads, which is the defect.
- **Narrow `SITE_REQUIRED` and let `validate_site` follow it.** This is what
  the first cut of the change did, and the cold review caught it: it silently
  removed nine operator-facing checks as a side effect of a loader change.
  Rejected — see 1a. Keeping them at `SEV_ERROR` in the validator was also
  rejected: a config that loads and runs should not be reported as failing.
- **Wire `Reporter` into a production tool.** Rejected as out of scope and
  speculative — no tool currently needs a second emit channel; marking it
  future-use is what `seen.py` already established as the honest pattern.
- **Make `record_result` raise.** Rejected: it would break the class's only
  existing caller to protect a caller that does not exist yet.

## Related decisions

- [ADR-0005: Thread-safe QA and reporting substrate](0005-thread-safe-qa-substrate.md)
- [ADR-0009: Config dataclass style](0009-config-dataclass-style.md)
- [ADR-0012: Reserved provenance columns for future use](0012-reserved-provenance-columns.md)
- [Issue #450](https://github.com/0bnoxide/AutoGIS/issues/450)
- [PR #516](https://github.com/0bnoxide/AutoGIS/pull/516)
- Prior deferral: `docs/adr/logs/2026-08-08-agent-decisions.md`
