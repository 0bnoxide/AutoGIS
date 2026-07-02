# New envmon tool checklist

One page. Before writing a new `core/envmon` module + CLI command, check
whether one of these blessed helpers already solves a piece of it. Each batch
that skips this list re-solves a solved problem slightly differently (finding
M3, `docs/reviews/fable-architecture-review.md`, tracked as issue #109) —
`envmon-spec-checker` now checks new/modified code against this list, so
treat it as a gate, not a suggestion.

| Need | Use | Not |
|---|---|---|
| Collect QA findings during a tool run | `QACollector` + `_render_qa(qa, report, fail_on)` (`autogis/core/common/qa.py`, `autogis/adapters/cli.py:_render_qa`) | An ad-hoc print loop + bare `SystemExit(1)` |
| `--report`/`--fail-on` CLI options on a headless QA-producing command | `@qa_report_options` decorator (`cli.py:12`) | Hand-declaring the same two `click.option`s |
| Read/write a list of dataclass instances as CSV | `read_records_csv` / `write_records_csv` (`autogis/core/common/records_csv.py`) | Hand-rolling `csv.DictWriter`/`DictReader` + `dataclasses.fields`/`asdict` |
| Load a YAML config file defensively (bad file -> QA error, not a crash) | `validate_config.safe_load(qa, label, fn)` (wraps a loader call) | A bare `try/except` around `yaml.safe_load` with ad-hoc error handling |
| Load canonical config objects | `autogis.core.common.config` (`HarvestConfig`, `ParserProfile`, `FigureSpec`, `load_analyte_dictionary`, `load_screening_levels`, ...) | Re-parsing YAML into a new ad-hoc config dataclass |
| Reach arcpy from a `core/envmon` function | Function-scope `from ...runtime.sessions import arcpy_env as _arcpy` (ADR-0040, style B) | A raw `import arcpy` in the function body (style C), or a module-scope import (style A) |
| New dataclass field-naming choice | PascalCase iff it mirrors a GDB table / deliverable CSV schema; snake_case otherwise (ADR-0038) | Guessing from whichever example is nearest |
| Register a new CLI command | `capabilities.TOOLS` (guard registry, required only if the command calls `_guard(...)`) **and** `capabilities._REGISTRY_SEED` (discovery registry, required for every `envmon` command so `list-tools` sees it) | Registering in only one of the two -- `tests/test_capabilities.py` now catches this, but check both up front |

If a new pattern doesn't fit any of these, that's fine -- not every tool needs
every helper. This list exists so the choice is deliberate, not accidental
duplication.

See also: `docs/adr/0038-record-dataclass-naming-convention.md`,
`docs/adr/0040-canonical-arcpy-access-style.md`, `.claude/agents/
envmon-spec-checker.md`.
