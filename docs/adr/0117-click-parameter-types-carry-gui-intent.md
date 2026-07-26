# ADR-0117: Click parameter types carry GUI intent without narrowing CLI input

**Status:** Proposed

**Date:** 2026-07-26

## Context

The standalone GUI derives its forms from the Click command tree
([ADR-0052](0052-gui-introspection-layer.md)), but Click's ordinary `STRING`
type leaves the GUI unable to distinguish a date, a value with useful
suggestions, or a comma-joined closed vocabulary. Those options therefore
rendered as free-text fields even when a native picker was possible.

Hardcoding option vocabularies in `gui/app.py` would duplicate the CLI's source
of truth. Replacing every known vocabulary with `click.Choice` would be worse:
some lists are suggestions, not constraints. For example, matrix codes outside
the built-in figure-spec set are valid, unit aliases exist outside the unit
conversion registry, and run-history filters must still find retired tool
names. Likewise, `click.DateTime` returns a `datetime`, while the existing
command bodies intentionally receive and parse strings.

The compatibility constraint is therefore: improve CLI validation and expose
enough metadata for native GUI controls without rejecting previously valid
input or changing the value type delivered to command bodies.

## Decision

Click remains the single source of truth for parameter semantics and GUI
control selection. `autogis.adapters.param_types` defines three small
`click.ParamType` subclasses:

- `SuggestedChoice` exposes `.choices` but accepts every value.
- `IsoDate` validates an ISO date or timestamp, as declared, and returns the
  original string.
- `CommaList` validates each comma-separated element against a closed
  vocabulary and returns the original string.

All three preserve the exact input string. Command bodies do not change their
input types or parsing rules.

`gui/introspect.py` maps those types to toolkit-free `FormField` metadata:
editable choice, date, and multichoice respectively. It also carries Click
range bounds, repeatability, and `nargs`. `gui/app.py` renders controls only
from that metadata; it does not own parameter vocabularies.

Use strict `click.Choice` only when the command already enforces the same
closed set. Use `IntRange`/`FloatRange` only for evidence-backed bounds. Leave
data-dependent vocabularies as free text until a reusable enumerator exists.

## Consequences

### Positive consequences

- The CLI and GUI cannot silently drift onto different vocabularies.
- Closed-list typos become Click usage errors before a command writes output.
- The GUI can render editable dropdowns, checklists, calendars, bounded spin
  boxes, repeatable rows, and multi-token inputs without per-command mappings.
- Existing command bodies and saved command-line syntax retain their value
  shapes.

### Negative consequences

- The custom types and their pass-through contract become maintained adapter
  API and require focused regression tests.
- A suggested choice is intentionally not validation; callers must not infer
  that `.choices` is exhaustive.
- Data-dependent vocabularies still require typing until a non-blocking,
  reusable enumeration seam is designed.

## Alternatives considered

- **Hardcode vocabularies or widget types in the GUI:** rejected because it
  creates a second source of truth.
- **Use `click.Choice` for every known list:** rejected because it narrows open
  vocabularies and makes historical values unqueryable.
- **Use `click.DateTime`:** rejected because it changes strings into
  `datetime` objects and breaks existing command-body parsing.
- **Add a YAML or dictionary metadata sidecar:** rejected because the relevant
  type and vocabulary already belong on the Click declaration.
- **Change comma lists or repeatable options to a new CLI spelling:** rejected
  because it would break saved recipes and scripts.

## Related decisions

- [ADR-0052: GUI introspection layer](0052-gui-introspection-layer.md)
- [ADR-0056: GUI form-values to Step adapter](0056-gui-form-step-adapter.md)
- [ADR-0057: GUI walking skeleton](0057-gui-walking-skeleton.md)
- [ADR-0060: GUI window polish](0060-gui-window-polish-browse-help.md)
- [GUI parameter-controls design](../superpowers/specs/2026-07-25-gui-parameter-controls-design.md)
- [Issues #350-#357](https://github.com/0bnoxide/AutoGIS/issues/350)
