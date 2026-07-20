import dataclasses
import json
import os
import uuid
from datetime import datetime as _dt
from pathlib import Path

import click
import yaml

from autogis.adapters.guard import require_runtime, RuntimeUnavailable
from autogis.core.common.config import HarvestConfig, load_config
from autogis.runtime.sessions import agol_from_profile


def qa_report_options(func):
    """Attach the shared ``--report`` / ``--fail-on`` options to a headless
    QA-producing command.

    This is the one home for the headless reporting contract: a command that
    collects a ``QACollector`` and ends with ``_render_qa(qa, report, fail_on)``
    declares the two options once via this decorator instead of repeating them.
    Option order (``--report`` then ``--fail-on``) matches the historical
    hand-written declarations.
    """
    func = click.option(
        "--fail-on", type=click.Choice(["error", "warning"]), default="error",
    )(func)
    func = click.option(
        "--report", default=None, type=click.Path(),
        help="Write QA report to PATH (.md/.json/.csv by extension).",
    )(func)
    return func


def run(config_path, where, out, incremental, *, harvest_fn=None):
    if harvest_fn is None:
        from autogis.core.harvest.harvester import harvest as harvest_fn

    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    profile = (raw.get("connection") or {}).get("profile")

    config = HarvestConfig.load(Path(config_path))

    overrides = {k: v for k, v in
                 {"where": where, "directory": out, "incremental": incremental}.items()
                 if v is not None}
    if overrides:
        config = dataclasses.replace(config, **overrides)

    gis = agol_from_profile(profile)
    summary = harvest_fn(gis, config)
    click.echo(
        f"Downloaded: {summary.downloaded}  "
        f"Skipped: {summary.skipped}  Failed: {summary.failed}")
    return summary


# --------------------------------------------------------------------------
# Run-history recording at the CLI adapter seam (ADR-0054; corrects the
# "result callback" wording in ADR-0050 item 6 -- a result_callback fires
# only on clean returns and would miss every exception exit).
# Command.invoke runs *after* argument parsing (so --help and bad-argument
# UsageErrors never produce records) but wraps execution, catching every
# exit path: guard ClickExceptions, _render_qa's SystemExit(1), Abort,
# KeyboardInterrupt, and unhandled crashes. It covers every caller --
# console script, CliRunner tests, GUI subprocess launches.
# --------------------------------------------------------------------------
_QA_COUNTS_META_KEY = "autogis.qa_counts"
# ponytail: one-entry skip-list -- `agol promote` self-logs a richer record
# (rows_copied etc.) via promote.py's _log_promotion; generalize only when a
# second self-logging command exists.
_SELF_LOGGING_COMMANDS = {"promote"}


def _record_tool_name(ctx) -> str:
    """Return the registry-level command name for a Click leaf context."""
    names = []
    current = ctx
    while current.parent is not None:
        if current.info_name:
            names.append(current.info_name)
        current = current.parent
    names.reverse()
    return names[1] if len(names) > 1 else (names[0] if names else "")


def _record_site_id(params: dict) -> str:
    """Resolve the site's audit identity from common CLI parameter shapes."""
    site_id = params.get("site_id") or params.get("site")
    if site_id:
        return str(site_id)
    # Path-shaped site configs: `site_config` (build-fieldmaps uses the dest
    # `site_path`) and the `--site <path>` commands (build-survey-form,
    # create-sampling-event) that also land on `site_path`. Extract site_id
    # so readiness can match these runs too (ADR-0076).
    site_config = params.get("site_config") or params.get("site_path")
    if site_config:
        try:
            return str(load_config(Path(site_config)).get("site_id") or "")
        except Exception:
            pass
    return ""


def _classify_exit(exc):
    """Map an exit path to a RunRecord status; None means write no record."""
    if exc is None:
        return "success"
    if isinstance(exc, click.exceptions.Exit):
        return "success" if not exc.exit_code else "error"
    if isinstance(exc, click.UsageError):
        return None  # parse-time failure, not a run
    if isinstance(exc, (KeyboardInterrupt, click.Abort)):
        return "cancelled"
    if isinstance(exc, SystemExit):
        return "success" if not exc.code else "error"
    return "error"


class RecordingCommand(click.Command):
    """Leaf command that best-effort writes a RunRecord for every run."""

    def parse_args(self, ctx, args):
        # Windows "Copy as path" pastes '"C:\...\x.gdb"', and a trailing
        # backslash escapes the closing quote in PowerShell ('C:\x\' -> 'C:\x"').
        # Strip such quotes before click validates paths (2026-07-10 QA
        # session: CreateFileGDB crashed on a quote-prefixed folder) -- but
        # ONLY when the value has no interior quote, so SQL --where clauses
        # ('"EditDate" > ...') pass through untouched. ponytail: a --where
        # that is nothing but one quoted field name would still be stripped;
        # that's not a meaningful clause, ceiling accepted.
        args = [inner if (inner := a.strip('"')) != a and inner
                and '"' not in inner else a
                for a in args]
        return super().parse_args(ctx, args)

    def invoke(self, ctx):
        # ponytail: `_dt` alias, not `datetime` -- when this module runs as
        # `__main__` (arcgispro-py3 `python -m autogis.adapters.cli`, the
        # GUI's own invocation), importing arcpy transitively (via
        # HarvestConfig -> arcgis -> arcpy -> arcgisscripting) overwrites any
        # `__main__` global literally named `datetime` (or `math`/`numpy`/
        # `time`) with the stdlib module -- ESRI's C extension pre-seeds
        # `__main__` the way the ArcGIS Pro Python window does. A module-
        # level name matching one of those gets silently stomped.
        started = _dt.now()
        try:
            rv = super().invoke(ctx)
        except BaseException as exc:
            self._record(ctx, started, exc)
            raise
        self._record(ctx, started, None)
        return rv

    def _record(self, ctx, started, exc):
        try:
            dest = os.environ.get("AUTOGIS_RUN_HISTORY", "")
            if dest.lower() == "off":
                return
            tool_name = _record_tool_name(ctx) or ctx.info_name or self.name or ""
            if tool_name in _SELF_LOGGING_COMMANDS:
                return
            status = _classify_exit(exc)
            if status is None:
                return
            from autogis.core.common.run_history import RunHistory, RunRecord

            counts = ctx.meta.get(_QA_COUNTS_META_KEY, {})
            RunHistory(Path(dest) if dest else Path.cwd() / "run_history.csv").write(
                RunRecord(
                    run_id=str(uuid.uuid4()),
                    tool_name=tool_name,
                    site_id=_record_site_id(ctx.params),
                    event_id=(str(ctx.params["event_id"])
                              if ctx.params.get("event_id") else None),
                    started_at=started,
                    finished_at=_dt.now(),
                    status=status,
                    # run_history._encode json.dumps()es inputs with no
                    # default=; one unserializable param (Path, date) would
                    # silently drop the whole record, so sanitize first.
                    inputs=json.loads(json.dumps(ctx.params, default=str)),
                    outputs={},
                    qa_count_error=counts.get("ERROR", 0),
                    qa_count_warning=counts.get("WARNING", 0),
                    qa_count_info=counts.get("INFO", 0),
                    message="" if exc is None else f"{type(exc).__name__}: {exc}",
                ))
        except Exception:
            # Observability must never break or alter the CLI itself.
            pass


class RecordingGroup(click.Group):
    command_class = RecordingCommand
    group_class = type  # self-propagating: @group.group() subgroups record too


@click.group(cls=RecordingGroup)
def autogis():
    """AutoGIS suite — harvest + envmon tools."""


@autogis.command("harvest")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("--where", default=None)
@click.option("--out", default=None)
@click.option(
    "--incremental/--no-incremental",
    default=None,
    help=(
        "Override the config's incremental setting: only fetch attachments for "
        "features edited since the last successful run (requires editor tracking "
        "on the layer)."
    ),
)
def harvest_cmd(config_path, where, out, incremental):
    run(config_path, where, out, incremental)


@autogis.group("envmon")
def envmon():
    """Environmental Monitoring tools (1, 9, 10 headless; 2-8 need ArcGIS Pro).

    Tools 2-8 are LOCAL (arcpy): they are registered here but error cleanly
    when arcpy is absent. The ``.pyt`` toolbox inside ArcGIS Pro is their
    primary UI. Tools 1/9/10 run headless (openpyxl only).
    """


def _guard(name: str) -> None:
    """Surface a missing-runtime as a clean click error, not a traceback."""
    try:
        require_runtime(name)
    except RuntimeUnavailable as exc:
        raise click.ClickException(str(exc))
    except KeyError as exc:
        raise click.ClickException(
            f"Internal error: tool {exc.args[0]!r} is not registered in the "
            f"capability registry. Report this as a bug.")


# --------------------------------------------------------------------------
# Headless tools (1/9/10) — pure core, openpyxl only, no arcpy.
# --------------------------------------------------------------------------
@envmon.command("inspect")
@click.argument("workbook", type=click.Path(exists=True))
@click.option("--scan-rows", type=int, default=40)
def inspect_cmd(workbook, scan_rows):
    """Tool 1: inspect an Excel workbook's structure (headless)."""
    from autogis.core.envmon.excel_workbook_inspector import (
        inspect_workbook_structure,
    )

    report = inspect_workbook_structure(Path(workbook), scan_rows=scan_rows)
    click.echo(f"Inspected {report.workbook}: "
               f"{len(report.sheets)} sheet(s).")


@envmon.command("parser-profile")
@click.argument("profile", type=click.Path(exists=True))
@click.argument("workbook", type=click.Path(exists=True))
def parser_profile_cmd(profile, workbook):
    """Tool 9: load a parser profile and open it against a workbook (headless)."""
    from autogis.core.common.config import ParserProfile
    from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader

    parser = ParserProfile.load(Path(profile))
    reader = ProfileWorkbookReader(Path(workbook), parser)
    click.echo(f"Profile '{parser.profile_id}' opened against "
               f"{len(reader.sheet_names())} sheet(s).")


@envmon.command("figure-spec")
@click.argument("spec", type=click.Path(exists=True))
def figure_spec_cmd(spec):
    """Tool 10: load and validate a figure spec (headless)."""
    from autogis.core.common.config import FigureSpec

    fs = FigureSpec.load(Path(spec))
    click.echo(f"Figure spec '{fs.figure_spec_id}' loaded.")


@envmon.command("validate-config")
@click.argument("site_config", type=click.Path(exists=True))
@click.option("--profile", "profiles", multiple=True, type=click.Path(exists=True),
              help="Parser profile(s) to validate (repeatable).")
@click.option("--figure", "figures", multiple=True, type=click.Path(exists=True),
              help="Figure spec(s) to validate (repeatable).")
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary (default: none; cross-file checks skipped).")
@click.option("--screening", default=None, type=click.Path(exists=True),
              help="Screening levels file.")
@click.option("--report", default=None, type=click.Path(),
              help="Write report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def validate_config_cmd(site_config, profiles, figures, analytes, screening,
                        report, fail_on):
    """Tool: validate a per-site config bundle (headless)."""
    from autogis.core.envmon.validate_config import validate_env_config

    qa = validate_env_config(
        Path(site_config), [Path(p) for p in profiles],
        [Path(f) for f in figures],
        Path(analytes) if analytes else None,
        Path(screening) if screening else None)
    _render_qa(qa, report, fail_on)


@envmon.command("manage-analyte-dict")
@click.argument("analytes", type=click.Path(exists=True))
@click.option("--list", "do_list", is_flag=True, default=False,
              help="Print the resolved analyte table sorted by display_order.")
@click.option("--check", "do_check", is_flag=True, default=False,
              help="Run validation checks (default when --list is absent).")
@qa_report_options
def manage_analyte_dict_cmd(analytes, do_list, do_check, report, fail_on):
    """Tool: validate / inspect the analyte dictionary (read-only, headless)."""
    from autogis.core.envmon.manage_analyte_dict import (
        check_analyte_dictionary, list_analytes)

    if do_list:
        rows = list_analytes(Path(analytes))
        header = f"{'display':>7}  {'canonical':<24} {'abbr':<8} {'group':<14} aliases"
        click.echo(header)
        for row in rows:
            click.echo(f"{row['display_order']:>7}  {row['canonical']:<24} "
                       f"{row['abbreviation']:<8} {row['analytical_group']:<14} "
                       f"{row['alias_count']}")
        if not do_check:
            return
    # Default to check when --list was not requested, or when both given.
    qa = check_analyte_dictionary(Path(analytes))
    _render_qa(qa, report, fail_on)


@envmon.command("manage-screening-levels")
@click.argument("screening", type=click.Path(exists=True))
@click.option("--analytes", default=None, type=click.Path(exists=True))
@click.option("--list", "do_list", is_flag=True, default=False,
              help="Print analyte/matrix/value table.")
@qa_report_options
def manage_screening_levels_cmd(screening, analytes, do_list, report, fail_on):
    """Validate and inspect the screening levels YAML (headless)."""
    from autogis.core.envmon.manage_screening_levels import (
        check_screening_levels, load_screening_entries)
    if do_list:
        entries = load_screening_entries(Path(screening))
        click.echo(f"{'analyte':<28} {'matrix':<6} {'value':>10}  units")
        for e in sorted(entries, key=lambda x: (x.matrix, x.analyte)):
            v = str(e.value) if e.value is not None else "null"
            click.echo(f"{e.analyte:<28} {e.matrix:<6} {v:>10}  {e.units}")
        if not analytes:
            return
    qa = check_screening_levels(Path(screening), Path(analytes) if analytes else None)
    _render_qa(qa, report, fail_on)


@envmon.command("validate-units")
@click.option("--analytes", required=True, type=click.Path(exists=True),
              help="Analyte dictionary (provides default_units_by_matrix).")
@click.option("--screening", required=True, type=click.Path(exists=True),
              help="Screening levels file.")
@click.option("--report", default=None, type=click.Path(),
              help="Write report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def validate_units_cmd(analytes, screening, report, fail_on):
    """Tool: validate analyte/screening units for convertibility (headless)."""
    from autogis.core.envmon.validate_units import validate_units_config

    qa = validate_units_config(Path(analytes), Path(screening))
    _render_qa(qa, report, fail_on)


@envmon.command("reconcile-locations")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("workbook", type=click.Path(exists=True))
@click.option("--profile", "profile_path", required=True,
              type=click.Path(exists=True), help="Parser profile for the workbook.")
@click.option("--wells-csv", default=None, type=click.Path(exists=True),
              help="CSV of well IDs (headless). Mutually exclusive with --gdb.")
@click.option("--gdb", is_flag=True, default=False,
              help="Read wells from the site GDB (ArcGIS Pro only; use the .pyt).")
@click.option("--threshold", type=float, default=0.8, show_default=True)
@qa_report_options
def reconcile_locations_cmd(site_config, workbook, profile_path, wells_csv, gdb,
                            threshold, report, fail_on):
    """Tool: pre-flight check that workbook location IDs match the well layer.

    SITE_CONFIG is not read by the headless (--wells-csv) check itself: it
    supplies run-history site identity (ADR-0076), and the .pyt twin reads it
    for the GDB well layer.
    """
    from autogis.core.common.config import ParserProfile
    from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader
    from autogis.core.envmon.reconcile_locations import (
        extract_location_ids, read_well_ids_csv, reconcile, reconcile_to_qa)

    if gdb:
        _guard("reconcile-locations")
        raise click.ClickException(
            "reconcile-locations --gdb runs inside ArcGIS Pro only. Use the "
            "ReconcileSampleLocations tool in the .pyt toolbox, or pass "
            "--wells-csv for a headless check.")
    if not wells_csv:
        raise click.ClickException("provide --wells-csv PATH (headless) or "
                                   "--gdb (ArcGIS Pro).")

    profile = ParserProfile.load(Path(profile_path))
    reader = ProfileWorkbookReader(Path(workbook), profile)
    workbook_ids = extract_location_ids(reader, profile)
    well_ids = read_well_ids_csv(Path(wells_csv))

    result = reconcile(workbook_ids, well_ids, threshold=threshold)
    qa = reconcile_to_qa(result)
    _render_qa(qa, report, fail_on)


@envmon.command("evaluate-rpd-qa")
@click.option("--samples-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_Samples.")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--batch-id", default="MANUAL", show_default=True,
              help="Import batch ID label for output records.")
@qa_report_options
def evaluate_rpd_qa_cmd(samples_csv, results_csv, batch_id, report, fail_on):
    """Tool: compute RPD for EDD duplicate samples and emit QA records."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord
    from autogis.core.envmon.evaluate_rpd_qa import (
        evaluate_duplicate_rpd, read_records_csv)

    qa = QACollector()
    samples = read_records_csv(Path(samples_csv), SampleRecord)
    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    site_id = samples[0].SiteID if samples else "UNKNOWN"
    evaluate_duplicate_rpd(samples, results, site_id, batch_id, qa)
    _render_qa(qa, report, fail_on)


@envmon.command("export-summary")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--samples-csv", default=None, type=click.Path(exists=True),
              help="CSV export of Env_Samples (optional; used for metadata only).")
@click.option("--output", required=True, type=click.Path(),
              help="Output .xlsx path.")
@click.option("--site-id", default="", help="Site ID label for the summary.")
@click.option("--event-id", default="", help="Event ID label for the summary.")
def export_summary_cmd(results_csv, samples_csv, output, site_id, event_id):
    """Tool: export Env_AnalyticalResults to a four-sheet Excel summary."""
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord, SampleRecord
    from autogis.core.common.records_csv import read_records_csv
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.export_summary import export_analytical_summary

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    samples = (read_records_csv(Path(samples_csv), SampleRecord)
               if samples_csv else [])
    if not site_id and results:
        site_id = results[0].SiteID
    qa = QACollector()
    out = export_analytical_summary(samples, results, Path(output), site_id,
                                    event_id, qa=qa)
    click.echo(f"Written: {out}  ({len(results)} result(s))")
    for rec in qa.records:
        if rec.category in ("qc_rows_excluded", "fraction_resolved"):
            click.echo(f"  [canonical-read] {rec.message}")


@envmon.command("export-report-format-summary-tables")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--output", required=True, type=click.Path(),
              help="Output .xlsx path.")
@click.option("--site-id", default="",
              help="Site ID filter + label (default: first record's SiteID).")
@click.option("--no-current-event", is_flag=True, default=False,
              help="Drop the 'Current Event' sheet.")
@click.option("--no-gw-by-event", is_flag=True, default=False,
              help="Drop the 'GW by Event' sheet.")
@click.option("--no-soil-by-depth", is_flag=True, default=False,
              help="Drop the 'Soil by Depth' sheet.")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def export_report_format_summary_tables_cmd(
        results_csv, output, site_id, no_current_event, no_gw_by_event,
        no_soil_by_depth, report, fail_on):
    """Tool: export Env_AnalyticalResults to formatted report-appendix tables.

    Produces the three cross-tab sheets (Current Event / GW by Event /
    Soil by Depth). Distinct from ``export-summary`` (flat QA sheets).
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.common.records_csv import read_records_csv
    from autogis.core.envmon.export_summary_tables import export_summary_tables

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    if not site_id and results:
        site_id = results[0].SiteID
    qa = QACollector()
    out = export_summary_tables(
        results, Path(output), site_id=site_id,
        include_current_event=not no_current_event,
        include_gw_by_event=not no_gw_by_event,
        include_soil_by_depth=not no_soil_by_depth,
        qa=qa)
    click.echo(f"Written: {out}")
    _render_qa(qa, report, fail_on)


@envmon.command("evaluate-readiness")
@click.option("--site-id", required=True, help="Site ID to check.")
@click.option("--run-history", required=True, type=click.Path(),
              help="run_history.csv path (need not exist; treated as empty if absent).")
@click.option("--event-id", default=None, help="Event ID filter (optional).")
@click.option("--required-tool", "required_tools", multiple=True,
              help="Tool name that must have succeeded (repeatable).")
@click.option("--qa-report", default=None, type=click.Path(exists=False),
              help="QA CSV from a previous import (checked for ERROR rows).")
@click.option("--figure-spec", default=None, type=click.Path(exists=False),
              help="Figure spec YAML to validate.")
@qa_report_options
def evaluate_readiness_cmd(site_id, run_history, event_id, required_tools,
                           qa_report, figure_spec, report, fail_on):
    """Tool: report-readiness gate — checks required tools ran successfully."""
    from autogis.core.common.run_history import RunHistory
    from autogis.core.envmon.evaluate_readiness import evaluate_readiness

    history = RunHistory(Path(run_history))
    qa = evaluate_readiness(
        site_id=site_id,
        event_id=event_id,
        run_history=history,
        required_tools=list(required_tools),
        qa_csv=Path(qa_report) if qa_report else None,
        figure_spec_path=Path(figure_spec) if figure_spec else None)
    _render_qa(qa, report, fail_on)


@envmon.command("portfolio-metrics")
@click.option("--run-history", required=True, type=click.Path(),
              help="run_history.csv path (need not exist; treated as empty if absent).")
@click.option("--required-tool", "required_tools", multiple=True,
              help="Tool name that must have succeeded per site (repeatable).")
@click.option("--site", "site_ids", multiple=True,
              help="Restrict to this site ID (repeatable). Default: every site "
                   "found in the run history.")
@click.option("--output", default=None, type=click.Path(),
              help="Optional CSV path for the per-site rollup.")
@qa_report_options
def portfolio_metrics_cmd(run_history, required_tools, site_ids, output,
                          report, fail_on):
    """Roll up per-site report readiness across a multi-site run history."""
    from autogis.core.common.qa import QACollector
    from autogis.core.common.run_history import RunHistory
    from autogis.core.envmon.portfolio_metrics import (
        build_portfolio_metrics,
        write_portfolio_csv,
    )

    history = RunHistory(Path(run_history))
    qa = QACollector()
    statuses = build_portfolio_metrics(
        history, list(required_tools),
        site_ids=list(site_ids) or None,
        qa=qa,
    )

    n_ready = sum(1 for s in statuses if s.ready)
    click.echo(f"Sites: {len(statuses)}  Ready: {n_ready}  Not ready: {len(statuses) - n_ready}")
    for s in statuses:
        click.echo(f"  {s.site_id}: {'READY' if s.ready else 'NOT READY'}"
                   + (f" (missing: {s.missing_tools})" if s.missing_tools else ""))

    if output:
        write_portfolio_csv(statuses, Path(output))
        click.echo(f"Results written: {output}")

    _render_qa(qa, report, fail_on)


@envmon.command("compare-events")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--output", required=True, type=click.Path(),
              help="Output comparison CSV path.")
@click.option("--current-event-date", default=None,
              help="ISO date (YYYY-MM-DD) to force as the current event.")
@click.option("--stable-threshold", default=10.0, type=float,
              help="abs(%% change) <= this is STABLE (default 10).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def compare_events_cmd(results_csv, output, current_event_date,
                       stable_threshold, report, fail_on):
    """Tool 4.7: compare current vs previous monitoring event per location/analyte."""
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.compare_events import compare_events, ComparisonRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    ced = _date.fromisoformat(current_event_date) if current_event_date else None
    qa = QACollector()
    rows = compare_events(results, qa, current_event_date=ced,
                          stable_threshold=stable_threshold)
    out = write_records_csv(rows, Path(output), record_class=ComparisonRecord)
    click.echo(f"Written: {out}  ({len(rows)} comparison rows)")
    _render_qa(qa, report, fail_on)


@envmon.command("process-level-loop")
@click.option("--observations-csv", required=True, type=click.Path(exists=True),
              help="CSV of LevelLoopObservation rows (ordered).")
@click.option("--run-id", required=True)
@click.option("--site-id", required=True)
@click.option("--survey-date", required=True, help="ISO date YYYY-MM-DD.")
@click.option("--benchmark-id", required=True, help="point_id of the benchmark.")
@click.option("--known-elevation", required=True, type=float)
@click.option("--tolerance", default=None, type=float,
              help="Closure tolerance ft; default 0.05*sqrt(n_setups).")
@click.option("--run-output", required=True, type=click.Path(),
              help="Output LevelLoopRun CSV path.")
@click.option("--observations-output", required=True, type=click.Path(),
              help="Output adjusted-observations CSV path.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def process_level_loop_cmd(observations_csv, run_id, site_id, survey_date,
                           benchmark_id, known_elevation, tolerance, run_output,
                           observations_output, report, fail_on):
    """Tool 8.1: differential leveling — adjusted elevations + misclosure QA."""
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.common.schema.survey import (
        LevelLoopObservation, LevelLoopRun)
    from autogis.core.envmon.level_loop import process_level_loop

    obs = read_records_csv(Path(observations_csv), LevelLoopObservation)
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id=run_id, site_id=site_id,
        survey_date=_date.fromisoformat(survey_date),
        benchmark_id=benchmark_id, known_elevation=known_elevation,
        tolerance=tolerance, qa=qa)

    write_records_csv([run], Path(run_output), record_class=LevelLoopRun)
    write_records_csv(rows, Path(observations_output),
                      record_class=LevelLoopObservation)
    click.echo(f"Misclosure: {run.misclosure_ft} ft  "
               f"Tolerance: {run.closure_tolerance_ft} ft  "
               f"Adjusted: {run.adjusted}")
    _render_qa(qa, report, fail_on)


@envmon.command("gw-level-summary")
@click.option("--elevations-csv", required=True, type=click.Path(exists=True),
              help="CSV of ElevationHistory rows.")
@click.option("--output", required=True, type=click.Path(),
              help="Output GW level summary CSV path.")
@click.option("--event-date", required=True, help="ISO date YYYY-MM-DD.")
@click.option("--toc-csv", default=None, type=click.Path(exists=True),
              help="Optional CSV with location_id,toc_elevation columns.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def gw_level_summary_cmd(elevations_csv, output, event_date, toc_csv,
                         report, fail_on):
    """Tool 5.1: per-well GW level/DTW/trend summary from elevation history."""
    import csv as _csv
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.common.schema.survey import ElevationHistory
    from autogis.core.envmon.gw_level_summary import (
        build_gw_level_summary, GWLevelRow)

    elevations = read_records_csv(Path(elevations_csv), ElevationHistory)
    qa = QACollector()
    toc: dict = {}
    if toc_csv:
        with Path(toc_csv).open(newline="", encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                loc = (row.get("location_id") or "").strip()
                raw = (row.get("toc_elevation") or "").strip()
                # Empty -> no TOC for this well; "0" is a real datum, kept.
                if loc and raw != "":
                    try:
                        toc[loc] = float(raw)
                    except ValueError:
                        from autogis.core.common.qa import SEV_WARNING
                        qa.add(SEV_WARNING, "bad_toc_value",
                               f"{loc}: non-numeric toc_elevation {raw!r} "
                               f"ignored", location_id=loc)
    rows = build_gw_level_summary(
        elevations, toc, event_date=_date.fromisoformat(event_date), qa=qa)
    out = write_records_csv(rows, Path(output), record_class=GWLevelRow)
    click.echo(f"Written: {out}  ({len(rows)} well summary rows)")
    _render_qa(qa, report, fail_on)


def _read_id_list(path) -> set:
    """One id per line; blanks and '#' comments ignored."""
    if not path:
        return set()
    out = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return out


@envmon.command("build-gwe-event")
@click.option("--water-levels", required=True, type=click.Path(exists=True),
              help="CSV of water-level rows (location_id,gwe_ft,dtw_ft,status,...).")
@click.option("--event-date", required=True, help="ISO date YYYY-MM-DD.")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output EnvWaterLevelEvent CSV path.")
@click.option("--exclude", default=None, type=click.Path(exists=True),
              help="Text file of location_ids to exclude from contouring.")
@click.option("--perched", default=None, type=click.Path(exists=True),
              help="Text file of perched/separate-zone location_ids.")
@click.option("--anomaly-stdev", default=3.0, type=float,
              help="Robust outlier threshold (modified z-score; default 3.0).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def build_gwe_event_cmd(water_levels, event_date, out_path, exclude, perched,
                        anomaly_stdev, report, fail_on):
    """Tool 4.1: build the per-event GW-elevation contour layer with exclusion flags."""
    import csv as _csv
    from autogis.core.envmon.build_gwe_event import (
        build_gwe_event, write_gwe_event)

    with Path(water_levels).open(newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    result = build_gwe_event(
        rows, event_date=event_date,
        exclude_locations=_read_id_list(exclude),
        perched_locations=_read_id_list(perched),
        anomaly_stdev=anomaly_stdev)
    out = write_gwe_event(result, Path(out_path))
    click.echo(f"Written: {out}  ({result.contour_points} contour points, "
               f"{result.excluded} excluded, {result.anomalous} anomalous)")
    _render_qa(result.qa, report, fail_on)


@envmon.command("gen-synthetic-workbook")
@click.option("--site-id", default="TEST01", help="Synthetic site_id.")
@click.option("--wells", default=10, type=int, help="Number of wells.")
@click.option("--events", default=4, type=int, help="Number of events.")
@click.option("--features", default="",
              help="Comma-separated messiness features (e.g. 'nondetects,rpd_sheet').")
@click.option("--seed", default=0, type=int, help="Deterministic seed.")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output .xlsx path.")
def gen_synthetic_workbook_cmd(site_id, wells, events, features, seed, out_path):
    """Tool 10.6: write a seeded synthetic environmental workbook for parser hardening."""
    from autogis.core.envmon.synthetic_workbook import (
        generate_workbook, WorkbookScenario)

    feats = {f.strip() for f in features.split(",") if f.strip()}
    scenario = WorkbookScenario(site_id=site_id, n_wells=wells, n_events=events,
                                features=feats, seed=seed)
    out = generate_workbook(scenario, Path(out_path))
    click.echo(f"Written: {out}  (wells={wells}, events={events}, "
               f"features={sorted(feats) or 'clean'}, seed={seed})")


@envmon.command("build-analytical-key")
@click.option("--analyte-dict", required=True, type=click.Path(exists=True),
              help="Analyte dictionary YAML.")
@click.option("--screening-levels", required=True, type=click.Path(exists=True),
              help="Screening levels YAML.")
@click.option("--matrix", required=True, type=click.Choice(["GW", "SOIL"]),
              help="Matrix — units and screening are keyed by it.")
@click.option("--out", "out_path", default=None, type=click.Path(),
              help="Output path; format by extension (.csv/.xlsx/.md). "
                   "Omitted -> markdown to stdout.")
@click.option("--analyte-filter", default=None,
              help="Comma-separated canonical names to include.")
@click.option("--site-id", default="", help="Site id for the markdown title.")
def build_analytical_key_cmd(analyte_dict, screening_levels, matrix, out_path,
                             analyte_filter, site_id):
    """Tool 5.5: build the analytical key/legend table (analyte, units, screening, NE)."""
    from autogis.core.common.config import (
        load_analyte_dictionary, load_screening_levels)
    from autogis.core.envmon.build_analytical_key import (
        build_analytical_key, format_key_markdown, write_key_csv, write_key_xlsx)

    analytes = load_analyte_dictionary(Path(analyte_dict))
    screening = load_screening_levels(Path(screening_levels))
    flt = ([s.strip() for s in analyte_filter.split(",") if s.strip()]
           if analyte_filter else None)
    rows = build_analytical_key(analytes, screening, matrix=matrix,
                                analyte_filter=flt)
    if not out_path:
        click.echo(format_key_markdown(rows, matrix=matrix, site_id=site_id))
        return
    suffix = Path(out_path).suffix.lower()
    if suffix == ".csv":
        write_key_csv(rows, Path(out_path))
    elif suffix == ".xlsx":
        write_key_xlsx(rows, Path(out_path), matrix=matrix)
    else:
        Path(out_path).write_text(
            format_key_markdown(rows, matrix=matrix, site_id=site_id),
            encoding="utf-8")
    click.echo(f"Written: {out_path}  ({len(rows)} analytes, matrix={matrix})")


@envmon.command("identify-data-gaps")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--schedule", required=True, type=click.Path(exists=True),
              help="Expected-schedule YAML (wells + required_analytes).")
@click.option("--output", required=True, type=click.Path(),
              help="Output data-gap CSV path.")
@click.option("--event-date", default=None, help="ISO date YYYY-MM-DD.")
@click.option("--event-window-days", default=30, type=int)
@click.option("--dry-wells", default=None, type=click.Path(exists=True),
              help="Optional CSV: location_id,reason.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def identify_data_gaps_cmd(results_csv, schedule, output, event_date,
                           event_window_days, dry_wells, report, fail_on):
    """Tool 4.10: report missing wells/analytes vs an expected schedule."""
    import csv as _csv
    from datetime import date as _date
    import yaml as _yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.data_gaps import identify_data_gaps, DataGapRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    sched = _yaml.safe_load(Path(schedule).read_text(encoding="utf-8"))
    dry: dict = {}
    if dry_wells:
        with Path(dry_wells).open(newline="", encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                dry[row["location_id"]] = row.get("reason", "")
    qa = QACollector()
    gaps = identify_data_gaps(
        results, sched,
        event_date=_date.fromisoformat(event_date) if event_date else None,
        window_days=event_window_days, dry_wells=dry, qa=qa)
    out = write_records_csv(gaps, Path(output), record_class=DataGapRecord)
    click.echo(f"Written: {out}  ({len(gaps)} gap rows)")
    _render_qa(qa, report, fail_on)


@envmon.command("run-history-report")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults (all events).")
@click.option("--output", required=True, type=click.Path(),
              help="Output summary CSV path.")
@qa_report_options
def run_history_report_cmd(results_csv, output, report, fail_on):
    """Tool 10.1: per-location per-analyte history summary across events."""
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.history_report import build_history_report, HistorySummaryRow

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    out = write_records_csv(rows, Path(output), record_class=HistorySummaryRow)
    click.echo(f"Written: {out}  ({len(rows)} history row(s))")
    _render_qa(qa, report, fail_on)


@envmon.command("validate-schedule")
@click.option("--schedule", "schedule_path", required=True,
              type=click.Path(exists=True),
              help="Monitoring schedule YAML.")
@click.option("--analyte-dict", default=None, type=click.Path(exists=True),
              help="CSV with AnalyteCanonicalName column; optional.")
@qa_report_options
def validate_schedule_cmd(schedule_path, analyte_dict, report, fail_on):
    """Tool 10.2: validate monitoring schedule YAML structure and analyte names."""
    import csv as _csv
    import yaml as _yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.validate_schedule import validate_schedule

    schedule = _yaml.safe_load(Path(schedule_path).read_text(encoding="utf-8"))
    adict = None
    if analyte_dict:
        with Path(analyte_dict).open(newline="", encoding="utf-8") as fh:
            adict = {row["AnalyteCanonicalName"]
                     for row in _csv.DictReader(fh)
                     if row.get("AnalyteCanonicalName")}
    qa = QACollector()
    validate_schedule(schedule, adict, qa=qa)
    _render_qa(qa, report, fail_on)


@envmon.command("apply-screening")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--screening", "screening_path", required=True,
              type=click.Path(exists=True),
              help="Screening levels YAML (analyte -> matrix -> {unit, level, source}).")
@click.option("--output", required=True, type=click.Path(),
              help="Output CSV path (updated records).")
@qa_report_options
def apply_screening_cmd(results_csv, screening_path, output, report, fail_on):
    """Tool 3.5: re-evaluate ExceedsScreeningLevel on result records (headless)."""
    import yaml as _yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.apply_screening import apply_screening_levels

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    screening = _yaml.safe_load(Path(screening_path).read_text(encoding="utf-8"))
    qa = QACollector()
    updated = apply_screening_levels(results, screening, qa=qa)
    out = write_records_csv(updated, Path(output),
                            record_class=AnalyticalResultRecord)
    click.echo(f"Written: {out}  ({len(updated)} record(s))")
    _render_qa(qa, report, fail_on)


@envmon.command("compare-schedule-vs-actual")
@click.option("--schedule", "schedule_path", required=True,
              type=click.Path(exists=True),
              help="Schedule YAML file (site_id, wells, required_analytes).")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV of AnalyticalResultRecord rows.")
@click.option("--output", required=True, type=click.Path(),
              help="Output CSV path for gap/excess report.")
@click.option("--event-date", default=None,
              help="Event date ISO (YYYY-MM-DD); inferred from results if omitted.")
@click.option("--window-days", type=int, default=30, show_default=True,
              help="Include results within this many days before event-date.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def compare_schedule_vs_actual_cmd(
    schedule_path, results_csv, output, event_date, window_days, report, fail_on
):
    """Compare scheduled monitoring wells/analytes vs actual results (headless)."""
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.schedule_vs_actual import (
        compare_schedule_vs_actual,
        load_schedule_yaml,
        write_gap_csv,
    )

    schedule = load_schedule_yaml(Path(schedule_path))
    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    event_dt = _date.fromisoformat(event_date) if event_date else None
    qa = QACollector()

    rows = compare_schedule_vs_actual(
        results, schedule,
        event_date=event_dt,
        window_days=window_days,
        qa=qa,
    )
    write_gap_csv(rows, Path(output))
    click.echo(f"Written: {output}  ({len(rows)} record(s))")

    n_missing = sum(1 for r in rows if r.Status == "MISSING")
    n_unexpected = sum(1 for r in rows if r.Status == "UNEXPECTED")
    click.echo(f"  MISSING: {n_missing}  UNEXPECTED: {n_unexpected}")

    _render_qa(qa, report, fail_on)


@envmon.command("drone-checkpoint-qa")
@click.option("--checkpoints", "checkpoints_csv", required=True,
              type=click.Path(exists=True),
              help="Checkpoint CSV (gcp_id, expected_x/y/z, measured_x/y/z).")
@click.option("--hrms-threshold", type=float, default=0.05, show_default=True,
              help="Horizontal RMSE threshold in metres.")
@click.option("--vrms-threshold", type=float, default=0.10, show_default=True,
              help="Vertical RMSE threshold in metres.")
@click.option("--output", default=None, type=click.Path(),
              help="Optional CSV path for per-point results.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def drone_checkpoint_qa_cmd(
    checkpoints_csv, hrms_threshold, vrms_threshold, output, report, fail_on
):
    """Tool 11.1: evaluate GCP checkpoint accuracy (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.drone_checkpoint_qa import (
        evaluate_gcp_checkpoints,
        read_checkpoint_csv,
        write_results_csv,
    )

    checkpoints = read_checkpoint_csv(Path(checkpoints_csv))
    qa = QACollector()
    summary = evaluate_gcp_checkpoints(
        checkpoints,
        hrms_threshold=hrms_threshold,
        vrms_threshold=vrms_threshold,
        qa=qa,
    )

    click.echo(f"Checkpoints: {summary.n_points}")
    click.echo(f"HRMS: {summary.hrms:.4f} m  (threshold: {hrms_threshold} m)"
               f"  -> {'PASS' if summary.hrms_pass else 'FAIL'}")
    click.echo(f"VRMS: {summary.vrms:.4f} m  (threshold: {vrms_threshold} m)"
               f"  -> {'PASS' if summary.vrms_pass else 'FAIL'}")
    click.echo(f"Overall: {'PASS' if summary.overall_pass else 'FAIL'}")

    if output:
        write_results_csv(summary, Path(output))
        click.echo(f"Results written: {output}")

    # _render_qa exits non-zero when a SEV_ERROR is present; evaluate_gcp_checkpoints
    # emits SEV_ERROR for every overall failure, so a FAIL already exits there.
    _render_qa(qa, report, fail_on)


@envmon.command("rtk-control-check")
@click.option("--control-points", "control_csv", required=True,
              type=click.Path(exists=True),
              help="Control-check CSV (control_id, published_x/y/z, surveyed_x/y/z).")
@click.option("--horizontal-tolerance-ft", type=float, default=0.05, show_default=True,
              help="Max allowed horizontal distance per point, in feet.")
@click.option("--vertical-tolerance-ft", type=float, default=0.10, show_default=True,
              help="Max allowed vertical distance per point, in feet.")
@click.option("--output", default=None, type=click.Path(),
              help="Optional CSV path for per-point results.")
@qa_report_options
def rtk_control_check_cmd(
    control_csv, horizontal_tolerance_ft, vertical_tolerance_ft, output,
    report, fail_on,
):
    """Compare RTK-surveyed control shots to published benchmarks (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.rtk_control_check import (
        evaluate_control_check,
        read_control_check_csv,
        write_results_csv,
    )

    points = read_control_check_csv(Path(control_csv))
    qa = QACollector()
    summary = evaluate_control_check(
        points,
        horizontal_tolerance_ft=horizontal_tolerance_ft,
        vertical_tolerance_ft=vertical_tolerance_ft,
        qa=qa,
    )

    click.echo(f"Control points: {summary.n_points}")
    click.echo(f"Pass: {summary.n_pass}  Fail: {summary.n_fail}")
    click.echo(f"RMSE horizontal: {summary.rmse_horizontal:.4f} ft  "
               f"RMSE vertical: {summary.rmse_vertical:.4f} ft")
    click.echo(f"Overall: {'PASS' if summary.overall_pass else 'FAIL'}")

    if output:
        write_results_csv(summary, Path(output))
        click.echo(f"Results written: {output}")

    _render_qa(qa, report, fail_on)


@envmon.command("export-geojson")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV of AnalyticalResultRecord rows (e.g. apply-screening output).")
@click.option("--coords-csv", required=True, type=click.Path(exists=True),
              help="CSV with columns: location_id, x, y")
@click.option("--output", required=True, type=click.Path(),
              help="Output GeoJSON file path (e.g. results.geojson).")
@click.option("--indent", type=int, default=2, show_default=True,
              help="JSON indent level (0 = compact).")
@click.option("--report", default=None, type=click.Path(),
              help="Optional QA report output path.")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def export_geojson_cmd(results_csv, coords_csv, output, indent, report, fail_on):
    """Tool 10.3: export analytical results to GeoJSON FeatureCollection (headless)."""
    import json as _json
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.export_geojson import build_geojson, load_well_coords
    from autogis.core.common.records_csv import read_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    coords = load_well_coords(Path(coords_csv))
    qa = QACollector()
    fc = build_geojson(results, coords, qa=qa)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(fc, indent=indent or None), encoding="utf-8")
    click.echo(f"Written: {out}  ({len(fc['features'])} feature(s))")
    _render_qa(qa, report, fail_on)


@envmon.command("generate-arcade-labels")
@click.option(
    "--analytes", "analytes_str", required=True,
    help="Comma-separated analyte names (e.g. 'Benzene,PCE,Toluene').",
)
@click.option(
    "--field-prefix", default="",
    help="Optional field name prefix (e.g. 'Env_').",
)
@click.option(
    "--out", required=True, type=click.Path(),
    help="Output JSON file path.",
)
@click.option(
    "--report", default=None, type=click.Path(),
    help="Optional QA report output path.",
)
def generate_arcade_labels_cmd(analytes_str, field_prefix, out, report):
    """Tool 5.4: generate Arcade label expressions for ArcGIS Pro layers (headless)."""
    from autogis.core.common.qa import QACollector, SEV_INFO
    from autogis.core.envmon.arcade_label_generator import (
        generate_arcade_labels, write_label_expressions,
    )

    analytes = [a.strip() for a in analytes_str.split(",") if a.strip()]
    if not analytes:
        raise click.UsageError("--analytes must contain at least one analyte name.")

    specs = generate_arcade_labels(analytes, field_prefix=field_prefix)
    write_label_expressions(specs, Path(out))

    qa = QACollector()
    qa.add(
        SEV_INFO, "arcade_labels_written",
        f"{len(specs)} expression(s) for {len(analytes)} analyte(s) → {out}",
    )
    click.echo(
        f"Written {len(specs)} Arcade expression(s) for {len(analytes)} "
        f"analyte(s) to: {out}"
    )
    _render_qa(qa, report, "error")


@envmon.command("generate-python-labels")
@click.option(
    "--analytes", "analytes_str", required=True,
    help="Comma-separated analyte names (e.g. 'Benzene,PCE,Toluene').",
)
@click.option(
    "--field-prefix", default="",
    help="Optional field name prefix (e.g. 'Env_').",
)
@click.option(
    "--out", required=True, type=click.Path(),
    help="Output JSON file path.",
)
@click.option(
    "--report", default=None, type=click.Path(),
    help="Optional QA report output path.",
)
def generate_python_labels_cmd(analytes_str, field_prefix, out, report):
    """Tool 5.4b: generate Python label expressions for ArcGIS Pro layers (headless)."""
    from autogis.core.common.qa import QACollector, SEV_INFO
    from autogis.core.envmon.python_label_generator import (
        generate_python_labels, write_label_expressions,
    )

    analytes = [a.strip() for a in analytes_str.split(",") if a.strip()]
    if not analytes:
        raise click.UsageError("--analytes must contain at least one analyte name.")

    specs = generate_python_labels(analytes, field_prefix=field_prefix)
    write_label_expressions(specs, Path(out))

    qa = QACollector()
    qa.add(
        SEV_INFO, "python_labels_written",
        f"{len(specs)} expression(s) for {len(analytes)} analyte(s) → {out}",
    )
    click.echo(
        f"Written {len(specs)} Python expression(s) for {len(analytes)} "
        f"analyte(s) to: {out}"
    )
    _render_qa(qa, report, "error")


@envmon.command("generate-event-changelog")
@click.option("--prior-csv", required=True, type=click.Path(exists=True),
              help="CSV of prior event analytical results (LocationID, AnalyteName, "
                   "ResultNumeric, ExceedsScreeningLevel columns required).")
@click.option("--current-csv", required=True, type=click.Path(exists=True),
              help="CSV of current event analytical results.")
@click.option("--prior-event-id", default="prior", show_default=True,
              help="Label for the prior event (e.g. 'E-2025-Q3').")
@click.option("--current-event-id", default="current", show_default=True,
              help="Label for the current event (e.g. 'E-2026-Q1').")
@click.option("--out", required=True, type=click.Path(),
              help="Output changelog CSV path.")
@click.option("--out-xlsx", default=None, type=click.Path(),
              help="Optional output Excel workbook (one sheet per change type).")
@click.option("--delta-pct-threshold", default=10.0, type=float, show_default=True,
              help="Minimum absolute %% change required to classify as VALUE_CHANGE.")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def generate_event_changelog_cmd(
    prior_csv, current_csv, prior_event_id, current_event_id,
    out, out_xlsx, delta_pct_threshold, report, fail_on,
):
    """Tool 9.3: Generate structured changelog from two monitoring event CSVs.

    Diffs prior and current result CSVs, classifies every (LocationID, AnalyteName)
    pair as NEW_LOCATION, DROPPED_LOCATION, NEW_ANALYTE, DROPPED_ANALYTE,
    NEW_EXCEEDANCE, CLEARED_EXCEEDANCE, VALUE_CHANGE, or NO_CHANGE.
    Headless, no arcpy.
    """
    import csv as _csv
    from autogis.core.envmon.event_changelog import (
        generate_event_changelog,
        write_changelog_csv,
        write_changelog_workbook,
    )

    def _read_csv(path: str) -> list:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(_csv.DictReader(fh))

    prior_rows = _read_csv(prior_csv)
    current_rows = _read_csv(current_csv)

    result = generate_event_changelog(
        prior_rows,
        current_rows,
        prior_event_id=prior_event_id,
        current_event_id=current_event_id,
        delta_pct_threshold=delta_pct_threshold,
    )

    write_changelog_csv(result, Path(out))
    click.echo(f"Written: {out}  ({len(result.changes)} record(s))")
    click.echo(
        f"  NEW_LOCATION: {result.new_location_count}  "
        f"DROPPED_LOCATION: {result.dropped_location_count}  "
        f"NEW_EXCEEDANCE: {result.new_exceedance_count}  "
        f"CLEARED_EXCEEDANCE: {result.cleared_exceedance_count}"
    )

    if out_xlsx:
        write_changelog_workbook(result, Path(out_xlsx))
        # Only report the workbook when it was actually written; on a missing
        # openpyxl the writer records a QA error and returns without a file.
        if Path(out_xlsx).exists():
            click.echo(f"Workbook: {out_xlsx}")

    _render_qa(result.qa, report, fail_on)


@envmon.command("generate-event-report")
@click.option("--site", "site_id", required=True, help="Site ID.")
@click.option("--event", "event_id", required=True,
              help="Event identifier (e.g. 2026Q2).")
@click.option("--output", required=True, type=click.Path(),
              help="Output file path (.md or .html per --format).")
@click.option("--results-csv", default=None, type=click.Path(),
              help="Analytical results CSV (absent file -> empty section).")
@click.option("--comparison-csv", default=None, type=click.Path(),
              help="compare-events output CSV (absent file -> empty section).")
@click.option("--history-csv", default=None, type=click.Path(),
              help="run-history-report output CSV (absent file -> empty section).")
@click.option("--gaps-csv", default=None, type=click.Path(),
              help="identify-data-gaps output CSV (absent file -> empty section).")
@click.option("--rpd-qa-csv", default=None, type=click.Path(),
              help="evaluate-rpd-qa output CSV (absent file -> empty section).")
@click.option("--format", "fmt", type=click.Choice(["md", "html"]),
              default="md", show_default=True, help="Output format.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def generate_event_report_cmd(
    site_id, event_id, output, fmt,
    results_csv, comparison_csv, history_csv, gaps_csv, rpd_qa_csv,
    report, fail_on,
):
    """Assemble a monitoring event report (Markdown or HTML) from CSV tool outputs (post-roadmap extra; not a numbered roadmap tool)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.generate_event_report import (
        generate_event_report, generate_event_report_html,
    )

    qa = QACollector()
    render = generate_event_report_html if fmt == "html" else generate_event_report
    content = render(
        site_id, event_id,
        results_csv=Path(results_csv) if results_csv else None,
        comparison_csv=Path(comparison_csv) if comparison_csv else None,
        history_csv=Path(history_csv) if history_csv else None,
        gaps_csv=Path(gaps_csv) if gaps_csv else None,
        rpd_qa_csv=Path(rpd_qa_csv) if rpd_qa_csv else None,
        qa=qa,
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    click.echo(f"Written: {out}")
    _render_qa(qa, report, fail_on)


@envmon.command("well-inspection-report")
@click.option("--wells-csv", required=True, type=click.Path(exists=True),
              help="Wells CSV; must include a WellID column.")
@click.option("--site", "site_id", required=True, help="Site ID.")
@click.option("--output-dir", required=True, type=click.Path(),
              help="Directory to write one Markdown file per well + SiteSummary.md.")
@click.option("--maintenance-log-csv", default=None, type=click.Path(),
              help="Optional maintenance log CSV (WellID, InspectionDate, "
                   "Condition, Notes). Absent file -> no inspection history.")
@click.option("--format", "fmt", type=click.Choice(["md", "html"]),
              default="md", show_default=True,
              help="Output format for each per-well file + the site summary.")
@click.option("--manifest", "manifest_path", default=None, type=click.Path(),
              help="Attachment harvester manifest (.csv/.json); HTML only, enables photos.")
@click.option("--harvest-dir", default=None, type=click.Path(),
              help="Harvest output dir (photo saved_path root); HTML only, enables photos.")
@qa_report_options
def well_inspection_report_cmd(wells_csv, site_id, output_dir,
                               maintenance_log_csv, fmt, manifest_path,
                               harvest_dir, report, fail_on):
    """Generate well inspection reports + a site summary (Markdown or HTML) (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.well_inspection_report import build_well_inspection_reports

    # Guard against silently-ignored photo inputs (photos need both, HTML only).
    if (manifest_path or harvest_dir) and not (manifest_path and harvest_dir):
        raise click.UsageError("--manifest and --harvest-dir must be given together.")
    if (manifest_path or harvest_dir) and fmt != "html":
        raise click.UsageError("--manifest/--harvest-dir require --format html.")

    qa = QACollector()
    written = build_well_inspection_reports(
        Path(wells_csv), Path(output_dir),
        site_id=site_id,
        maintenance_log_csv=Path(maintenance_log_csv) if maintenance_log_csv else None,
        fmt=fmt,
        manifest_path=Path(manifest_path) if manifest_path else None,
        harvest_dir=Path(harvest_dir) if harvest_dir else None,
        qa=qa,
    )
    click.echo(f"Written {len(written)} {fmt.upper()} file(s) to {output_dir}")
    _render_qa(qa, report, fail_on)


@envmon.command("run-history")
@click.option(
    "--run-history", "history_path", required=True, type=click.Path(),
    help="Path to run_history.csv (need not exist; treated as empty if absent).",
)
@click.option("--site", "site_id", default=None, help="Filter by site ID.")
@click.option("--tool", "tool_name", default=None, help="Filter by tool name.")
@click.option(
    "--status", default=None,
    type=click.Choice(["success", "warning", "error", "cancelled"]),
    help="Filter by run status.",
)
@click.option("--since", default=None, help="Only runs since this ISO date (YYYY-MM-DD).")
@click.option("--limit", type=int, default=0, help="Max records to show (0 = all).")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "csv", "json"]),
    default="table", show_default=True,
)
def run_history_cmd(history_path, site_id, tool_name, status, since, limit, fmt):
    """Query the tool run history CSV (headless)."""
    import json as _json
    import csv as _csv
    import io
    from datetime import datetime as _dt
    from dataclasses import asdict
    from autogis.core.common.run_history import RunHistory

    history = RunHistory(Path(history_path))
    since_dt = _dt.fromisoformat(since) if since else None
    records = history.query(
        site_id=site_id,
        tool_name=tool_name,
        since=since_dt,
        status=status,
    )
    if limit and limit > 0:
        records = records[-limit:]

    # Each format handles the empty case itself so json/csv stay machine-parseable
    # ([] / header-only); the human-readable count is emitted only for `table`.
    if fmt == "json":
        payload = []
        for r in records:
            d = asdict(r)
            d["started_at"] = r.started_at.isoformat()
            d["finished_at"] = r.finished_at.isoformat()
            payload.append(d)
        click.echo(_json.dumps(payload, indent=2))
    elif fmt == "csv":
        buf = io.StringIO()
        cols = [
            "run_id", "tool_name", "site_id", "event_id",
            "started_at", "finished_at", "status",
            "qa_count_error", "qa_count_warning", "message",
        ]
        w = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = asdict(r)
            row["started_at"] = r.started_at.isoformat()
            row["finished_at"] = r.finished_at.isoformat()
            w.writerow(row)
        click.echo(buf.getvalue().rstrip())
    else:  # table
        hdr = (
            f"{'tool_name':<28} {'site_id':<12} {'status':<10}"
            f" {'finished_at':<20} msg"
        )
        click.echo(hdr)
        click.echo("-" * len(hdr))
        for r in records:
            click.echo(
                f"{r.tool_name:<28} {r.site_id:<12} {r.status:<10} "
                f"{r.finished_at.isoformat():<20} {r.message[:40]}"
            )
        click.echo(f"\n{len(records)} record(s).")


def _render_qa(qa, report, fail_on):
    """Shared rendering + exit-code helper for headless QA-producing commands."""
    ctx = click.get_current_context(silent=True)
    if ctx is not None:
        ctx.meta[_QA_COUNTS_META_KEY] = dict(qa.counts_by_severity())
    for rec in sorted(qa.records,
                      key=lambda r: {"CRITICAL": 0, "ERROR": 1, "WARNING": 2,
                                     "INFO": 3}.get(r.severity, 4)):
        click.echo(f"[{rec.severity}] {rec.category}: {rec.message}"
                   + (f" -> {rec.recommended_action}"
                      if rec.recommended_action else ""))
    if report:
        p = Path(report)
        if p.suffix == ".json":
            qa.write_json_summary(p)
        elif p.suffix == ".csv":
            qa.write_csv(p)
        else:
            qa.write_markdown(p)
        click.echo(f"Wrote report: {p}")
    allow_warnings = fail_on != "warning"
    status = qa.status(allow_warnings=allow_warnings, allow_errors=False)
    click.echo(f"Status: {status}")
    if status == "FAIL":
        raise SystemExit(1)


# --------------------------------------------------------------------------
# LOCAL tools (2-8) — registered but runtime-guarded. The core call is only
# reached when arcpy is present (in ArcGIS Pro). No rich ergonomics here; the
# .pyt is their primary UI (Global Constraints).
# --------------------------------------------------------------------------
@envmon.command("qualify")
@click.option("--out", "out_dir", required=True,
              type=click.Path(file_okay=False),
              help="Directory for qualification.json/.md and run history.")
@click.option("--self-test", is_flag=True,
              help="Run only the two detector canaries.")
def qualify_cmd(out_dir, self_test):
    """Qualify the installed ArcGIS Pro runtime and Python toolbox."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AUTOGIS_RUN_HISTORY"] = str(out_dir / "run_history.csv")
    try:
        _guard("qualify")
    except click.ClickException as exc:
        click.echo(f"Precondition failed: {exc.format_message()}", err=True)
        raise SystemExit(2)

    from autogis.adapters.qualification import (
        QualificationPreconditionError,
        run_qualification,
    )
    try:
        report, paths, exit_code = run_qualification(
            out_dir, self_test=self_test)
    except QualificationPreconditionError as exc:
        click.echo(f"Precondition failed: {exc}", err=True)
        raise SystemExit(2)

    click.echo(f"Wrote report: {paths[0]}")
    click.echo(f"Wrote report: {paths[1]}")
    summary = report.summary
    click.echo(
        f"Summary: {summary['pass']} pass, {summary['fail']} fail, "
        f"{summary['skip']} skip")
    if self_test:
        click.echo("Self-test: " + ("PASS" if exit_code == 0 else "FAIL"))
    if exit_code:
        raise SystemExit(exit_code)


@envmon.command("import-gdb")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("workbook", type=click.Path(exists=True))
def import_gdb_cmd(site_config, workbook):
    """Tool 2: import a workbook into the file geodatabase (ArcGIS Pro)."""
    _guard("import-gdb")
    from autogis.core.envmon import import_to_gdb  # noqa: F401  (arcpy path)
    raise click.ClickException(
        "import-gdb runs inside ArcGIS Pro only. Use the ImportToGdb "
        "tool in the .pyt toolbox."
    )


@envmon.command("build-event")
@click.argument("site_config", type=click.Path(exists=True))
def build_event_cmd(site_config):
    """Tool 3: build the current-event feature data (ArcGIS Pro)."""
    _guard("build-event")
    from autogis.core.envmon import build_current_event  # noqa: F401
    raise click.ClickException(
        "build-event runs inside ArcGIS Pro only. Use the BuildCurrentEvent "
        "tool in the .pyt toolbox."
    )


@envmon.command("build-callouts")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("figure_spec", type=click.Path(exists=True))
@click.option("--use-hull-collision", is_flag=True, default=False,
              help="Use convex-hull (numpy) callout collision detection "
                   "(Tool 5.2, ADR-0020). Mirrors the BuildCallouts .pyt "
                   "parameter of the same name.")
def build_callouts_cmd(site_config, figure_spec, use_hull_collision):
    """Tool 4: generate callout feature classes (ArcGIS Pro)."""
    _guard("build-callouts")
    from autogis.core.envmon import build_figure_dataset  # noqa: F401
    raise click.ClickException(
        "build-callouts runs inside ArcGIS Pro only. Use the BuildCallouts "
        "tool in the .pyt toolbox"
        + (" with 'Use hull collision (numpy)' enabled."
           if use_hull_collision else ".")
    )


@envmon.command("optimize-callouts")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("figure_spec", type=click.Path(exists=True))
def optimize_callouts_cmd(site_config, figure_spec):
    """Tool 5.2: hull-collision callout placement (see build-callouts)."""
    _guard("optimize-callouts")
    raise click.ClickException(
        "optimize-callouts (Tool 5.2) was folded into build-callouts as its "
        "--use-hull-collision flag (ADR-0020). Use the BuildCallouts tool "
        "in the .pyt toolbox with 'Use hull collision (numpy)' enabled."
    )


@envmon.group("manage-callout-overrides")
def manage_callout_overrides_group():
    """Tool 5.3: manage callout placement overrides (ArcGIS Pro)."""


_OV_GDB = click.argument("gdb", type=click.Path(exists=True))
_OV_SITE = click.option("--site", required=True, help="SiteID to scope the query.")
_OV_SPEC = click.option("--spec", required=True, help="FigureSpecID to scope the query.")


@manage_callout_overrides_group.command("list")
@_OV_GDB
@_OV_SITE
@_OV_SPEC
@click.option("--map-type", default="",
              help="MapType to scope the listing (default: blank). Overrides "
                   "are keyed per map type; list one at a time.")
def manage_overrides_list_cmd(gdb, site, spec, map_type):
    """List placement overrides for a site/figure spec/map type."""
    _guard("manage-callout-overrides")
    from autogis.core.envmon.manage_callout_overrides import load_overrides
    overrides = load_overrides(gdb, site, spec, map_type)
    if not overrides:
        click.echo(f"No overrides for {site}/{spec}"
                   f"/{map_type or 'blank'}.")
        return
    for loc, ov in sorted(overrides.items()):
        origin = ov["origin"]
        pos = (f"origin=({origin[0]:.2f}, {origin[1]:.2f})" if origin
               else "origin=auto")
        quad = ov["preferred_quadrant"] or "-"
        state = "LOCKED" if ov["locked"] else "unlocked"
        click.echo(f"{loc}: {pos} quadrant={quad} [{state}]")
    click.echo(f"{len(overrides)} override(s).")


@manage_callout_overrides_group.command("clear")
@_OV_GDB
@_OV_SITE
@_OV_SPEC
def manage_overrides_clear_cmd(gdb, site, spec):
    """Delete all unlocked overrides for a site/figure spec."""
    _guard("manage-callout-overrides")
    from autogis.core.envmon.manage_callout_overrides import (
        clear_unlocked_overrides,
    )
    n = clear_unlocked_overrides(gdb, site, spec)
    click.echo(f"Cleared {n} unlocked override(s) for {site}/{spec}.")


@manage_callout_overrides_group.command("lock")
@_OV_GDB
@_OV_SITE
@_OV_SPEC
@click.option("--location", required=True, help="LocationID to lock.")
@click.option("--anchor-x", type=float, required=True,
              help="Box lower-left X in map units.")
@click.option("--anchor-y", type=float, required=True,
              help="Box lower-left Y in map units.")
@click.option("--map-type", default="",
              help="MapType key of the override row (default: blank).")
def manage_overrides_lock_cmd(gdb, site, spec, location,
                               anchor_x, anchor_y, map_type):
    """Lock a callout to a fixed position."""
    _guard("manage-callout-overrides")
    from autogis.core.envmon.manage_callout_overrides import (
        CalloutOverride, get_override, save_override,
    )
    ov = get_override(gdb, site, spec, location, map_type=map_type)
    if ov is None:
        ov = CalloutOverride(site_id=site, location_id=location,
                             figure_spec_id=spec, map_type=map_type)
    ov.anchor_x = anchor_x
    ov.anchor_y = anchor_y
    # The anchor IS the box lower-left; stale offsets would shift it.
    ov.offset_x = 0.0
    ov.offset_y = 0.0
    ov.locked = True
    save_override(gdb, ov)
    click.echo(f"Locked {location} at ({anchor_x}, {anchor_y}) "
               f"for {site}/{spec}.")


@manage_callout_overrides_group.command("unlock")
@_OV_GDB
@_OV_SITE
@_OV_SPEC
@click.option("--location", required=True, help="LocationID to unlock.")
@click.option("--map-type", default="",
              help="MapType key of the override row (default: blank).")
def manage_overrides_unlock_cmd(gdb, site, spec, location, map_type):
    """Clear a callout's lock; its position becomes an adjustable candidate."""
    _guard("manage-callout-overrides")
    from autogis.core.envmon.manage_callout_overrides import (
        get_override, save_override,
    )
    ov = get_override(gdb, site, spec, location, map_type=map_type)
    if ov is None:
        raise click.ClickException(
            f"No override found for {location} ({site}/{spec}, "
            f"map type {map_type or 'blank'}).")
    ov.locked = False
    save_override(gdb, ov)
    click.echo(f"Unlocked {location} for {site}/{spec}.")


@envmon.command("gw-contours")
@click.argument("site_config", type=click.Path(exists=True))
def gw_contours_cmd(site_config):
    """Tool 5: build groundwater contours (ArcGIS Pro)."""
    _guard("gw-contours")
    from autogis.core.envmon import groundwater_contours  # noqa: F401
    raise click.ClickException(
        "gw-contours runs inside ArcGIS Pro only. Use the GroundwaterContours "
        "tool in the .pyt toolbox."
    )


@envmon.command("run-gw-model-pipeline")
@click.argument("site_config", type=click.Path(exists=True))
def run_gw_model_pipeline_cmd(site_config):
    """RunFieldToGroundwaterModelPipeline: multi-model draft contours +
    leave-one-out cross-validation ranking (ArcGIS Pro)."""
    _guard("run-gw-model-pipeline")
    from autogis.core.envmon import gw_model_pipeline  # noqa: F401
    raise click.ClickException(
        "run-gw-model-pipeline runs inside ArcGIS Pro only. Use the "
        "RunGWModelPipeline tool in the .pyt toolbox."
    )


@envmon.command("approve-gw-model")
@click.option("--gdb", required=True, type=click.Path(),
              help="File geodatabase holding GW_ModelRun (schema >= 2.4).")
@click.option("--run-id", required=True, help="GW_ModelRun.RunID to approve.")
@click.option("--model", required=True,
              help="Model name to approve (must have been in the run; any "
                   "rank — hydro judgment trumps the metric).")
@click.option("--reviewer", default="", help="Reviewer name for the record.")
def approve_gw_model_cmd(gdb, run_id, model, reviewer):
    """BuildGroundwaterSurfaceModel approval verb: record the
    hydrogeologist's model choice on a DRAFT run (ArcGIS Pro)."""
    _guard("approve-gw-model")
    from autogis.core.envmon.gw_model_pipeline import approve_gw_model
    if approve_gw_model(gdb, run_id, model, reviewer=reviewer):
        click.echo(f"Run {run_id}: ApprovedModel={model}, "
                   "ReviewStatus=APPROVED.")
    else:
        raise click.ClickException(
            f"Not approved: run {run_id!r} not found, {model!r} was not one "
            "of its models, or GW_ModelRun tables are missing (run "
            "upgrade-schema first).")


@envmon.command("export-figures")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("figure_spec", type=click.Path(exists=True))
def export_figures_cmd(site_config, figure_spec):
    """Tool 6: export figure layouts (ArcGIS Pro)."""
    _guard("export-figures")
    from autogis.core.envmon import export_figures  # noqa: F401
    raise click.ClickException(
        "export-figures runs inside ArcGIS Pro only. Use the ExportFigures "
        "tool in the .pyt toolbox."
    )


@envmon.command("full-pipeline")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("workbook", type=click.Path(exists=True))
def full_pipeline_cmd(site_config, workbook):
    """Tool 7: run the full import-to-figures pipeline (ArcGIS Pro)."""
    _guard("full-pipeline")
    from autogis.core.envmon import import_to_gdb  # noqa: F401
    raise click.ClickException(
        "full-pipeline runs inside ArcGIS Pro only. Use the FullPipeline "
        "tool in the .pyt toolbox."
    )


@envmon.command("validate-db")
@click.argument("gdb", type=click.Path())
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary YAML (enables analyte-name QA checks).")
@qa_report_options
def validate_db_cmd(gdb, analytes, report, fail_on):
    """Tool 8: validate the GDB schema and cross-table integrity (ArcGIS Pro)."""
    _guard("validate-db")
    from autogis.core.common.config import load_analyte_dictionary
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.validate_database import validate_database

    analyte_dict = {}
    if analytes:
        analyte_dict = load_analyte_dictionary(Path(analytes)) or {}
    qa = QACollector()
    validate_database(Path(gdb), qa, analyte_dict)
    _render_qa(qa, report, fail_on)


@envmon.command("evaluate-rpd")
@click.argument("workbook", type=click.Path(exists=True))
@click.argument("profile", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--batch-id", default="", show_default=True)
@click.option("--threshold", type=float, default=30.0, show_default=True,
              help="RPD exceedance threshold (pct, default 30).")
@qa_report_options
def evaluate_rpd_cmd(workbook, profile, site_id, batch_id, threshold, report, fail_on):
    """Evaluate field duplicate RPD values against a threshold (headless)."""
    from autogis.core.common.config import ParserProfile
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.normalize_rpd import normalize_rpd_table
    from autogis.core.envmon.evaluate_rpd import evaluate_rpd_records, rpd_to_qa
    parser = ParserProfile.load(Path(profile))
    qa_import = QACollector()
    records = normalize_rpd_table(Path(workbook), parser, site_id, batch_id, qa_import)
    result = evaluate_rpd_records(records, rpd_threshold_pct=threshold)
    qa = rpd_to_qa(result)
    qa.records = qa_import.records + qa.records
    _render_qa(qa, report, fail_on)


@envmon.command("import-edd")
@click.option("--edd", "edd_path", required=True, type=click.Path(exists=True),
              help="Path to EDD CSV or XLSX file.")
@click.option("--profile-path", required=True, type=click.Path(exists=True),
              help="Path to lab profile YAML.")
@click.option("--site", "site_id", required=True,
              help="Site ID (e.g. H281).")
@click.option("--gdb", "gdb_path", required=True, type=click.Path(),
              help="Path to target file GDB.")
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary YAML (optional).")
@click.option("--screening", default=None, type=click.Path(exists=True),
              help="Screening levels YAML (optional).")
@click.option("--event-date", default=None,
              help="Override event date ISO8601 (YYYY-MM-DD).")
@qa_report_options
def import_edd_cmd(edd_path, profile_path, site_id, gdb_path,
                   analytes, screening, event_date, report, fail_on):
    """Tool 2.3: import a lab EDD CSV/XLSX into the envmon GDB (needs ArcGIS Pro)."""
    _guard("import-edd")
    from autogis.core.envmon.edd_profile import LabEDDProfile
    from autogis.core.envmon.edd_importer import run_edd_import
    from autogis.core.common.config import load_config
    from autogis.core.common.qa import QACollector

    profile = LabEDDProfile.load(Path(profile_path))
    analyte_dictionary = load_config(Path(analytes)) if analytes else {}
    screening_levels = load_config(Path(screening)) if screening else {}

    override = None
    if event_date:
        from datetime import date as _date
        try:
            override = _date.fromisoformat(event_date)
        except ValueError:
            raise click.BadParameter(
                f"Invalid date '{event_date}'; use YYYY-MM-DD",
                param_hint="--event-date")

    qa = QACollector()
    batch_id = run_edd_import(
        edd_path=Path(edd_path),
        profile=profile,
        gdb_path=Path(gdb_path),
        site_id=site_id,
        analyte_dictionary=analyte_dictionary,
        screening_levels=screening_levels,
        event_date_override=override,
        qa=qa,
    )
    click.echo(f"Import complete. Batch ID: {batch_id}")
    _render_qa(qa, report, fail_on)


@envmon.command("upgrade-schema")
@click.argument("gdb")
@click.option("--spatial-reference", "spatial_reference", type=int, default=4326,
              help="WKID for the output spatial reference (default: 4326 = GCS WGS 1984).")
def upgrade_schema_cmd(gdb, spatial_reference):
    """Upgrade a file GDB to the current envmon schema version (ArcGIS Pro)."""
    _guard("upgrade-schema")
    from autogis.core.envmon.upgrade_schema import upgrade_gdb_schema, format_report
    report = upgrade_gdb_schema(gdb, spatial_reference)
    click.echo(format_report(report))


@envmon.command("export-snapshot")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--event", "event_id", required=True)
@click.option("--out", "out_dir", required=True, type=click.Path())
@click.option("--compress", is_flag=True, default=False,
              help="ZIP the output GDB after creation.")
def export_snapshot_cmd(gdb, site_id, event_id, out_dir, compress):
    """Freeze a GDB snapshot for a reporting event (ArcGIS Pro)."""
    _guard("export-snapshot")
    from autogis.core.envmon.export_snapshot import export_event_snapshot, format_manifest
    manifest = export_event_snapshot(gdb, site_id, event_id, out_dir, compress)
    click.echo(format_manifest(manifest))

@envmon.command("build-survey-form")
@click.option("--site", "site_path", required=True,
              type=click.Path(exists=True), help="Site config YAML.")
@click.option("--analytes", "analytes_path", required=True,
              type=click.Path(exists=True), help="Analyte dictionary YAML.")
@click.option("--event", "event_path", required=True,
              type=click.Path(exists=True), help="Event config YAML.")
@click.option("--out", "out_path", required=True,
              type=click.Path(), help="Output .xlsx path.")
def build_survey_form_cmd(site_path, analytes_path, event_path, out_path):
    """Tool 7.1a: generate a Survey123 XLSForm from site/event/analyte config."""
    import yaml
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    site_cfg = yaml.safe_load(open(site_path, encoding="utf-8"))
    analytes = yaml.safe_load(open(analytes_path, encoding="utf-8"))
    event_cfg = yaml.safe_load(open(event_path, encoding="utf-8"))
    wb = build_xlsform(site_cfg, event_cfg, analytes)
    wb.save(out_path)
    click.echo(f"XLSForm written to {out_path}")


@envmon.command("create-sampling-event")
@click.option("--site", "site_path", required=True, type=click.Path(exists=True),
              help="Path to site config YAML or JSON.")
@click.option("--event", "event_path", required=True, type=click.Path(exists=True),
              help="Path to event config YAML or JSON.")
@click.option("--analytes", "analytes_path", required=True,
              type=click.Path(exists=True),
              help="Path to analyte dictionary YAML or JSON.")
@click.option("--out-dir", "out_dir", required=True, type=click.Path(),
              help="Output directory for the sampling plan workbook.")
def create_sampling_event_cmd(site_path, event_path, analytes_path, out_dir):
    """Tool 2.7: generate pre-field sampling event plan (headless).

    Reads a well list + event metadata + analyte dict and writes a
    three-sheet planning workbook: expected samples, crew assignment,
    and COC draft.
    """
    import uuid
    from autogis.core.common.config import (
        SiteConfig, load_analyte_dictionary, ConfigError)
    from autogis.core.envmon.create_sampling_event import (
        build_sampling_event_plan, load_event_config)
    from autogis.core.envmon.sampling_event_writer import (
        write_sampling_event_workbook)

    try:
        site_cfg = SiteConfig.load(Path(site_path))
        event_cfg = load_event_config(Path(event_path))
        analyte_dict = load_analyte_dictionary(Path(analytes_path))
    except ConfigError as exc:
        raise click.ClickException(str(exc))

    try:
        plan = build_sampling_event_plan(
            site_cfg.data, event_cfg, analyte_dict,
            run_id=str(uuid.uuid4()),
        )
    except (ValueError, KeyError) as exc:
        raise click.ClickException(str(exc))

    out = Path(out_dir) / f"{plan.site_id}_{plan.event_name}_sampling_plan.xlsx"
    write_sampling_event_workbook(plan, out)
    click.echo(f"Sampling plan written: {out}")
    click.echo(f"  {len(plan.expected_samples)} expected sample rows "
               f"({sum(1 for r in plan.expected_samples if r.sample_type == 'Regular')} primary, "
               f"{sum(1 for r in plan.expected_samples if r.sample_type == 'Field Duplicate')} field dups)")
    click.echo(f"  {len(plan.crew_assignments)} wells assigned across "
               f"{len({r.assigned_to for r in plan.crew_assignments})} crew member(s)")


@envmon.command("build-fieldmaps")
@click.option("--site-config", "site_path", required=True,
              type=click.Path(exists=True), help="Site config YAML.")
@click.option("--event-config", "event_path", default=None,
              type=click.Path(exists=True),
              help="Optional event config YAML; its analyte_groups add one "
                   "Status_<group> field per group on SampleStatus.")
@click.option("--gdb", "gdb_path", default=None, type=click.Path(),
              help="Target file GDB to create/refresh the layers in "
                   "(ArcGIS Pro). Omit with --dry-run for a headless preview.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print the layer/field plan without touching a GDB "
                   "(headless).")
@qa_report_options
def build_fieldmaps_cmd(site_path, event_path, gdb_path, dry_run, report,
                        fail_on):
    """Tool 7.1: create/refresh the Field Maps monitoring layers for field
    crews (ArcGIS Pro).

    Derives the six canonical layers (monitoring wells, sample status,
    water levels, access notes, photo points, issue flags) with the
    editable field schema RouteSurvey123Submission (7.1b) expects, then
    provisions them in --gdb. Publish the GDB to Field Maps with
    `agol publish-layer` (6.1).
    """
    import yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.fieldmaps_plan import (
        plan_fieldmaps_project, provision_fieldmaps_layers)

    if not gdb_path and not dry_run:
        raise click.UsageError(
            "Provide --gdb (ArcGIS Pro) or --dry-run for a headless "
            "plan preview.")

    cfg = yaml.safe_load(open(site_path, encoding="utf-8")) or {}
    if event_path:
        cfg.update(yaml.safe_load(open(event_path, encoding="utf-8")) or {})
    plans = plan_fieldmaps_project(cfg)
    for p in plans:
        click.echo(f"{p.name} ({p.geometry}): "
                   + ", ".join(f.name for f in p.fields))
    if dry_run:
        click.echo("[dry-run: no GDB touched]")
        return

    _guard("build-fieldmaps")
    qa = QACollector()
    srs = str(cfg.get("coordinate_system") or "")
    n = provision_fieldmaps_layers(
        Path(gdb_path), plans, qa,
        spatial_reference=srs if srs and not srs.startswith("_TODO") else None)
    click.echo(f"Provisioned {n} layer(s) in {gdb_path}")
    _render_qa(qa, report, fail_on)


@autogis.group()
def agol():
    """AGOL / cloud tools."""


@agol.command("publish-layer")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--title", required=True, help="Hosted service title")
@click.option("--source", required=True, type=click.Path(exists=True),
              help="Zip of FGDB or shapefiles, or GeoJSON, to publish")
@click.option("--tags", default="autogis", help="Comma-separated AGOL tags")
@click.option("--folder", default=None, help="AGOL content folder (default: root)")
@click.option("--share-with", default="org",
              type=click.Choice(["private", "org", "everyone"]),
              help="Sharing level after publish")
@click.option("--no-overwrite", is_flag=True, default=False,
              help="Fail if a service with this title already exists")
def publish_layer(profile, title, source, tags, folder, share_with, no_overwrite):
    """Publish or overwrite a hosted AGOL feature service."""
    from autogis.core.agol.publish import PublishConfig, publish_or_overwrite_layer
    from autogis.core.common.qa import QACollector
    gis = agol_from_profile(profile)
    cfg = PublishConfig(
        title=title,
        tags=[t.strip() for t in tags.split(",")],
        folder=folder,
        share_with=share_with,
        overwrite=not no_overwrite,
    )
    qa = QACollector()
    result = publish_or_overwrite_layer(gis, cfg, source, qa)
    for rec in qa.records:
        click.echo(f"[{rec.severity}] {rec.message}")
    if result is None:
        raise SystemExit(1)


@agol.command("audit-schema")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True),
              help="Path to local layer schema spec (YAML/JSON).")
@click.option("--layer-url", default=None,
              help="Full AGOL FeatureLayer REST URL.")
@click.option("--item-id", default=None,
              help="AGOL item ID (use with --layer-index when item has multiple layers).")
@click.option("--layer-index", type=int, default=0, show_default=True,
              help="Layer index within the item (0-based).")
@click.option("--profile", default=None,
              help="ArcGIS API for Python profile name.")
@click.option("--output", default=None, type=click.Path(),
              help="Write report to this file path (stdout if omitted).")
@click.option("--format", "fmt",
              type=click.Choice(["text", "csv", "json"]), default="text",
              show_default=True, help="Output format.")
@click.option("--fail-on-drift", is_flag=True, default=False,
              help="Exit with status 1 if any drift is detected.")
def audit_schema_cmd(spec_path, layer_url, item_id, layer_index, profile,
                     output, fmt, fail_on_drift):
    """Tool 6.6: compare a hosted AGOL feature layer schema against a local spec (HYBRID)."""
    import csv as _csv
    import io
    import json as _json

    from autogis.core.agol.audit_schema import (
        DriftItem,
        diff_schema,
        fetch_layer_schema,
        format_drift_report,
    )
    from autogis.core.common.config import load_config

    if not layer_url and not item_id:
        raise click.UsageError("Provide --layer-url or --item-id.")

    local_spec = load_config(Path(spec_path))
    gis = agol_from_profile(profile)
    fetched_schema = fetch_layer_schema(
        gis, layer_url=layer_url, item_id=item_id, layer_index=layer_index)
    report = diff_schema(fetched_schema, local_spec)

    if fmt == "text":
        content = format_drift_report(report)
    elif fmt == "json":
        content = _json.dumps({
            "layer_name": report.layer_name,
            "total_agol_fields": report.total_agol_fields,
            "total_spec_fields": report.total_spec_fields,
            "has_drift": report.has_drift,
            "drift_items": [dataclasses.asdict(d) for d in report.drift_items],
        }, indent=2)
    else:  # csv
        buf = io.StringIO()
        cols = [f.name for f in dataclasses.fields(DriftItem)]
        w = _csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for d in report.drift_items:
            w.writerow(dataclasses.asdict(d))
        content = buf.getvalue()

    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Report written: {output}  "
                   f"({'DRIFT' if report.has_drift else 'CLEAN'})")
    else:
        click.echo(content)

    if fail_on_drift and report.has_drift:
        raise SystemExit(1)


@agol.command("audit-dependencies")
@click.option("--item-id", required=True, help="AGOL item ID to audit.")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--max-depth", type=int, default=2, show_default=True,
              help="Maximum dependency-walk depth.")
@click.option("--output", default=None, type=click.Path(),
              help="Write report to this file path (stdout if omitted).")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="csv",
              show_default=True, help="Output format.")
def audit_dependencies_cmd(item_id, profile, max_depth, output, fmt):
    """Tool 6.9: find items that reference/depend on an AGOL item (HYBRID)."""
    import csv as _csv
    import io
    import json as _json

    from autogis.core.agol.audit_dependencies import (
        DependencyRecord, audit_item_dependencies)
    from autogis.core.common.qa import QACollector

    gis = agol_from_profile(profile)
    qa = QACollector()
    records = audit_item_dependencies(gis, item_id, qa=qa, max_depth=max_depth)
    for rec in qa.records:
        click.echo(f"[{rec.severity}] {rec.message}")

    if fmt == "json":
        content = _json.dumps([dataclasses.asdict(r) for r in records], indent=2)
    else:
        buf = io.StringIO()
        cols = [f.name for f in dataclasses.fields(DependencyRecord)]
        w = _csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))
        content = buf.getvalue()

    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Wrote {len(records)} dependency record(s) to {output}")
    else:
        click.echo(content)


@agol.command("refresh-dashboard")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--mart-dir", required=True, type=click.Path(exists=True, file_okay=False),
              help="Directory of per-table mart dumps, one <TableName>.json "
                   "(list of row dicts) per Dash_* table.")
@click.option("--layer-map", "layer_map_path", required=True, type=click.Path(exists=True),
              help="YAML mapping Dash_* table name -> hosted layer/table item id.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Validate row schema against hosted layers/tables; write nothing.")
@click.option("--report", default=None, type=click.Path())
def refresh_dashboard_cmd(profile, mart_dir, layer_map_path, dry_run, report):
    """Tool 6.4: push local Dash_* data-mart tables to hosted AGOL layers (HYBRID).

    NOTE: --mart-dir expects one <TableName>.json (list of row dicts) per Dash_*
    table. Tool 6.7 (BuildDashboardDataMart) currently writes straight into a
    GDB via arcpy — a JSON-dump step between 6.7 and this command does not
    exist yet, so --mart-dir must be populated by hand or a future export tool.
    """
    import json
    from autogis.core.agol.dashboard_refresh import refresh_dashboard_data

    gis = agol_from_profile(profile)
    layer_map = yaml.safe_load(Path(layer_map_path).read_text(encoding="utf-8"))
    mart_tables = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in Path(mart_dir).glob("Dash_*.json")
    }
    result = refresh_dashboard_data(gis, mart_tables, layer_map, dry_run=dry_run)
    for rec in result.qa.records:
        click.echo(f"[{rec.severity}] {rec.message}")
    click.echo(f"tables_refreshed={result.tables_refreshed} "
               f"rows_pushed={result.rows_pushed} failures={result.failures}")
    if report:
        p = Path(report)
        if p.suffix == ".json":
            result.qa.write_json_summary(p)
        elif p.suffix == ".csv":
            result.qa.write_csv(p)
        else:
            result.qa.write_markdown(p)
        click.echo(f"Wrote report: {p}")
    # Exit code is driven solely by result.failures (not a generic
    # warning-level QA threshold) -- a benign WARNING should not fail this
    # command when nothing actually failed to push.
    if result.failures:
        raise SystemExit(1)


@agol.command("publish-dashboard")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--spec", required=True, type=click.Path(exists=True),
              help="Dashboard spec YAML (title, web-map item, cards, charts, selectors, ...)")
@click.option("--dry-run", is_flag=True, default=False,
              help="Compile and print the dashboard JSON without publishing")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension)")
def publish_dashboard_cmd(profile, spec, dry_run, report):
    """Tool 6.8: compile a YAML dashboard spec and create-or-update the AGOL Dashboard item."""
    import json
    from autogis.core.agol.dashboard_publish import publish_dashboard

    spec_dict = yaml.safe_load(Path(spec).read_text(encoding="utf-8"))
    # dry_run never touches gis (see publish_dashboard), so skip session setup entirely
    gis = None if dry_run else agol_from_profile(profile)
    result = publish_dashboard(gis, spec_dict, dry_run=dry_run)

    for rec in result.qa.records:
        click.echo(f"[{rec.severity}] {rec.message}")
    if dry_run:
        click.echo(json.dumps(result.dashboard_json, indent=2))
    if report:
        _render_qa(result.qa, report, "warning")
    if not dry_run and not result.item_id:
        raise SystemExit(1)


@agol.command("promote")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--stage-map", "stage_map_path", required=True, type=click.Path(exists=True),
              help="YAML mapping: layer -> {dev,qa,prod: item_id}")
@click.option("--layer", required=True, help="Logical layer name (key in the stage map)")
@click.option("--from", "from_stage", required=True,
              type=click.Choice(["dev", "qa", "prod"]), help="Source stage")
@click.option("--to", "to_stage", required=True,
              type=click.Choice(["dev", "qa", "prod"]), help="Target stage")
@click.option("--approve", is_flag=True, default=False,
              help="Explicitly approve a qa->prod promotion")
@click.option("--approved-by", default=None, help="Approver name (required for qa->prod)")
@click.option("--run-history", "run_history_path", default="run_history.csv",
              show_default=True, type=click.Path(), help="Run-history CSV path")
def promote_cmd(profile, stage_map_path, layer, from_stage, to_stage,
                approve, approved_by, run_history_path):
    """Tool 6.10: promote an AGOL layer's data between DEV/QA/PROD stages."""
    from autogis.core.agol.promote import promote_layer
    from autogis.core.common.run_history import RunHistory

    if approved_by and not approve:
        raise click.UsageError(
            "--approved-by requires --approve (both gate a qa->prod promotion; "
            "--approved-by alone is silently ignored otherwise).")

    gis = agol_from_profile(profile)
    stage_map = yaml.safe_load(Path(stage_map_path).read_text(encoding="utf-8"))
    result = promote_layer(
        gis, layer=layer, stage_map=stage_map,
        from_stage=from_stage, to_stage=to_stage,
        approved_by=(approved_by if approve else None),
        run_history=RunHistory(Path(run_history_path)),
    )
    for rec in result.qa.records:
        click.echo(f"[{rec.severity}] {rec.message}")
    if result.status != "promoted":
        raise SystemExit(1)


@agol.command("update-webmap")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--webmap-item", "webmap_item_id", required=True, help="Web map item ID")
@click.option("--figure-spec", "figure_spec_path", required=True,
              type=click.Path(exists=True), help="Figure spec YAML (canonical FigureSpec)")
@click.option("--event-date", default="", help="Value for {event_date} in definition-query templates")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show the JSON changes without writing the web map")
@click.option("--report", default=None, type=click.Path())
def update_webmap_cmd(profile, webmap_item_id, figure_spec_path, event_date, dry_run, report):
    """Tool 6.3: push a figure spec's display config into an AGOL web map."""
    from autogis.core.agol.webmap import update_webmap_from_spec
    from autogis.core.common.config import FigureSpec
    spec = FigureSpec.load(Path(figure_spec_path))
    gis = agol_from_profile(profile)
    result = update_webmap_from_spec(gis, webmap_item_id=webmap_item_id,
                                     figure_spec=spec.data, event_date=event_date,
                                     dry_run=dry_run)
    _render_qa(result.qa, report, "error")


@agol.command("create-views")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--view-spec", "view_spec_path", required=True, type=click.Path(exists=True),
              help="YAML: views: [{name, source_layer, allow_fields|deny_fields, "
                   "definition_query, sensitive_fields}]")
@click.option("--report", default=None, type=click.Path())
def create_views_cmd(profile, view_spec_path, report):
    """Tool 6.11: create/update audience-specific hosted views (sensitive-field leak is blocking)."""
    from autogis.core.agol.hosted_views import create_stakeholder_view, load_view_specs
    from autogis.core.common.qa import QACollector
    data = yaml.safe_load(Path(view_spec_path).read_text(encoding="utf-8"))
    try:
        specs = load_view_specs(data)
    except ValueError as exc:
        raise click.UsageError(str(exc))
    gis = agol_from_profile(profile)
    combined = QACollector()
    for spec in specs:
        combined.extend(create_stakeholder_view(gis, spec).qa.records)
    _render_qa(combined, report, "error")


@agol.command("sync-to-gdb")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--layer-url", default=None,
              help="Full AGOL FeatureLayer REST URL.")
@click.option("--item-id", default=None,
              help="AGOL item ID (use with --layer-index when item has multiple layers).")
@click.option("--layer-index", type=int, default=0, show_default=True,
              help="Layer index within the item (0-based).")
@click.option("--where", default=None,
              help="SQL where clause filtering the hosted layer.")
@click.option("--since", default=None,
              help="ISO date YYYY-MM-DD — only records with EditDate after this "
                   "(hosted layer needs editor tracking).")
@click.option("--key-field", default="GlobalID", show_default=True,
              help="Field matching hosted records to local rows.")
@click.option("--fields", default=None,
              help="Comma-separated fields to sync (default: all non-system fields).")
@click.option("--out-csv", default=None, type=click.Path(),
              help="Headless: write fetched edit records to CSV. "
                   "Mutually exclusive with --gdb.")
@click.option("--gdb", default=None, type=click.Path(),
              help="File geodatabase: upsert records into --table (ArcGIS Pro). "
                   "Mutually exclusive with --out-csv.")
@click.option("--table", default=None,
              help="Target table/feature class name in the GDB (required with --gdb).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show the upsert plan without writing to the GDB (use with --gdb).")
@qa_report_options
def sync_to_gdb_cmd(profile, layer_url, item_id, layer_index, where, since,
                    key_field, fields, out_csv, gdb, table, dry_run,
                    report, fail_on):
    """Tool 6.2: download hosted feature layer edits into the local FGDB (HYBRID).

    Headless path (--out-csv): fetch attribute records via the arcgis REST API
    and dump them to CSV — no arcpy. LOCAL path (--gdb --table): guard for
    arcpy, read existing keys from the target table, and (unless --dry-run)
    upsert the fetched records. Attribute sync only — photo attachments are
    `autogis harvest` + `envmon index-field-attachments` (Tool 6.5).
    """
    import csv as _csv
    from datetime import date as _date

    from autogis.core.agol import sync_layer
    from autogis.core.common.qa import QACollector

    if gdb and out_csv:
        raise click.UsageError("--gdb and --out-csv are mutually exclusive.")
    if not gdb and not out_csv:
        raise click.UsageError(
            "Provide --out-csv (headless dump) or --gdb (ArcGIS Pro upsert).")
    if gdb and not table:
        raise click.UsageError("--gdb requires --table.")
    if not layer_url and not item_id:
        raise click.UsageError("Provide --layer-url or --item-id.")
    if gdb:
        _guard("sync-to-gdb")

    since_d = _date.fromisoformat(since) if since else None
    eff_where = sync_layer.edits_where_clause(where, since_d)

    gis = agol_from_profile(profile)
    records = sync_layer.fetch_layer_edits(
        gis, layer_url=layer_url, item_id=item_id, layer_index=layer_index,
        where=eff_where)
    click.echo(f"Fetched {len(records)} record(s)  where: {eff_where}")

    qa = QACollector()
    field_list = ([f.strip() for f in fields.split(",") if f.strip()]
                  if fields else None)

    if out_csv:
        # Headless deliverable: the keyed, field-filtered edit records.
        # Planning against local rows needs the GDB, so upsert is --gdb-only.
        plan = sync_layer.plan_sync(records, set(), key_field=key_field,
                                    fields=field_list, qa=qa)
        rows = list(plan.updates.values()) + plan.inserts
        with open(out_csv, "w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=plan.field_names,
                                extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        click.echo(f"Wrote {len(rows)} record(s) to {out_csv}")
    else:
        from autogis.runtime.sessions import arcpy_env as _arcpy
        _ax = _arcpy()
        target = str(Path(gdb) / table)
        if not _ax.Exists(target):
            raise click.ClickException(f"Target table not found: {target}")
        existing = set()
        with _ax.da.SearchCursor(target, [key_field]) as cur:
            for row in cur:
                if row[0] is not None:
                    existing.add(str(row[0]))
        plan = sync_layer.plan_sync(records, existing, key_field=key_field,
                                    fields=field_list, qa=qa)
        click.echo(f"Plan: {len(plan.updates)} update(s), {len(plan.inserts)} "
                   f"insert(s), {plan.skipped_no_key} skipped (no {key_field}).")
        if not dry_run:
            updated, inserted = sync_layer.write_sync_to_gdb(gdb, table, plan)
            click.echo(f"Wrote {updated} update(s) + {inserted} insert(s) "
                       f"to {target}.")

    _render_qa(qa, report, fail_on)


@envmon.command("validate-rtk-survey")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True)
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True)
@click.option("--format", "coord_format", type=click.Choice(["auto", "pnezd", "penzd"]),
              default="auto", show_default=True,
              help="Coordinate column order for headerless input.")
@click.option("--extra-columns", default=None,
              help="Comma-separated field names for columns 6+ of a headerless file, "
                   "overriding the built-in 11-column layout. Vocabulary: hrms_ft, "
                   "vrms_ft, pdop, satellites, fix_type, collected_at, operator, "
                   "feature_code.")
@click.option("--report", default=None, type=click.Path())
# Deliberately NOT @qa_report_options: this command's --fail-on defaults to
# "warning" (not the shared contract's "error") because RTK precision
# warnings are routinely expected and shouldn't fail a pipeline by default.
# Exempted by name in tests/test_capabilities.py's QA-contract consistency
# test -- don't "fix" this default without updating that test too.
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="warning")
def validate_rtk_survey_cmd(csv_path, hrms_threshold, vrms_threshold, coord_format,
                           extra_columns, report, fail_on):
    """Validate an RTK survey CSV for precision and fix-type QA (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv
    from autogis.core.envmon.validate_rtk_survey import validate_rtk_points
    extra = [c.strip() for c in extra_columns.split(",")] if extra_columns else None
    qa = QACollector()
    try:
        points = parse_rtk_csv(Path(csv_path), coord_format=coord_format,
                               extra_columns=extra, qa=qa)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    validate_rtk_points(points, hrms_threshold, vrms_threshold, qa=qa)
    _render_qa(qa, report, fail_on)


@envmon.command("export-survey-cad")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--feature-code-map", "map_path", required=True, type=click.Path(exists=True),
              help="YAML feature-code -> layer-name mapping "
                   "(e.g. {MW: MonitoringWells, GCP: DroneControlPoints}).")
@click.option("--output-dir", required=True, type=click.Path(),
              help="Directory to write one CSV (+ manifest.json) per layer.")
@click.option("--geojson/--no-geojson", default=False,
              help="Also write a GeoJSON FeatureCollection per layer.")
@click.option("--landxml/--no-landxml", default=False,
              help="Also write a LandXML <CgPoints> file per layer (points only; "
                   "no surface/alignment data).")
@qa_report_options
def export_survey_cad_cmd(csv_path, map_path, output_dir, geojson, landxml, report, fail_on):
    """Export RTK survey points to feature-code-mapped CSV/GeoJSON/LandXML layers (headless).

    DWG/DXF CAD export is still out of scope for this tool.
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv
    from autogis.core.envmon.export_survey_cad import (
        export_survey_to_cad_gis,
        load_feature_code_map,
    )

    points = parse_rtk_csv(Path(csv_path))
    feature_code_map = load_feature_code_map(Path(map_path))
    qa = QACollector()
    manifest = export_survey_to_cad_gis(
        points, feature_code_map, Path(output_dir),
        write_geojson=geojson, write_landxml=landxml, qa=qa,
    )

    for entry in manifest:
        click.echo(f"  {entry.layer_name}: {entry.point_count} point(s) -> {entry.output_path}")

    _render_qa(qa, report, fail_on)


@envmon.command("import-rtk-survey")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--gdb", required=True, type=click.Path())
@click.option("--batch-id", default=None)
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True)
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True)
@click.option("--format", "coord_format", type=click.Choice(["auto", "pnezd", "penzd"]),
              default="auto", show_default=True,
              help="Coordinate column order for headerless input.")
@click.option("--extra-columns", default=None,
              help="Comma-separated field names for columns 6+ of a headerless file, "
                   "overriding the built-in 11-column layout. Vocabulary: hrms_ft, "
                   "vrms_ft, pdop, satellites, fix_type, collected_at, operator, "
                   "feature_code.")
def import_rtk_survey_cmd(csv_path, site_id, gdb, batch_id, hrms_threshold, vrms_threshold,
                         coord_format, extra_columns):
    """Import RTK survey CSV into SurveyPoints_Raw/QA (ArcGIS Pro)."""
    import uuid
    _guard("import-rtk-survey")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv, import_rtk_survey, assign_qa_flags
    bid = batch_id or f"RTK-{uuid.uuid4().hex[:8].upper()}"
    extra = [c.strip() for c in extra_columns.split(",")] if extra_columns else None
    qa = QACollector()
    try:
        points = parse_rtk_csv(Path(csv_path), coord_format=coord_format,
                               extra_columns=extra, qa=qa)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    for rec in qa.records:
        click.echo(f"[{rec.severity}] {rec.category}: {rec.message}")
    try:
        import_rtk_survey(gdb, site_id, bid, points, hrms_threshold, vrms_threshold)
    except RuntimeError as exc:
        raise click.ClickException(str(exc))
    passes = sum(1 for p in points if not assign_qa_flags(p, hrms_threshold, vrms_threshold))
    click.echo(f"Imported {len(points)} points: {passes} QA pass, {len(points)-passes} QA fail.")


@envmon.command("register-source-doc")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True),
              help="Path to the source file to register.")
@click.option("--site", "site_id", required=True, help="Site ID (e.g. H281).")
@click.option("--event", "event_id", required=True, help="Event ID (e.g. 2026-Q2).")
@click.option("--tool", "tool_name", required=True, help="Tool that ingested the file.")
@click.option("--registry", "registry_path", default="source_docs.csv",
              show_default=True, type=click.Path(),
              help="Path to the source-document registry CSV.")
@click.option("--notes", default="", help="Optional free-text notes.")
@click.option("--skip-if-registered", is_flag=True, default=False,
              help="Exit cleanly without writing if the file hash is already registered.")
def register_source_doc_cmd(file_path, site_id, event_id, tool_name,
                            registry_path, notes, skip_if_registered):
    """Tool 2.5: register a source document in the append-only registry (headless)."""
    from datetime import datetime, timezone
    from autogis.core.envmon.source_registry import (
        SourceDocRecord, SourceRegistry, compute_sha256,
    )

    p = Path(file_path)
    sha = compute_sha256(p)
    reg = SourceRegistry(Path(registry_path))

    if skip_if_registered and reg.is_registered(str(p), sha):
        click.echo("Already registered, skipped.")
        return

    reg.register(SourceDocRecord(
        registered_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        file_path=str(p),
        sha256=sha,
        file_size_bytes=p.stat().st_size,
        site_id=site_id,
        event_id=event_id,
        tool=tool_name,
        notes=notes,
    ))
    click.echo(f"Registered: {sha[:8]} {p.name}")


@envmon.command("register-drone-flight")
@click.argument("flight_yaml", metavar="FLIGHT_YAML", type=click.Path(exists=True))
@click.option("--gdb", required=True, type=click.Path(),
              help="File geodatabase path (ArcGIS Pro required for the write).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Validate the flight YAML only; do not write to the GDB.")
@qa_report_options
def register_drone_flight_cmd(flight_yaml, gdb, dry_run, report, fail_on):
    """Tool 8.6: register a drone flight from an inventory YAML (ArcGIS Pro)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.register_drone_flight import (
        load_flight_yaml, validate_flight_record, write_drone_flight)
    rec = load_flight_yaml(Path(flight_yaml))
    qa = QACollector()
    validate_flight_record(rec, qa)
    if not dry_run and qa.counts_by_severity().get("ERROR", 0) == 0:
        _guard("register-drone-flight")
        if write_drone_flight(gdb, rec):
            click.echo(f"Flight {rec.flight_id} registered in {gdb}.")
        else:
            click.echo(f"DroneFlights table not found in {gdb}; nothing written.")
    _render_qa(qa, report, fail_on)


@envmon.command("validate-drone-products")
@click.option("--manifest", "manifest_path", required=True, type=click.Path(exists=True),
              help="Product manifest CSV (product_type, path, crs, vertical_datum, resolution_m).")
@click.option("--flight-id", required=True, help="Drone flight ID to stamp on records.")
@click.option("--check-paths", is_flag=True, default=False,
              help="Verify that each product path exists on disk.")
@qa_report_options
def validate_drone_products_cmd(manifest_path, flight_id, check_paths, report, fail_on):
    """Tool 8.8: validate a drone product manifest CSV (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_drone_products import (
        parse_product_manifest, validate_drone_products)
    records = parse_product_manifest(Path(manifest_path), flight_id)
    qa = QACollector()
    validate_drone_products(records, qa, check_paths=check_paths)
    _render_qa(qa, report, fail_on)


@envmon.command("import-drone-products")
@click.option("--manifest", "manifest_path", required=True, type=click.Path(exists=True),
              help="Product manifest CSV (product_type, path, crs, vertical_datum, resolution_m).")
@click.option("--flight-id", required=True,
              help="Drone flight ID. A matching DroneFlights row must already exist in the GDB.")
@click.option("--site-id", required=True,
              help="Site identifier stamped into run-history audit records "
                   "(ADR-0076); not read by the import itself.")
@click.option("--gdb", "gdb_path", required=True, type=click.Path(),
              help="File geodatabase path (ArcGIS Pro required).")
@click.option("--catalog-name", default="DroneMosaicDataset", show_default=True,
              help="Name of the existing mosaic dataset inside the GDB.")
@click.option("--gcp-csv", "gcp_csv_path", default=None, type=click.Path(exists=True),
              help="Optional GCP CSV (point_id, northing, easting, elevation, point_type).")
@qa_report_options
def import_drone_products_cmd(manifest_path, flight_id, site_id, gdb_path,
                              catalog_name, gcp_csv_path, report, fail_on):
    """Tool 8.8: import drone deliverables to raster catalog + GCP table (ArcGIS Pro)."""
    _guard("import-drone-products")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_drone_products import (
        parse_product_manifest, validate_drone_products, classify_records,
        parse_gcp_csv, write_product_registry, add_rasters_to_catalog,
        write_gcp_features)
    records = parse_product_manifest(Path(manifest_path), flight_id)
    qa = QACollector()
    validate_drone_products(records, qa)
    if qa.has_blocking(allow_warnings=True, allow_errors=False):
        _render_qa(qa, report, fail_on)
        return
    rasters, others = classify_records(records)
    n_reg = write_product_registry(gdb_path, records)
    if n_reg:
        click.echo(f"Registered {n_reg} product(s) in DroneProductRegistry.")
    else:
        click.echo("DroneProductRegistry table not found; no products registered.")
    added = add_rasters_to_catalog(gdb_path, catalog_name, rasters)
    click.echo(f"Added {added} raster(s) to mosaic dataset '{catalog_name}'.")
    if others:
        click.echo(f"Path-registered {len(others)} non-raster product(s) "
                   f"(point cloud — no mosaic load in v1).")
    if gcp_csv_path:
        gcp_points = parse_gcp_csv(Path(gcp_csv_path), flight_id)
        n_gcp = write_gcp_features(gdb_path, gcp_points)
        click.echo(f"Wrote {n_gcp} GCP feature(s) to DroneControlPoints.")
    _render_qa(qa, report, fail_on)


@envmon.command("condition-dem")
@click.option("--gdb", "gdb_path", required=True, type=click.Path(),
              help="File geodatabase path (ArcGIS Pro required).")
@click.option("--flight-id", required=True,
              help="Drone flight ID; its DroneFlights.DEMPath is conditioned.")
@click.option("--out-dir", required=True, type=click.Path(),
              help="Directory for the conditioned DEM and derived rasters.")
@click.option("--fill-voids", is_flag=False, flag_value=9, default=None,
              type=int, metavar="[MAX_PIXELS]",
              help="Void-fill nodata pixels. Bare flag = 9px kernel.")
@click.option("--smooth", is_flag=False, flag_value="median", default=None,
              type=click.Choice(["median"]),
              help="Smooth the DEM. Bare flag = median.")
@click.option("--with-slope", is_flag=True, default=False,
              help="Also derive a slope raster.")
@click.option("--with-contours", is_flag=True, default=False,
              help="Also derive a contour feature class.")
def condition_dem_cmd(gdb_path, flight_id, out_dir, fill_voids, smooth,
                      with_slope, with_contours):
    """DEMConditioningPipeline: void-fill/smooth a flight's DEM and derive
    hillshade/slope/contours (ArcGIS Pro)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.dem_conditioning import build_config, validate_config
    config = build_config(fill_voids=fill_voids, smooth=smooth,
                          with_slope=with_slope, with_contours=with_contours)
    qa = QACollector()
    validate_config(config, qa)
    if qa.records:
        raise click.ClickException("; ".join(r.message for r in qa.records))
    _guard("condition-dem")
    raise click.ClickException(
        "condition-dem runs inside ArcGIS Pro only. Use the ConditionDEM "
        "tool in the .pyt toolbox."
    )


@envmon.command("compare-drone-surfaces")
@click.option("--gdb", "gdb_path", required=True, type=click.Path(),
              help="File geodatabase path (ArcGIS Pro required).")
@click.option("--primary-product-id", required=True,
              help="DroneProductRegistry product ID of the DEM to evaluate.")
@click.option("--baseline-product-id", default=None,
              help="Baseline: another DroneProductRegistry product ID "
                   "(prior-flight DEM, raw or conditioned).")
@click.option("--baseline-landxml", default=None, type=click.Path(exists=True),
              help="Baseline: a LandXML design-surface file.")
@click.option("--lod-threshold-ft", type=float, default=0.2, show_default=True,
              help="Elevation diff magnitude above which a cell counts as change.")
def compare_drone_surfaces_cmd(gdb_path, primary_product_id,
                               baseline_product_id, baseline_landxml,
                               lod_threshold_ft):
    """CompareDroneSurfaces: raster-diff a drone DEM against a prior flight
    or a LandXML design surface (ArcGIS Pro)."""
    from autogis.core.envmon.compare_drone_surfaces import validate_baseline_args
    try:
        validate_baseline_args(baseline_product_id, baseline_landxml)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    _guard("compare-drone-surfaces")
    from autogis.core.envmon import compare_drone_surfaces  # noqa: F401  (arcpy path)
    raise click.ClickException(
        "compare-drone-surfaces runs inside ArcGIS Pro only. Use the "
        "CompareDroneSurfaces tool in the .pyt toolbox."
    )


@envmon.command("validate-boring-logs")
@click.argument("input_dir", metavar="INPUT_DIR",
                type=click.Path(exists=True, file_okay=False))
@qa_report_options
def validate_boring_logs_cmd(input_dir, report, fail_on):
    """Tool 8.0b: validate a boring-log CSV package (headless).

    INPUT_DIR holds boring_locations.csv, lithology.csv and samples.csv.
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_boring_logs import (
        load_boring_package, validate_boring_package)
    qa = QACollector()
    locs, ivals, samps = load_boring_package(Path(input_dir), qa)
    validate_boring_package(locs, ivals, samps, qa)
    _render_qa(qa, report, fail_on)


@envmon.command("create-boring-log-db")
@click.argument("db_path", metavar="DB", type=click.Path())
@click.option("--overwrite", is_flag=True,
              help="Replace the database if it already exists.")
@click.option("--validate", "validate_only", is_flag=True,
              help="Validate an existing database against the expected "
                   "schema instead of creating one.")
@qa_report_options
def create_boring_log_db_cmd(db_path, overwrite, validate_only, report, fail_on):
    """Tool 8.0a: create (or --validate) the normalized boring-log SQLite
    database (headless).

    One table per schema/boring.py dataclass — columns are derived from the
    dataclass fields.
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.create_boring_log_database import (
        create_boring_log_database, validate_boring_log_database)
    qa = QACollector()
    if validate_only:
        validate_boring_log_database(Path(db_path), qa)
    else:
        try:
            create_boring_log_database(Path(db_path), overwrite=overwrite, qa=qa)
            click.echo(f"Created boring-log database: {db_path}")
        except FileExistsError:
            pass  # QA already carries the error; _render_qa exits 1.
    _render_qa(qa, report, fail_on)


@envmon.command("gen-boring-logs")
@click.option("--db", "db_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Boring-log SQLite database (from create-boring-log-db).")
@click.option("--out-dir", "out_dir", required=True,
              type=click.Path(file_okay=False),
              help="Directory for the per-boring .md files, appendix, "
                   "photo log and sample-summary CSV.")
@click.option("--borings", default="",
              help="Comma-separated boring IDs (default: all).")
@qa_report_options
def gen_boring_logs_cmd(db_path, out_dir, borings, report, fail_on):
    """Tool 8.0c: assemble boring-log Markdown documents from the boring
    database (headless).

    Writes one .md per boring plus a combined appendix, photo log and
    sample-summary CSV. PDF conversion is an explicit downstream step.
    """
    from autogis.core.common.qa import QACollector, SEV_ERROR
    from autogis.core.envmon.boring_log_report import (
        build_boring_log, read_boring_records, write_outputs)
    from autogis.core.envmon.create_boring_log_database import (
        validate_boring_log_database)
    qa = QACollector()
    validate_boring_log_database(Path(db_path), qa)
    if qa.has_blocking():
        _render_qa(qa, report, fail_on)
        return
    ids = [b.strip() for b in borings.split(",") if b.strip()] or None
    bundles = read_boring_records(Path(db_path), boring_ids=ids, qa=qa)
    if not bundles:
        qa.add(SEV_ERROR, "no_borings",
               f"No matching borings found in {db_path}.")
        _render_qa(qa, report, fail_on)
        return
    docs = [build_boring_log(bid, qa=qa, **bundle)
            for bid, bundle in bundles.items()]
    paths = write_outputs(docs, Path(out_dir))
    click.echo(f"Wrote {len(paths)} file(s) for {len(docs)} boring(s) "
               f"-> {out_dir}")
    _render_qa(qa, report, fail_on)


@envmon.command("generate-subsurface-profile")
@click.argument("db_path", metavar="DB_PATH",
                 type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output image path (.png/.svg).")
@click.option("--boring-a", default=None, help="Profile start, by boring ID.")
@click.option("--boring-b", default=None, help="Profile end, by boring ID.")
@click.option("--start", nargs=2, type=float, default=None,
              metavar="NORTHING EASTING", help="Profile start, by coordinate.")
@click.option("--end", nargs=2, type=float, default=None,
              metavar="NORTHING EASTING", help="Profile end, by coordinate.")
@click.option("--projection-tolerance-ft", type=float, default=50.0,
              show_default=True,
              help="Max perpendicular offset for a boring to be included.")
@click.option("--title", default="", help="Optional plot title.")
@qa_report_options
def generate_subsurface_profile_cmd(db_path, out_path, boring_a, boring_b,
                                    start, end, projection_tolerance_ft,
                                    title, report, fail_on):
    """Generate a subsurface profile figure from the boring-log database
    (headless).

    The profile line is exactly two endpoints — either --boring-a/--boring-b
    or --start/--end. Borings within --projection-tolerance-ft of the line
    are projected onto it and rendered as lithology columns; borings beyond
    tolerance are excluded with a QA warning naming them.

    Rendering requires matplotlib: pip install "autogis[profile]".
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.subsurface_profile import build_profile, render_profile
    qa = QACollector()
    try:
        placements = build_profile(
            Path(db_path), boring_a=boring_a, boring_b=boring_b,
            start=start or None, end=end or None,
            tolerance_ft=projection_tolerance_ft, qa=qa)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    try:
        render_profile(placements, Path(out_path), title=title, qa=qa)
    except ImportError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Wrote {out_path}: {len(placements)} boring(s) on the profile.")
    _render_qa(qa, report, fail_on)


@envmon.command("generate-inspection-report")
@click.option("--inspections", "inspections_csv", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Inspection metadata CSV (WellID, InspectionDate, "
                   "Inspector, Condition, Notes; optional GPS_Lat, GPS_Lon, "
                   "DepthToWaterFt).")
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Harvester manifest.csv/.json written by "
                   "'autogis harvest'.")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Root directory of the harvested attachment tree "
                   "(photos grouped {harvest_dir}/{well_id}/...).")
@click.option("--site", "site_id", required=True, help="Site ID.")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output .xlsx path.")
@click.option("--photo-width", type=int, default=300, show_default=True,
              help="Embedded photo box width (px).")
@click.option("--photo-height", type=int, default=225, show_default=True,
              help="Embedded photo box height (px).")
@qa_report_options
def generate_inspection_report_cmd(inspections_csv, manifest_path,
                                   harvest_dir, site_id, out_path,
                                   photo_width, photo_height, report,
                                   fail_on):
    """Tool 7.4: per-well inspection photo workbook from harvested
    attachments + an inspection CSV (headless).

    Embedding photos requires Pillow: pip install "autogis[report]".
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.index_field_attachments import load_manifest
    from autogis.core.envmon.well_inspection_photo_report import (
        load_inspection_records, match_photos_to_wells, write_photo_report)
    qa = QACollector()
    records = load_inspection_records(Path(inspections_csv), qa=qa)
    photo_map = match_photos_to_wells(
        load_manifest(Path(manifest_path)), Path(harvest_dir), qa=qa)
    try:
        result = write_photo_report(
            records, photo_map, Path(out_path), site_id=site_id,
            photo_width_px=photo_width, photo_height_px=photo_height, qa=qa)
    except ImportError as exc:  # missing Pillow -> clean error, no traceback
        raise click.ClickException(str(exc))
    click.echo(f"Wrote {result.workbook_path}: {result.well_count} well(s), "
               f"{result.photos_embedded} photo(s) embedded, "
               f"{result.photos_missing} missing")
    _render_qa(qa, report, fail_on)


@envmon.command("index-field-attachments")
@click.argument("manifest", metavar="MANIFEST",
                type=click.Path(exists=True, dir_okay=False))
@click.option("--db", "db_path", required=True, type=click.Path(),
              help="SQLite database to write the AttachmentIndex table into.")
@click.option("--related-table", default="",
              help="Fallback source table name for manifest rows without one.")
@click.option("--replace", is_flag=True,
              help="Clear existing AttachmentIndex rows before inserting.")
@qa_report_options
def index_field_attachments_cmd(manifest, db_path, related_table, replace,
                                report, fail_on):
    """Tool 6.5: index a harvester manifest into AttachmentIndex (headless).

    MANIFEST is the CSV or JSON manifest written by the attachment harvester;
    this is the envmon-side half of SyncFieldAttachments (no AGOL call).
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.index_field_attachments import (
        build_attachment_index, load_manifest, validate_attachment_index,
        write_attachment_index)
    qa = QACollector()
    records = build_attachment_index(load_manifest(Path(manifest)),
                                     related_table=related_table, qa=qa)
    validate_attachment_index(records, qa)
    if not qa.has_blocking(allow_warnings=True, allow_errors=False):
        n = write_attachment_index(Path(db_path), records, replace=replace)
        click.echo(f"Indexed {n} attachment(s) -> {db_path}")
    _render_qa(qa, report, fail_on)


@envmon.command("import-boring-logs")
@click.argument("input_dir", metavar="INPUT_DIR",
                type=click.Path(exists=True, file_okay=False))
@click.option("--gdb", required=True, type=click.Path(),
              help="File geodatabase path (ArcGIS Pro required).")
@qa_report_options
def import_boring_logs_cmd(input_dir, gdb, report, fail_on):
    """Tool 8.0b: import a boring-log CSV package into the GDB (ArcGIS Pro)."""
    _guard("import-boring-logs")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_boring_logs import (
        load_boring_package, validate_boring_package, import_boring_package)
    qa = QACollector()
    locs, ivals, samps = load_boring_package(Path(input_dir), qa)
    validate_boring_package(locs, ivals, samps, qa)
    if not qa.has_blocking(allow_warnings=True, allow_errors=False):
        import_boring_package(gdb, locs, ivals, samps)
        click.echo(f"Imported {len(locs)} borings, {len(ivals)} intervals, "
                   f"{len(samps)} samples.")
    _render_qa(qa, report, fail_on)


def _require_ocr_extra() -> None:
    """Surface the missing `ocr` extra as a clean click error, not a
    mid-pipeline traceback. Checked via find_spec (no heavy import) so this
    guard doesn't itself require torch/transformers to be importable."""
    import importlib.util
    missing = [mod for mod in ("torch", "transformers", "PIL", "fitz")
               if importlib.util.find_spec(mod) is None]
    if missing:
        raise click.ClickException(
            f"Missing OCR dependencies: {', '.join(missing)}. "
            f"Install with: pip install autogis[ocr]")


@envmon.command("draft-lithology-from-scan")
@click.argument("scan_path", metavar="SCAN_PATH",
                type=click.Path(exists=True, dir_okay=False))
@click.option("--out-dir", "out_dir", required=True, type=click.Path(file_okay=False),
              help="Directory to write the draft lithology.csv into.")
@click.option("--handwritten", is_flag=True, default=False,
              help="Use the handwritten TrOCR model instead of the printed one.")
@qa_report_options
def draft_lithology_from_scan_cmd(scan_path, out_dir, handwritten, report, fail_on):
    """DRAFT: OCR a scanned/PDF boring log into a draft lithology.csv (headless).

    DRAFT TOOL: no real scanned sample has validated this pipeline. Output is
    an unreviewed draft, never authoritative — review every row against the
    original scan, then run 'autogis envmon validate-boring-logs OUT_DIR'
    before anything downstream uses it. Requires the ocr extra
    (pip install autogis[ocr]).
    """
    _require_ocr_extra()
    from autogis.core.envmon.draft_lithology_from_scan import (
        draft_lithology, write_draft_csv)
    result = draft_lithology(Path(scan_path), handwritten=handwritten)
    out_path = write_draft_csv(result.rows, Path(out_dir) / "lithology.csv")
    click.echo(f"DRAFT: wrote {out_path} ({len(result.rows)} row(s)). "
               f"Review against the scan before running validate-boring-logs.")
    _render_qa(result.qa, report, fail_on)


@envmon.command("download-dem")
@click.option("--dataset", default="USGS10m", show_default=True,
              help="DEM dataset code (case-insensitive); see --list-datasets.")
@click.option("--bbox", nargs=4, type=float, default=None,
              metavar="W S E N",
              help="WGS84 bounding box (mutually exclusive with --aoi).")
@click.option("--aoi", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="AOI shapefile (.shp) or GeoJSON; non-WGS84 shapefiles "
                   "need the opentopo extra (pip install autogis[opentopo]).")
@click.option("--out", "out_path", default=None, type=click.Path(),
              help="Output raster path; auto-derived from dataset+bbox if omitted.")
@click.option("--overwrite", is_flag=True, default=False,
              help="Allow overwriting an existing --out (refused otherwise).")
@click.option("--format", "output_format", default="GTiff", show_default=True,
              type=click.Choice(["GTiff", "AAIGrid", "HFA"]),
              help="OpenTopography output format.")
@click.option("--api-key", default=None,
              help="Overrides $OPENTOPOGRAPHY_API_KEY for this run.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Resolve AOI/routing, print a redacted URL + area estimate, "
                   "and exit without downloading.")
@click.option("--list-datasets", "list_datasets_flag", is_flag=True,
              default=False, help="Print the dataset registry and exit.")
@qa_report_options
def download_dem_cmd(dataset, bbox, aoi, out_path, overwrite, output_format,
                     api_key, dry_run, list_datasets_flag, report, fail_on):
    """Download an OpenTopography DEM GeoTIFF for an AOI (headless).

    Auto-routes the dataset code to /API/globaldem or /API/usgsdem, resolves
    the AOI to a WGS84 bbox, streams the raster to disk, and writes a
    provenance/citation .json sidecar. Requires an OpenTopography API key
    ($OPENTOPOGRAPHY_API_KEY or --api-key) except for --dry-run and
    --list-datasets.
    """
    from autogis.core.envmon import opentopo

    if list_datasets_flag:
        for ds in opentopo.list_datasets():
            click.echo(f"{ds.code:<16} {ds.endpoint:<9} "
                       f"{ds.resolution:<32} {ds.coverage}")
        return
    if bbox and aoi:
        raise click.UsageError("--bbox and --aoi are mutually exclusive.")
    if not bbox and not aoi:
        raise click.UsageError(
            "an AOI is required: pass --bbox W S E N or --aoi PATH "
            "(or use --list-datasets).")

    try:
        if dry_run:
            ds = opentopo.get_dataset(dataset)
            box = opentopo.resolve_bbox(bbox=bbox or None, aoi_path=aoi)
            click.echo(f"dataset : {ds.code} -> /API/{ds.endpoint} "
                       f"({ds.param}) [{ds.resolution}, {ds.coverage}]")
            click.echo(f"bbox    : W={box[0]} S={box[1]} E={box[2]} N={box[3]} "
                       f"(WGS84)")
            click.echo(f"area    : ~{opentopo.estimate_area_km2(box):,.1f} km2 "
                       f"(~{opentopo.estimate_pixels(ds, box):,} px "
                       f"at {ds.res_m:g} m)")
            click.echo(f"url     : "
                       f"{opentopo.build_url(ds, box, 'REDACTED', output_format)}")
            click.echo("dry run: nothing downloaded.")
            return

        last_step = [0]

        def on_progress(done, total):
            step = done // (10 * 2 ** 20)      # one line per 10 MiB
            if step != last_step[0]:
                last_step[0] = step
                suffix = (f" / {total / 2 ** 20:,.0f} MiB" if total
                          else " MiB")
                click.echo(f"  downloaded {done / 2 ** 20:,.0f}{suffix}")

        result = opentopo.download_dem(
            dataset, bbox=bbox or None, aoi_path=aoi, out_path=out_path,
            api_key=api_key, output_format=output_format,
            overwrite=overwrite, on_progress=on_progress)
    except (ValueError, RuntimeError, OSError) as err:  # OSError covers FileExistsError
        raise click.ClickException(str(err))

    if result.bytes_written:
        click.echo(f"Wrote {result.out_path} ({result.bytes_written:,} bytes) "
                   f"+ provenance sidecar {result.out_path.name}.json")
    _render_qa(result.qa, report, fail_on)


@envmon.command("survey-to-well-elevation")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True,
              help="Site ID matching SiteID in MonitoringWells.")
@click.option("--batch-id", default=None,
              help="Override auto-generated batch ID (default: RTK-<hex>).")
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True,
              help="Max horizontal RMS error (ft) for QA pass.")
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True,
              help="Max vertical RMS error (ft) for QA pass.")
@click.option("--elevation-type", default="TOC", show_default=True,
              help="ElevationType tag for ElevationHistory (e.g. TOC, GS).")
@click.option("--survey-date", default=None, help="ISO date YYYY-MM-DD; defaults to today.")
@click.option("--vertical-datum", default="NAVD88", show_default=True,
              help="Vertical datum label stored in ElevationHistory.")
@click.option("--wells-csv", default=None, type=click.Path(exists=True),
              help="CSV with a LocationID column — headless well list. "
                   "Mutually exclusive with --gdb.")
@click.option("--gdb", default=None, type=click.Path(),
              help="File geodatabase: read well IDs from MonitoringWells and write "
                   "elevations (ArcGIS Pro). Mutually exclusive with --wells-csv.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show the update plan without writing to the GDB (use with --gdb).")
@click.option("--approve", is_flag=True, default=False,
              help="Mark written ElevationHistory rows ApprovedForUse=1 "
                   "(default: pending — TOC_ft is updated, approval recorded as 0).")
@qa_report_options
def survey_to_well_elevation_cmd(csv_path, site_id, batch_id, hrms_threshold,
                                 vrms_threshold, elevation_type, survey_date,
                                 vertical_datum, wells_csv, gdb, dry_run, approve,
                                 report, fail_on):
    """Tool 8.5: push QA-passed RTK survey elevations to MonitoringWells.TOC_ft.

    Headless path (--wells-csv): parse RTK CSV, QA-filter, match to a known-wells
    CSV, print the plan — no arcpy. LOCAL path (--gdb): guard for arcpy, read well
    IDs from MonitoringWells, and (unless --dry-run) write TOC_ft + ElevationHistory.
    """
    import uuid
    from datetime import date as _date

    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv
    from autogis.core.envmon.reconcile_locations import read_well_ids_csv
    from autogis.core.envmon.survey_to_well_elevation import (
        build_elevation_history_records, select_rtk_elevations_for_wells,
        write_rtk_elevations_to_wells, sql_quote)

    if gdb and wells_csv:
        raise click.UsageError("--gdb and --wells-csv are mutually exclusive.")
    if not gdb and not wells_csv:
        raise click.UsageError(
            "Provide --wells-csv (headless well list) or --gdb (ArcGIS Pro).")
    if gdb:
        _guard("survey-to-well-elevation")

    bid = batch_id or f"RTK-{uuid.uuid4().hex[:8].upper()}"
    sdate = _date.fromisoformat(survey_date) if survey_date else _date.today()

    points = parse_rtk_csv(Path(csv_path))
    qa = QACollector()

    well_ids: set[str] = set()
    if wells_csv:
        well_ids = set(read_well_ids_csv(Path(wells_csv)))
    elif gdb:
        from autogis.runtime.sessions import arcpy_env as _arcpy
        _ax = _arcpy()
        wells_fc = str(Path(gdb) / "MonitoringWells")
        if _ax.Exists(wells_fc):
            with _ax.da.SearchCursor(wells_fc, ["LocationID"],
                                     f"SiteID='{sql_quote(site_id)}'") as cur:
                for row in cur:
                    if row[0]:
                        well_ids.add(str(row[0]).strip())

    plan = select_rtk_elevations_for_wells(
        points, well_ids, bid, qa,
        hrms_threshold_ft=hrms_threshold, vrms_threshold_ft=vrms_threshold,
        elevation_type=elevation_type)

    click.echo(f"Batch: {plan.batch_id}  Survey date: {sdate}  Site: {site_id}")
    click.echo(f"Updates: {len(plan.updates)}  Skipped: {len(plan.skipped)}  "
               f"Failed QA: {len(plan.failed_qa)}")
    for loc_id, elev in plan.updates.items():
        click.echo(f"  {loc_id}: {elev:.3f} ft ({plan.elevation_type})")

    if gdb and not dry_run and plan.updates:
        history_recs = build_elevation_history_records(
            plan, sdate, vertical_datum=vertical_datum, approved_for_use=approve)
        n = write_rtk_elevations_to_wells(gdb, site_id, plan, history_recs)
        click.echo(f"Updated {n} MonitoringWells records + "
                   f"{len(history_recs)} ElevationHistory rows.")

    _render_qa(qa, report, fail_on)


@envmon.command("update-well-elevations")
@click.option("--run-csv", "run_csv", required=True, type=click.Path(exists=True),
              help="CSV of the single LevelLoopRun row (Tool 8.1 --run-output).")
@click.option("--observations-csv", "observations_csv", required=True,
              type=click.Path(exists=True),
              help="CSV of adjusted LevelLoopObservation rows (Tool 8.1 --observations-output).")
@click.option("--site", "site_id", required=True,
              help="Site ID matching SiteID in MonitoringWells.")
@click.option("--wells-csv", default=None, type=click.Path(exists=True),
              help="CSV with a LocationID column — headless well list. "
                   "Mutually exclusive with --gdb.")
@click.option("--gdb", default=None, type=click.Path(),
              help="File geodatabase: read well IDs from MonitoringWells and write "
                   "TOC_ft + ElevationHistory (ArcGIS Pro). Mutually exclusive with --wells-csv.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show the update plan without writing to the GDB (use with --gdb).")
def update_well_elevations_cmd(run_csv, observations_csv, site_id, wells_csv, gdb, dry_run):
    """Tool 8.2: push a closed level-loop run's elevations to MonitoringWells.TOC_ft.

    Headless path (--wells-csv): read the Tool 8.1 run + observations CSVs, filter to
    known wells, print the update plan -- no arcpy. LOCAL path (--gdb): guard for
    arcpy, read well IDs from MonitoringWells, and (unless --dry-run) write TOC_ft +
    ElevationHistory via update_well_elevations().
    """
    from autogis.core.common.records_csv import read_records_csv
    from autogis.core.common.schema.survey import LevelLoopObservation, LevelLoopRun
    from autogis.core.envmon.level_loop import (
        select_elevations_for_update, update_well_elevations)
    from autogis.core.envmon.reconcile_locations import read_well_ids_csv
    from autogis.core.envmon.survey_to_well_elevation import sql_quote

    if gdb and wells_csv:
        raise click.UsageError("--gdb and --wells-csv are mutually exclusive.")
    if not gdb and not wells_csv:
        raise click.UsageError(
            "Provide --wells-csv (headless well list) or --gdb (ArcGIS Pro).")
    if gdb:
        _guard("update-well-elevations")

    runs = read_records_csv(Path(run_csv), LevelLoopRun)
    if len(runs) != 1:
        raise click.UsageError(f"Expected exactly one LevelLoopRun row, got {len(runs)}.")
    run = runs[0]
    observations = read_records_csv(Path(observations_csv), LevelLoopObservation)

    well_ids: set[str] = set()
    if wells_csv:
        well_ids = set(read_well_ids_csv(Path(wells_csv)))
    elif gdb:
        from autogis.runtime.sessions import arcpy_env as _arcpy
        _ax = _arcpy()
        wells_fc = str(Path(gdb) / "MonitoringWells")
        if _ax.Exists(wells_fc):
            with _ax.da.SearchCursor(wells_fc, ["LocationID"],
                                     f"SiteID='{sql_quote(site_id)}'") as cur:
                for row in cur:
                    if row[0]:
                        well_ids.add(str(row[0]).strip())

    plan = select_elevations_for_update(run, observations, well_ids)

    if plan.blocked:
        raise click.ClickException(
            f"Update blocked: {plan.block_reason} "
            f"(misclosure={run.misclosure_ft} tolerance={run.closure_tolerance_ft} "
            f"adjusted={run.adjusted})")

    click.echo(f"Run: {plan.run_id}  Site: {site_id}")
    click.echo(f"Updates: {len(plan.updates)}  Skipped: {len(plan.skipped)}")
    for loc_id, elev in plan.updates.items():
        click.echo(f"  {loc_id}: {elev:.3f} ft (TOC)")

    if gdb and not dry_run and plan.updates:
        n = update_well_elevations(gdb, site_id, plan)
        click.echo(f"Updated {n} MonitoringWells records + "
                   f"{len(plan.updates)} ElevationHistory rows.")


@envmon.command("update-layout-text")
@click.option("--aprx", "aprx_path", required=True, type=click.Path(exists=True),
              help="Path to the .aprx project file (edited in place).")
@click.option("--layout", "layout_name", default=None,
              help="Layout name inside the APRX (default: all layouts).")
@click.option("--values", "values_path", required=True, type=click.Path(exists=True),
              help="YAML values file: flat {ElementName: text} mapping or a "
                   "list of {element_name, text} dicts.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Apply and report, but do not save the APRX.")
@qa_report_options
def update_layout_text_cmd(aprx_path, layout_name, values_path, dry_run,
                           report, fail_on):
    """Tool 5.8: update APRX layout text elements from a YAML values file
    (ArcGIS Pro).

    Runs layout_manager.update_layout_text — the same step the
    report-figure-package pipeline uses — standalone against an arbitrary
    APRX: sets named text elements, resolves {{placeholder}} tokens, and
    raises a QA warning for any placeholder left unresolved.
    """
    _guard("update-layout-text")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.layout_manager import (
        load_layout_text_yaml, update_layout_text)

    values = load_layout_text_yaml(Path(values_path))
    qa = QACollector()
    update_layout_text(Path(aprx_path), layout_name, values, qa,
                       dry_run=dry_run)
    click.echo(f"Applied {len(values)} text value(s) to "
               f"{layout_name or 'all layouts'} in {aprx_path}"
               + ("  [dry-run: not saved]" if dry_run else ""))
    _render_qa(qa, report, fail_on)


def _ids_arg(value: str) -> list:
    """--sites/--events accept a comma-separated list or a path to a text
    file with one ID per line (blank lines and # comments ignored). Order
    is preserved (unlike _read_id_list's set) — it drives job ordering."""
    p = Path(value)
    if p.is_file():
        return [ln.strip() for ln in
                p.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    return [v.strip() for v in value.split(",") if v.strip()]


@envmon.command("gen-map-series")
@click.option("--sites", required=True,
              help="Comma-separated site IDs, or path to a text file "
                   "(one per line).")
@click.option("--events", required=True,
              help="Comma-separated event IDs/dates, or path to a text file "
                   "(one per line).")
@click.option("--specs", "specs_dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Folder of figure-spec YAMLs (each loaded via FigureSpec).")
@click.option("--mode", type=click.Choice(["per_site", "per_map_type",
                                           "combined_appendix", "historical"]),
              default="per_site", show_default=True,
              help="Packet mode — grouping/naming selector over the same "
                   "site x event x spec matrix.")
@click.option("--format", "out_format", type=click.Choice(["pdf", "png"]),
              default="pdf", show_default=True)
@click.option("--out-dir", default=None, type=click.Path(),
              help="Export folder (required unless --dry-run).")
@click.option("--gdb", default=None, type=click.Path(),
              help="File geodatabase to repath layers to and register exports "
                   "in (required unless --dry-run).")
@click.option("--dpi", type=int, default=300, show_default=True)
@click.option("--dry-run", is_flag=True, default=False,
              help="Print the planned job list without touching arcpy.")
@qa_report_options
def gen_map_series_cmd(sites, events, specs_dir, mode, out_format, out_dir,
                       gdb, dpi, dry_run, report, fail_on):
    """Tool 5.6: batch figure-packet exporter across sites/events (ArcGIS Pro).

    Headless path (--dry-run): expand the site x event x figure-spec matrix
    via plan_map_series() and print the ordered job list — no arcpy. LOCAL
    path: guard for arcpy, then replay the proven ExportFigures chain per job
    (repath data sources, apply definition queries, export layouts, register
    exports in Env_FigureRegistry).
    """
    from autogis.core.common.config import FigureSpec
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.map_series_plan import plan_map_series

    spec_files = sorted(Path(specs_dir).glob("*.y*ml"))
    if not spec_files:
        raise click.UsageError(
            f"No figure-spec YAMLs (*.yaml/*.yml) found in {specs_dir}.")
    specs = {}
    for f in spec_files:
        s = FigureSpec.load(f)
        specs[s.figure_spec_id] = s

    jobs = plan_map_series(_ids_arg(sites), _ids_arg(events),
                           list(specs), mode=mode, out_format=out_format)
    click.echo(f"Planned {len(jobs)} map job(s)  mode={mode}  "
               f"format={out_format}")
    for j in jobs:
        click.echo(f"  {j.out_name}  (site={j.site_id} event={j.event} "
                   f"spec={j.figure_spec})")
    if dry_run:
        return
    if not gdb or not out_dir:
        raise click.UsageError("--gdb and --out-dir are required to export "
                               "(or use --dry-run to preview the plan).")
    _guard("gen-map-series")
    from autogis.core.envmon.export_figures import (
        export_layouts, register_exports)
    from autogis.core.envmon.layout_manager import (
        apply_figure_definition_queries, copy_template_aprx,
        update_aprx_data_sources)

    qa = QACollector()
    gdb_path = Path(gdb)
    export_dir = Path(out_dir)
    written_all = []
    for job in jobs:
        spec = specs[job.figure_spec]
        template = Path(spec.get("template_aprx")
                        or spec.get("aprx_template") or "")
        if not template.is_absolute():
            template = spec.path.parent / template
        stem = Path(job.out_name).stem
        work = copy_template_aprx(template, export_dir / "_working", stem)
        update_aprx_data_sources(work, gdb_path, qa)
        lq = spec.get("layer_definition_queries", {})
        if lq:
            apply_figure_definition_queries(
                work, job.site_id, job.event, job.figure_spec,
                spec.get("map_type", "GW_ANALYTICAL"), lq, qa)
        written = export_layouts(
            work, export_dir, "{stem}", {"stem": stem}, qa,
            layout_names=spec.get("layouts"),
            formats=[job.out_format.upper()], dpi=dpi,
            required_layers=spec.get("required_layers", []))
        register_exports(gdb_path, written, job.site_id, job.event,
                         job.figure_spec, qa)
        for w in written:
            click.echo(f"Exported {w}")
        written_all.extend(written)

    if mode == "combined_appendix" and out_format == "pdf" and written_all:
        # ponytail: cross-APRX combine — same PDFDocumentCreate primitive
        # export_layouts uses for its single-APRX combine_pdf.
        from autogis.runtime.sessions import arcpy_env as _arcpy
        arcpy = _arcpy()
        combined = export_dir / "Appendix_Combined.pdf"
        pdoc = arcpy.mp.PDFDocumentCreate(str(combined))
        for p in written_all:
            pdoc.appendPages(str(p))
        pdoc.saveAndClose()
        click.echo(f"Combined appendix written: {combined} "
                   f"({len(written_all)} figures)")
    _render_qa(qa, report, fail_on)


@envmon.command("reconcile-survey123-lab")
@click.option("--survey", "survey_csv", required=True, type=click.Path(exists=True),
              help="Survey123 export CSV.")
@click.option("--edd", "edd_path", required=True, type=click.Path(exists=True),
              help="Lab EDD CSV or XLSX.")
@click.option("--edd-profile", "profile_path", required=True, type=click.Path(exists=True),
              help="Lab EDD profile YAML.")
@click.option("--site", "site_id", required=True,
              help="Site identifier stamped into run-history audit records "
                   "(ADR-0076); not read by the reconciliation itself.")
@click.option("--threshold", type=float, default=0.85, show_default=True)
@qa_report_options
def reconcile_survey123_lab_cmd(survey_csv, edd_path, profile_path, site_id,
                                threshold, report, fail_on):
    """Pre-production: reconcile Survey123 field submissions vs lab EDD (headless)."""
    from autogis.core.envmon.reconcile_survey123_lab import (
        load_survey123_csv, reconcile_field_lab, reconcile_to_qa)
    from autogis.core.common.config import ParserProfile
    from autogis.core.envmon.edd_importer import extract_sample_roster

    field_samples = load_survey123_csv(Path(survey_csv))
    profile = ParserProfile.load(Path(profile_path))
    lab_samples = extract_sample_roster(Path(edd_path), profile)

    result = reconcile_field_lab(field_samples, lab_samples, threshold=threshold)
    qa = reconcile_to_qa(result)
    _render_qa(qa, report, fail_on)


@envmon.command("route-survey123")
@click.argument("input_path", metavar="INPUT", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--gdb", "gdb_path", required=True, type=click.Path())
@click.option("--batch-id", default=None, help="Override auto-generated batch ID.")
@click.option("--format", "input_format",
              type=click.Choice(["csv", "json"]), default="csv", show_default=True)
@qa_report_options
def route_survey123_cmd(input_path, site_id, gdb_path, batch_id, input_format,
                        report, fail_on):
    """Route Survey123 field submissions into the GDB (ArcGIS Pro)."""
    import json
    import uuid
    import datetime as dt
    _guard("route-survey123")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.normalize_survey123 import (
        normalize_survey123_submission, load_survey123_csv_submissions)
    from autogis.core.envmon.import_to_gdb import (
        append_records_idempotent, finalize_batch, write_qa_to_gdb)
    from autogis.runtime.sessions import arcpy_env

    bid = batch_id or f"S123-{uuid.uuid4().hex[:8].upper()}"
    qa = QACollector()
    gdb = Path(gdb_path)

    if input_format == "json":
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        wl, samp = normalize_survey123_submission(payload, site_id, bid, qa)
    else:
        wl, samp = load_survey123_csv_submissions(Path(input_path), site_id, bid, qa)

    arcpy = arcpy_env()
    batch_fields = ["ImportBatchID", "SiteID", "SiteName", "SourceWorkbook",
                    "SourceWorkbookHash", "ImportDateTime", "ImportedBy",
                    "ParserProfile", "ImportMode", "QAStatus", "SourceSheets"]
    batch_row = [bid, site_id, "", str(input_path)[:255], "",
                 dt.datetime.now(), "survey123_router",
                 "Survey123", "append", "IN_PROGRESS", "Survey123 JSON/CSV"]
    with arcpy.da.InsertCursor(str(gdb / "Env_ImportBatch"), batch_fields) as cur:
        cur.insertRow(batch_row)

    wl_inserted, wl_skipped = append_records_idempotent(gdb, "Env_WaterLevels", wl, qa, bid)
    samp_inserted, samp_skipped = append_records_idempotent(gdb, "Env_Samples", samp, qa, bid)

    counts = {"water_levels": wl_inserted, "samples": samp_inserted}
    finalize_batch(gdb, bid, qa, counts, "COMPLETE")
    write_qa_to_gdb(gdb, qa, bid)

    click.echo(f"Batch {bid}: {wl_inserted} water levels, {samp_inserted} samples imported.")
    _render_qa(qa, report, fail_on)


# ---------------------------------------------------------------------------
# Headless envmon batch (2026-06-28): max-result, merge, QC, compliance,
# regulatory tables, field completeness, GW flow direction, GeoPackage export,
# site narrative, report package. All arcpy-free.
# ---------------------------------------------------------------------------


@envmon.command("merge-event-results")
@click.option("--results", "result_paths", multiple=True, type=click.Path(exists=True),
              help="Result CSV file(s). Repeatable.")
@click.option("--results-dir", default=None, type=click.Path(exists=True),
              help="Directory to scan for result CSVs.")
@click.option("--event-labels", default=None,
              help="Comma-separated event labels (parallel to --results).")
@click.option("--out", required=True, type=click.Path())
@click.option("--manifest", "manifest_path", default=None, type=click.Path())
@click.option("--no-dedup", is_flag=True, default=False)
@qa_report_options
def merge_event_results_cmd(result_paths, results_dir, event_labels,
                             out, manifest_path, no_dedup, report, fail_on):
    """Merge multiple event result CSVs into one long-format file (headless)."""
    from autogis.core.envmon.event_results_merger import merge_event_results

    paths = [Path(p) for p in result_paths]
    if results_dir:
        paths += sorted(Path(results_dir).glob("*.csv"))
    labels = [l.strip() for l in event_labels.split(",")] if event_labels else None
    from autogis.core.envmon.event_results_merger import _DEFAULT_DEDUP_KEY
    result = merge_event_results(
        paths, Path(out),
        event_labels=labels,
        dedup_key=() if no_dedup else _DEFAULT_DEDUP_KEY,
        manifest_path=Path(manifest_path) if manifest_path else None,
    )
    click.echo(f"Sources: {len(result.source_files)}  Rows: {result.total_rows}  "
               f"Duplicates dropped: {result.duplicate_rows_dropped}  Output: {out}")
    _render_qa(result.qa, report, fail_on)


@envmon.command("build-max-result-dataset")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--analytes", default=None)
@click.option("--wells", default=None)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--include-nd", is_flag=True, default=False)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def build_max_result_dataset_cmd(results_path, sl_path, analytes, wells,
                                  date_from, date_to, include_nd, out, report):
    """Build max-detected dataset across all events (headless)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.max_result_dataset import (
        build_max_result_dataset, write_max_result_csv)
    from autogis.core.common.qa import QACollector

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = _yaml.safe_load(Path(sl_path).read_text(encoding="utf-8")) if sl_path else None
    qa = QACollector()
    records = build_max_result_dataset(
        rows, screening_levels=sl,
        analytes=[a.strip() for a in analytes.split(",")] if analytes else None,
        wells=[w.strip() for w in wells.split(",")] if wells else None,
        date_from=date_from, date_to=date_to, include_nd=include_nd, qa=qa,
    )
    write_max_result_csv(records, Path(out))
    exceed = sum(1 for r in records if r.has_exceedance)
    click.echo(f"Records: {len(records)}  Exceedances: {exceed}  Output: {out}")
    _render_qa(qa, report, "warning")


@envmon.command("generate-qc-summary")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def generate_qc_summary_cmd(results_path, out, report):
    """Generate QC data summary workbook (blanks, spikes, duplicates) (headless)."""
    import csv as _csv
    from autogis.core.envmon.qc_sample_summary import (
        classify_qc_rows, write_qc_summary_workbook, QCSummaryResult)
    from autogis.core.common.qa import QACollector

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    records = classify_qc_rows(rows)
    qa = QACollector()
    blank_types = frozenset({"method_blank", "field_blank", "trip_blank"})
    blank_dets = sum(1 for r in records
                     if r.qc_type in blank_types and r.result_value is not None)
    result = QCSummaryResult(records=records, blank_detections=blank_dets,
                              spike_failures=0, duplicate_failures=0, qa=qa)
    write_qc_summary_workbook(result, Path(out))
    click.echo(f"QC records: {len(records)}  Blank detections: {blank_dets}  Output: {out}")
    _render_qa(qa, report, "warning")


@envmon.command("build-compliance-table")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--analytes", default=None)
@click.option("--date-from", default=None)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def build_compliance_table_cmd(results_path, sl_path, analytes, date_from, out, report):
    """Build cross-event compliance summary matrix + detail workbook (headless)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.compliance_summary import (
        build_compliance_summary, write_compliance_workbook)

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = _yaml.safe_load(Path(sl_path).read_text(encoding="utf-8")) if sl_path else None
    analyte_list = [a.strip() for a in analytes.split(",")] if analytes else None
    result = build_compliance_summary(rows, screening_levels=sl,
                                       analytes=analyte_list, date_from=date_from)
    write_compliance_workbook(result, Path(out))
    click.echo(f"Wells: {result.well_count}  Analytes: {result.analyte_count}  "
               f"With exceedances: {result.locations_with_exceedances}  Output: {out}")
    _render_qa(result.qa, report, "warning")


@envmon.command("generate-reg-tables")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--group-map", "gm_path", default=None, type=click.Path(exists=True))
@click.option("--site", "site_id", default="")
@click.option("--event-label", default="")
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def generate_reg_tables_cmd(results_path, sl_path, gm_path, site_id,
                             event_label, out, report):
    """Build regulatory submission pivot table workbook (headless, openpyxl)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.regulatory_table_builder import (
        build_regulatory_table_specs, write_regulatory_workbook)

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = _yaml.safe_load(Path(sl_path).read_text(encoding="utf-8")) if sl_path else None
    gm = _yaml.safe_load(Path(gm_path).read_text(encoding="utf-8")) if gm_path else None
    specs = build_regulatory_table_specs(rows, group_map=gm, screening_levels=sl)
    result = write_regulatory_workbook(rows, specs, Path(out), site_id=site_id,
                                        event_label=event_label, screening_levels=sl)
    click.echo(f"Groups: {result.group_count}  Wells: {result.well_count}  "
               f"Exceedances: {result.exceedance_count}  Output: {out}")
    _render_qa(result.qa, report, "warning")


@envmon.command("validate-field-completeness")
@click.option("--plan", "plan_path", required=True, type=click.Path(exists=True))
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def validate_field_completeness_cmd(plan_path, results_path, out, report, fail_on):
    """Compare sampling plan vs. lab results for completeness (headless)."""
    import csv as _csv
    from autogis.core.envmon.field_completeness_validator import (
        validate_field_completeness, write_completeness_report)

    with open(plan_path, newline="", encoding="utf-8") as fh:
        plan = list(_csv.DictReader(fh))
    with open(results_path, newline="", encoding="utf-8") as fh:
        results = list(_csv.DictReader(fh))
    result = validate_field_completeness(plan, results)
    write_completeness_report(result, Path(out))
    click.echo(f"Planned: {result.planned_count}  Received: {result.received_count}  "
               f"Matched: {result.matched_count}  Issues: {len(result.issues)}  Out: {out}")
    _render_qa(result.qa, report, fail_on)


@envmon.command("estimate-gw-flow-direction")
@click.option("--wells-csv", required=True, type=click.Path(exists=True),
              help="CSV with columns: well_id, easting, northing, gwe_ft.")
@click.option("--site-id", required=True, help="Site identifier.")
@click.option("--event-date", required=True,
              help="Event date YYYY-MM-DD (metadata only; not used in math).")
@click.option("--run-id", default=None,
              help="Run identifier; auto-generated UUID4 if omitted.")
@click.option("--output", default=None, type=click.Path(),
              help="Write GWFlowResult to this CSV path (one-row output).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report (.csv / .json / .md).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def estimate_gw_flow_direction_cmd(wells_csv, site_id, event_date, run_id,
                                    output, report, fail_on):
    """Tool 4.3: estimate GW flow direction and gradient (DRAFT) from well GWEs.

    Fits a least-squares plane h = a·E + b·N + c to 3+ well water levels and
    derives hydraulic gradient magnitude and flow azimuth (degrees from N, CW).
    Outputs are always DRAFT_REVIEW_REQUIRED.
    """
    import csv as _csv
    from dataclasses import asdict
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.estimate_gw_flow_direction import (
        parse_wells_csv, estimate_gw_flow_direction,
    )

    wells = parse_wells_csv(Path(wells_csv))
    qa = QACollector()
    result = estimate_gw_flow_direction(
        wells,
        run_id=run_id,
        site_id=site_id,
        event_date=event_date,
        qa=qa,
    )

    click.echo(
        f"Flow azimuth: {result.flow_azimuth_deg:.1f} deg  "
        f"Gradient: {result.gradient_magnitude:.6f} ft/ft  "
        f"Method: {result.method}  "
        f"Status: {result.qa_status}  [DRAFT_REVIEW_REQUIRED]"
    )

    if output:
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(result)
        d["well_ids"] = ",".join(result.well_ids)
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(d.keys()))
            w.writeheader()
            w.writerow(d)
        click.echo(f"Result written: {output}")

    _render_qa(qa, report, fail_on)


@envmon.command("evaluate-gw-models")
@click.option("--observations", "observations_csv", required=True,
              type=click.Path(exists=True),
              help="Wide CSV: well_id, observed_ft, one column per model.")
@click.option("--tolerance-ft", type=float, default=0.5, show_default=True,
              help="Absolute error threshold for the percent-within-tolerance stat.")
@click.option("--output", default=None, type=click.Path(),
              help="Optional CSV path for per-model ranked results.")
@qa_report_options
def evaluate_gw_models_cmd(observations_csv, tolerance_ft, output, report, fail_on):
    """Cross-validate interpolation model predictions against observed values."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.evaluate_gw_models import (
        evaluate_gw_models,
        read_gw_model_csv,
        write_model_stats_csv,
    )

    observations = read_gw_model_csv(Path(observations_csv))
    qa = QACollector()
    stats = evaluate_gw_models(observations, tolerance_ft=tolerance_ft, qa=qa)

    for s in stats:
        click.echo(f"  #{s.rank} {s.model_name}: RMSE={s.rmse:.4f} ft  "
                   f"MAE={s.mae:.4f} ft  bias={s.mean_error:+.4f} ft  "
                   f"{s.pct_within_tolerance:.1f}% within {tolerance_ft} ft")

    if output:
        write_model_stats_csv(stats, Path(output))
        click.echo(f"Results written: {output}")

    _render_qa(qa, report, fail_on)


@envmon.command("export-geopackage")
@click.option("--wells", "wells_path", required=True, type=click.Path(exists=True))
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--water-levels", "wl_path", default=None, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--overwrite", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
def export_geopackage_cmd(wells_path, results_path, wl_path, out,
                           overwrite, report):
    """Export envmon data to OGC GeoPackage (stdlib sqlite3, headless)."""
    import csv as _csv
    from autogis.core.envmon.geopackage_exporter import export_env_data_geopackage

    with open(wells_path, newline="", encoding="utf-8") as fh:
        wells = list(_csv.DictReader(fh))
    with open(results_path, newline="", encoding="utf-8") as fh:
        results = list(_csv.DictReader(fh))
    wl_rows = None
    if wl_path:
        with open(wl_path, newline="", encoding="utf-8") as fh:
            wl_rows = list(_csv.DictReader(fh))
    result = export_env_data_geopackage(wells, results, Path(out),
                                         water_level_rows=wl_rows,
                                         overwrite=overwrite)
    click.echo(f"Wells: {result.well_count}  Results: {result.result_count}  "
               f"Layers: {result.layers}  Output: {out}")
    _render_qa(result.qa, report, "warning")


@envmon.command("generate-site-narrative")
@click.option("--site", "site_id", required=True)
@click.option("--event-label", required=True)
@click.option("--max-results", "max_results_path", default=None,
              type=click.Path(exists=True))
@click.option("--change-log", "change_log_path", default=None,
              type=click.Path(exists=True))
@click.option("--plan", "plan_path", default=None, type=click.Path(exists=True))
@click.option("--results", "results_path", default=None, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--top-n", type=int, default=5, show_default=True)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def generate_site_narrative_cmd(site_id, event_label, max_results_path,
                                 change_log_path, plan_path, results_path,
                                 sl_path, top_n, out, report):
    """Generate template-driven site monitoring narrative (headless)."""
    import yaml as _yaml
    from autogis.core.envmon.site_narrative_generator import generate_site_narrative

    sl = _yaml.safe_load(Path(sl_path).read_text(encoding="utf-8")) if sl_path else None
    result = generate_site_narrative(
        site_id, event_label,
        max_result_path=Path(max_results_path) if max_results_path else None,
        change_log_path=Path(change_log_path) if change_log_path else None,
        plan_path=Path(plan_path) if plan_path else None,
        result_path=Path(results_path) if results_path else None,
        screening_levels=sl, top_n=top_n,
    )
    Path(out).write_text(result.full_text, encoding="utf-8")
    click.echo(f"Sections: {len(result.sections)}  Output: {out}")
    _render_qa(result.qa, report, "warning")


@envmon.command("build-report-package")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True))
@click.option("--out-dir", required=True, type=click.Path())
@click.option("--site", "site_id", default="")
@click.option("--event-label", default="")
@click.option("--report", default=None, type=click.Path())
def build_report_package_cmd(spec_path, out_dir, site_id, event_label, report):
    """Assemble deliverable folder from YAML spec (headless)."""
    from autogis.core.envmon.report_figure_package import (
        load_deliverable_spec, assemble_figure_package)
    from autogis.core.common.qa import QACollector

    entries = load_deliverable_spec(Path(spec_path))
    qa = QACollector()
    result = assemble_figure_package(entries, Path(out_dir),
                                      site_id=site_id, event_label=event_label, qa=qa)
    click.echo(f"Copied: {result.copied_count}  Missing: {result.missing_count}  "
               f"Out: {out_dir}")
    _render_qa(qa, report, "warning")


@envmon.command("export-lab-request")
@click.option("--plan", "plan_path", required=True, type=click.Path(exists=True))
@click.option("--analyte-groups", "groups_path", required=True, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--project-code", default="")
@click.option("--turnaround", type=int, default=5, show_default=True)
@click.option("--site", "site_id", default="")
@click.option("--csv-also", "csv_path", default=None, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def export_lab_request_cmd(plan_path, groups_path, out, project_code,
                            turnaround, site_id, csv_path, report):
    """Generate lab analytical request workbook from sampling event plan (headless)."""
    import csv as _csv
    import yaml as _yaml
    from autogis.core.envmon.lab_request_exporter import (
        build_lab_request_rows, write_lab_request_workbook, write_lab_request_csv)

    with open(plan_path, newline="", encoding="utf-8") as fh:
        plan = list(_csv.DictReader(fh))
    groups = _yaml.safe_load(Path(groups_path).read_text(encoding="utf-8"))
    rows = build_lab_request_rows(plan, groups, project_code=project_code,
                                   turnaround_days=turnaround)
    result = write_lab_request_workbook(rows, Path(out), site_id=site_id)
    if csv_path:
        write_lab_request_csv(rows, Path(csv_path))
    click.echo(f"Samples: {result.sample_count}  Groups: {result.analyte_group_count}  "
               f"Output: {out}")
    _render_qa(result.qa, report, "warning")


@envmon.command("build-report-appendix")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--group-map", "group_map_path", default=None, type=click.Path(exists=True))
@click.option("--site", "site_id", default="")
@click.option("--event-dates", default=None,
              help="Comma-separated event dates to include (default: all).")
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def build_report_appendix_cmd(results_path, sl_path, group_map_path, site_id,
                              event_dates, out, report):
    """Build multi-sheet Excel analytical-data appendix (headless)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.report_appendix_builder import (
        build_appendix_sheet_specs, write_appendix_workbook)
    from autogis.core.common.qa import QACollector

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = _yaml.safe_load(Path(sl_path).read_text()) if sl_path else None
    group_map = (_yaml.safe_load(Path(group_map_path).read_text())
                 if group_map_path else None)
    dates = [d.strip() for d in event_dates.split(",")] if event_dates else None
    qa = QACollector()
    specs = build_appendix_sheet_specs(rows, screening_levels=sl,
                                       group_map=group_map)
    result = write_appendix_workbook(rows, specs, Path(out), site_id=site_id,
                                     event_dates=dates, qa=qa)
    click.echo(f"Sheets: {result.sheet_count}  Wells: {result.well_count}  "
               f"Events: {result.event_count}  Output: {out}")
    _render_qa(qa, report, "warning")


@envmon.command("build-dashboard-data-mart")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--event", "event_id", required=True)
@click.option("--prior-event", "prior_event_id", default=None)
def build_dashboard_data_mart_cmd(gdb, site_id, event_id, prior_event_id):
    """Tool 6.7: truncate + repopulate the Dash_* mart tables (ArcGIS Pro)."""
    _guard("build-dashboard-data-mart")
    from autogis.core.envmon.dashboard_data_mart import build_dashboard_data_mart
    summary = build_dashboard_data_mart(gdb, site_id, event_id,
                                        prior_event_id=prior_event_id)
    for table, n in summary.row_counts.items():
        click.echo(f"{table}: {n} row(s)")
    click.echo(f"Updated {len(summary.tables_updated)} table(s) "
               f"for {site_id}/{event_id}.")


@envmon.command("build-exceedance-event")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", required=True, type=click.Path(exists=True))
@click.option("--rule", default="max_exceedance_per_location",
              type=click.Choice(["max_exceedance_per_location", "latest_per_location",
                                 "specific_event_date", "date_range_latest"]))
@click.option("--event-date", default=None)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def build_exceedance_event_cmd(results_path, sl_path, rule, event_date,
                               date_from, date_to, out, report):
    """Build exceedance event dataset with ratio/tier enrichment (headless)."""
    import csv as _csv
    from autogis.core.envmon.build_exceedance_event import (
        build_exceedance_event, load_screening_levels_yaml,
        write_exceedance_event_csv)
    from autogis.core.common.qa import QACollector

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = load_screening_levels_yaml(Path(sl_path))
    date_range = (date_from, date_to) if (date_from and date_to) else None
    qa = QACollector()
    records = build_exceedance_event(
        rows, sl, rule=rule, event_date=event_date,
        date_range=date_range, qa=qa)
    write_exceedance_event_csv(records, Path(out))
    exceed = sum(1 for r in records if r.has_exceedance)
    click.echo(f"Records: {len(records)}  Exceedances: {exceed}  Output: {out}")
    _render_qa(qa, report, "warning")


@envmon.command("list-tools")
@click.option("--runtime", "runtime_filter", default=None,
              type=click.Choice(["CLOUD", "LOCAL", "DRAFT"], case_sensitive=False))
@click.option("--domain", default=None)
@click.option("--status", default=None,
              type=click.Choice(["stable", "draft", "planned", "deprecated"],
                                case_sensitive=False))
@click.option("--search", default=None)
@click.option("--verbose", is_flag=True, default=False)
def list_tools_cmd(runtime_filter, domain, status, search, verbose):
    """List available envmon + agol tools with capability metadata (headless)."""
    from autogis.core.envmon.tool_registry import (
        get_all_tools, filter_tools, format_tool_table)

    entries = filter_tools(get_all_tools(), runtime=runtime_filter,
                           domain=domain, status=status, search=search)
    if not entries:
        click.echo("No tools match the given filters.")
        return
    click.echo(format_tool_table(entries, verbose=verbose))
    click.echo(f"\n{len(entries)} tool(s).")


@envmon.command("generate-trend-charts")
@click.option("--history-csv", required=True, type=click.Path(exists=True),
              help="History CSV (LocationID, AnalyteName, SampleDate, "
                   "ResultValue, ReportedUnits, ScreeningLevel).")
@click.option("--out", required=True, type=click.Path(), help="Output .xlsx path.")
@click.option("--analytes", default=None,
              help="Comma-separated analytes to include (default: all).")
@click.option("--wells", default=None,
              help="Comma-separated location IDs to include (default: all).")
@click.option("--screening-levels", "sl_path", default=None,
              type=click.Path(exists=True),
              help="Optional YAML {AnalyteName: screening level} overriding the CSV.")
@click.option("--max-per-sheet", type=int, default=20, show_default=True)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def generate_trend_charts_cmd(history_csv, out, analytes, wells, sl_path,
                              max_per_sheet, report, fail_on):
    """Tool 4.6: generate Excel trend-chart workbook from a history CSV (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.well_trend_charts import (
        load_history_csv, write_trend_charts)

    qa = QACollector()
    series_list = load_history_csv(Path(history_csv))
    if analytes:
        keep = {a.strip() for a in analytes.split(",")}
        series_list = [s for s in series_list if s.analyte_name in keep]
    if wells:
        keep_wells = {w.strip() for w in wells.split(",")}
        series_list = [s for s in series_list if s.location_id in keep_wells]
    if sl_path:
        sl_map = yaml.safe_load(Path(sl_path).read_text(encoding="utf-8")) or {}
        if not isinstance(sl_map, dict):
            raise click.ClickException(
                f"--screening-levels {sl_path} must be a YAML mapping of "
                f"{{AnalyteName: level}}, got {type(sl_map).__name__}.")
        for s in series_list:
            if s.analyte_name in sl_map:
                try:
                    s.screening_level = float(sl_map[s.analyte_name])
                except (TypeError, ValueError):
                    pass
    chart_count = write_trend_charts(series_list, Path(out),
                                     max_per_sheet=max_per_sheet)
    click.echo(f"Written: {out}  ({len(series_list)} series, "
               f"{chart_count} chart(s))")
    _render_qa(qa, report, fail_on)


@envmon.command("ingest-reviewer-comments")
@click.argument("input_file", metavar="INPUT", type=click.Path(exists=True))
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output tracker CSV path (created or overwritten).")
@click.option("--tracker", "tracker_path", default=None, type=click.Path(),
              help="Existing comment tracker CSV to merge into (optional).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def ingest_reviewer_comments_cmd(input_file, out_path, tracker_path, report, fail_on):
    """Tool 9.4: ingest reviewer map comments/redlines into a tracked table.

    INPUT may be a flat CSV, GeoJSON FeatureCollection (AGOL comment export),
    or XLSX spreadsheet; format is auto-detected from the extension. Pass a
    previous --out as --tracker to merge while preserving existing status.
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.ingest_reviewer_comments import (
        ingest_comments, read_tracker_csv, merge_tracker,
        write_tracker_csv, format_comment_summary)

    qa = QACollector()
    incoming = ingest_comments(Path(input_file), qa=qa)
    existing = read_tracker_csv(Path(tracker_path)) if tracker_path else []
    merged = merge_tracker(existing, incoming, qa=qa)
    out = Path(out_path)
    write_tracker_csv(merged, out)
    click.echo(f"Written: {out}  ({len(merged)} comment(s))")
    click.echo(format_comment_summary(merged))
    _render_qa(qa, report, fail_on)


@envmon.command("select-soil-intervals")
@click.option("--results-csv", "results_csv", required=True,
              type=click.Path(exists=True),
              help="Soil results CSV (LocationID, TopDepthFt, BottomDepthFt, "
                   "AnalyteName, ResultValue, ResultQualifier, ReportedUnits, "
                   "ScreeningLevel, ExceedsScreeningLevel).")
@click.option("--out", required=True, type=click.Path(),
              help="Output CSV path for tiered intervals.")
@click.option("--analytes", default=None,
              help="Comma-separated analyte names to include (default: all).")
@click.option("--tiers", default=None,
              help="Comma-separated tiers to include: HOTSPOT,DETECT,ND,NO_DATA "
                   "(default: all).")
@click.option("--max-depth-ft", "max_depth_ft", type=float, default=None,
              help="Exclude intervals with top_depth_ft greater than this value.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def select_soil_intervals_cmd(results_csv, out, analytes, tiers, max_depth_ft,
                              report, fail_on):
    """Assign display tiers to soil sample intervals and write a mapping CSV (headless)."""
    from autogis.core.envmon.soil_interval_selector import (
        load_soil_results_csv, select_intervals, write_intervals_csv)
    from autogis.core.common.qa import QACollector

    analyte_list = [a.strip() for a in analytes.split(",")] if analytes else None
    tier_list = [t.strip().upper() for t in tiers.split(",")] if tiers else None
    qa = QACollector()
    intervals = load_soil_results_csv(results_csv)
    rows = select_intervals(intervals, analytes=analyte_list, tiers=tier_list,
                            max_depth_ft=max_depth_ft, qa=qa)
    write_intervals_csv(rows, Path(out))
    click.echo(f"Intervals selected: {len(rows)}  Output: {out}")
    _render_qa(qa, report, fail_on)


@envmon.command("export-comparison-excel")
@click.option("--comparison-csv", required=True, type=click.Path(exists=True),
              help="ComparisonRecord CSV (output of compare-events).")
@click.option("--output", required=True, type=click.Path())
@click.option("--overwrite", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def export_comparison_excel_cmd(comparison_csv, output, overwrite, report, fail_on):
    """Tool 4.8: export comparison results to a formatted Excel workbook (headless)."""
    import csv as _csv
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.export_comparison_excel import export_comparison_excel

    with open(comparison_csv, newline="", encoding="utf-8") as fh:
        records = list(_csv.DictReader(fh))
    qa = QACollector()
    export_comparison_excel(records, Path(output), overwrite=overwrite, qa=qa)
    click.echo(f"Records: {len(records)}  Output: {output}")
    _render_qa(qa, report, fail_on)


@envmon.command("generate-job-queue")
@click.option("--manifest", required=True, type=click.Path(exists=True),
              help="YAML with sites, tools, and optional per-tool args.")
@click.option("--output", required=True, type=click.Path(),
              help="Output JSON queue file.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def generate_job_queue_cmd(manifest, output, report, fail_on):
    """Tool 10.4: generate an ordered job-queue JSON from a manifest YAML (headless)."""
    import json as _json
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.job_queue import generate_job_queue

    spec = yaml.safe_load(Path(manifest).read_text(encoding="utf-8")) or {}
    if not isinstance(spec, dict):
        raise click.ClickException(
            f"--manifest {manifest} must be a YAML mapping with 'sites'/'tools' "
            f"keys, got {type(spec).__name__}.")
    site_ids = spec.get("sites") or []
    tool_names = spec.get("tools") or []
    extra_args = spec.get("args") or {}
    qa = QACollector()
    entries = generate_job_queue(site_ids, tool_names, extra_args, qa=qa)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps([e.to_dict() for e in entries], indent=2),
                   encoding="utf-8")
    click.echo(f"Jobs: {len(entries)}  Output: {output}")
    _render_qa(qa, report, fail_on)


@envmon.command("draft-parser-profile")
@click.argument("workbook", type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path(),
              help="Path to write the draft YAML profile.")
@click.option("--profile-id", default="DRAFT", show_default=True,
              help="Profile ID embedded in the output YAML.")
@click.option("--scan-rows", type=int, default=40, show_default=True,
              help="Rows to scan per sheet for structure detection.")
def draft_parser_profile_cmd(workbook, output, profile_id, scan_rows):
    """Tool 2.1: inspect a workbook and write a draft parser profile YAML (headless)."""
    import yaml as _yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.excel_workbook_inspector import (
        inspect_workbook_structure,
        propose_parser_profile,
    )

    qa = QACollector()
    report = inspect_workbook_structure(Path(workbook), scan_rows=scan_rows, qa=qa)
    profile_dict = propose_parser_profile(report, profile_id=profile_id)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_yaml.dump(profile_dict, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    click.echo(f"Draft profile written: {out}  "
               f"({len(report.sheets)} sheet(s) — REVIEW BEFORE USE)")
    if qa.records:
        _render_qa(qa, None, "error")


@envmon.command("draft-edd-profile")
@click.argument("sample_file", type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path(),
              help="Path to write the draft LabEDD profile YAML.")
@click.option("--profile-id", default="DRAFT", show_default=True,
              help="Profile ID embedded in the output YAML.")
@click.option("--lab-name", default=None,
              help="Lab name for the profile (default: sample file stem).")
def draft_edd_profile_cmd(sample_file, output, profile_id, lab_name):
    """Tool 2.3a: inspect a sample lab EDD and write a draft LabEDD profile
    YAML (headless). Counterpart to draft-parser-profile for flat lab EDDs."""
    import yaml as _yaml
    from autogis.core.envmon.edd_profile_draft import (
        REQUIRED_FIELDS,
        draft_edd_profile,
        drafted_profile_to_yaml_dict,
    )

    try:
        drafted = draft_edd_profile(Path(sample_file))
    except ValueError as exc:
        raise click.ClickException(str(exc))
    profile_dict = drafted_profile_to_yaml_dict(
        drafted, profile_id=profile_id,
        lab_name=lab_name or Path(sample_file).stem)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_yaml.dump(profile_dict, allow_unicode=True,
                              sort_keys=False),
                   encoding="utf-8")
    # count only actionable review items (required unmapped or ambiguous),
    # not optional fields simply absent from the export
    review = sum(1 for f in drafted.fields if f.status == "NEEDS_REVIEW"
                 and (f.candidates or f.canonical_name in REQUIRED_FIELDS))
    click.echo(f"Draft profile written: {out}  "
               f"({review} field(s) need review — REVIEW BEFORE USE)")
    click.echo("Next: edit the _TODO mappings, then test headlessly with "
               "'autogis envmon batch-import-workbooks' before import-edd.")


@envmon.command("validate-lab-profile")
@click.argument("profile_yaml", type=click.Path(exists=True))
@qa_report_options
def validate_lab_profile_cmd(profile_yaml, report, fail_on):
    """Validate a LabEDD profile YAML is well-formed (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.edd_profile import (
        LabEDDProfile,
        validate_edd_profile,
    )

    try:
        profile = LabEDDProfile.load(Path(profile_yaml))
    except Exception as exc:  # noqa: BLE001 — surface load failure cleanly
        raise click.ClickException(f"Cannot load profile: {exc}")
    qa = QACollector()
    validate_edd_profile(profile, qa)
    _render_qa(qa, report, fail_on)


@envmon.command("batch-import-workbooks")
@click.option("--manifest", default=None, type=click.Path(exists=True),
              help="CSV with columns: workbook_path, profile_path, site_id. "
                   "Mutually exclusive with --edd-dir.")
@click.option("--edd-dir", default=None,
              type=click.Path(exists=True, file_okay=False),
              help="Directory of EDD files to import with one shared "
                   "--profile/--site. Mutually exclusive with --manifest.")
@click.option("--profile", default=None, type=click.Path(exists=True),
              help="LabEDD profile YAML/JSON applied to every file "
                   "(--edd-dir mode only).")
@click.option("--site", default=None,
              help="Site ID applied to every file (--edd-dir mode only).")
@click.option("--pattern", default=None,
              help="Glob for --edd-dir (default *.csv, falling back to "
                   "*.xlsx if no CSV matches).")
@click.option("--output-dir", required=True, type=click.Path(),
              help="Directory to write sample_records.csv, result_records.csv, "
                   "and batch_manifest.csv.")
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary YAML (optional).")
@click.option("--screening", default=None, type=click.Path(exists=True),
              help="Screening levels YAML (optional).")
@click.option("--event-date", default=None,
              help="Force event date for all workbooks (YYYY-MM-DD).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def batch_import_workbooks_cmd(manifest, edd_dir, profile, site, pattern,
                               output_dir, analytes, screening,
                               event_date, report, fail_on):
    """Tool 2.2: batch-import EDD workbooks from a manifest CSV or a directory (headless)."""
    import yaml as _yaml
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import write_records_csv
    from autogis.core.envmon.batch_workbook_importer import (
        read_manifest_csv, manifest_rows_from_dir, run_batch_import,
        BatchManifestRow)

    if (manifest is None) == (edd_dir is None):
        raise click.UsageError(
            "Provide exactly one input mode: --manifest OR --edd-dir.")
    if manifest and (profile or site or pattern):
        raise click.UsageError(
            "--profile/--site/--pattern apply only with --edd-dir.")
    if edd_dir:
        if not (profile and site):
            raise click.UsageError("--edd-dir requires --profile and --site.")
        manifest_rows = manifest_rows_from_dir(
            Path(edd_dir), Path(profile), site, pattern)
        if not manifest_rows:
            raise click.ClickException(
                "No EDD files matching %s in %s"
                % (pattern or "*.csv (or *.xlsx)", edd_dir))
    else:
        manifest_rows = read_manifest_csv(Path(manifest))
    analyte_dict = _yaml.safe_load(Path(analytes).read_text(encoding="utf-8")) \
        if analytes else {}
    screening_lvls = _yaml.safe_load(Path(screening).read_text(encoding="utf-8")) \
        if screening else {}
    ev_date = _date.fromisoformat(event_date) if event_date else None
    qa = QACollector()

    result = run_batch_import(
        manifest_rows,
        analyte_dictionary=analyte_dict,
        screening_levels=screening_lvls,
        event_date_override=ev_date,
        qa=qa,
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_records_csv(result.manifest,
                      out_dir / "batch_manifest.csv",
                      record_class=BatchManifestRow)
    if result.all_samples:
        write_records_csv(result.all_samples,
                          out_dir / "sample_records.csv",
                          record_class=type(result.all_samples[0]))
    if result.all_results:
        write_records_csv(result.all_results,
                          out_dir / "result_records.csv",
                          record_class=type(result.all_results[0]))

    ok = sum(1 for m in result.manifest if m.Status == "OK")
    click.echo(f"Batch import: {ok}/{len(result.manifest)} OK  "
               f"→ {len(result.all_samples)} samples, "
               f"{len(result.all_results)} results  "
               f"[{out_dir}]")
    _render_qa(qa, report, fail_on)


@envmon.command("migrate-legacy-data")
@click.option("--input-csv", required=True, type=click.Path(exists=True),
              help="Wide-format legacy CSV (rows = samples, columns = analytes).")
@click.option("--output", required=True, type=click.Path(),
              help="Output long-format result CSV path.")
@click.option("--location-col", default="LocationID", show_default=True)
@click.option("--date-col", default="SampleDate", show_default=True)
@click.option("--matrix-col", default=None,
              help="Column name for matrix (omit to use --default-matrix).")
@click.option("--sample-id-col", default=None,
              help="Column for sample ID (auto-generated if omitted).")
@click.option("--site-id", default="", help="Site ID to embed in output rows.")
@click.option("--default-matrix", default="GW", show_default=True)
@click.option("--default-units", default="ug/L", show_default=True)
@click.option("--nondetect-prefix", default="<", show_default=True,
              help="String prefix indicating a non-detect result.")
@click.option("--units-yaml", default=None, type=click.Path(exists=True),
              help="YAML mapping analyte_name -> units override.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def migrate_legacy_data_cmd(input_csv, output, location_col, date_col,
                             matrix_col, sample_id_col, site_id,
                             default_matrix, default_units, nondetect_prefix,
                             units_yaml, report, fail_on):
    """Tool 2.4: convert wide-format legacy CSV to long-format result records (headless)."""
    import yaml as _yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import write_records_csv
    from autogis.core.envmon.legacy_migrator import (
        MigrationConfig, migrate_wide_csv, LegacyResultRow)

    cfg = MigrationConfig(
        location_col=location_col, date_col=date_col,
        matrix_col=matrix_col, sample_id_col=sample_id_col,
        site_id=site_id, default_matrix=default_matrix,
        default_units=default_units, nondetect_prefix=nondetect_prefix,
    )
    units_map = _yaml.safe_load(Path(units_yaml).read_text(encoding="utf-8")) \
        if units_yaml else {}
    qa = QACollector()

    rows = migrate_wide_csv(Path(input_csv), cfg, units_map=units_map, qa=qa)
    write_records_csv(rows, Path(output), record_class=LegacyResultRow)
    click.echo(f"Migrated: {len(rows)} result rows → {output}")
    _render_qa(qa, report, fail_on)


@envmon.command("create-sampling-plan")
@click.option("--wells-csv", required=True, type=click.Path(exists=True),
              help="CSV of well network (required: location_id; optional: matrix, "
                   "analyte_groups).")
@click.option("--analyte-groups", required=True, type=click.Path(exists=True),
              help="YAML mapping group_name -> {bottles, bottle_size_ml, "
                   "preservation, matrix}.")
@click.option("--event-date", required=True,
              help="Planned sampling date YYYY-MM-DD.")
@click.option("--site-id", default="", help="Site ID.")
@click.option("--prior-event-date", default=None,
              help="Prior event date YYYY-MM-DD (optional).")
@click.option("--samples-output", required=True, type=click.Path(),
              help="Path to write planned sample list CSV.")
@click.option("--bottles-output", required=True, type=click.Path(),
              help="Path to write bottle count summary CSV.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def create_sampling_plan_cmd(wells_csv, analyte_groups, event_date, site_id,
                              prior_event_date, samples_output, bottles_output,
                              report, fail_on):
    """Tool 7.2: generate planned sample list and bottle count for an event (headless)."""
    import yaml as _yaml
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import write_records_csv
    from autogis.core.envmon.sampling_plan import (
        read_well_network_csv, create_sampling_plan,
        PlannedSample, BottleCountRow)

    wells = read_well_network_csv(Path(wells_csv))
    groups = _yaml.safe_load(Path(analyte_groups).read_text(encoding="utf-8"))
    ev_date = _date.fromisoformat(event_date)
    prior = _date.fromisoformat(prior_event_date) if prior_event_date else None
    qa = QACollector()

    plan = create_sampling_plan(
        wells, groups, site_id=site_id,
        event_date=ev_date, prior_event_date=prior, qa=qa)

    write_records_csv(plan.samples, Path(samples_output),
                      record_class=PlannedSample)
    write_records_csv(plan.bottle_summary, Path(bottles_output),
                      record_class=BottleCountRow)
    click.echo(f"Sampling plan: {len(plan.samples)} planned samples  "
               f"→ {samples_output}")
    click.echo(f"Bottle summary: {len(plan.bottle_summary)} groups  "
               f"→ {bottles_output}")
    _render_qa(qa, report, fail_on)


@envmon.command("reconcile-field-lab")
@click.option("--field-csv", required=True, type=click.Path(exists=True),
              help="Field samples CSV (required: sample_id, location_id, "
                   "collection_date).")
@click.option("--lab-csv", required=True, type=click.Path(exists=True),
              help="Lab results CSV (required: sample_id, location_id, "
                   "analysis_date, analyte_name).")
@click.option("--output", required=True, type=click.Path(),
              help="Output reconciliation flags CSV.")
@click.option("--date-tolerance", type=int, default=1, show_default=True,
              help="Allowed date gap in days before DATE_MISMATCH flag.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def reconcile_field_lab_cmd(field_csv, lab_csv, output, date_tolerance,
                             report, fail_on):
    """Tool 7.3: compare field records to lab results, flag mismatches (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import write_records_csv
    from autogis.core.envmon.field_lab_reconciler import (
        read_field_samples_csv, read_lab_results_csv,
        reconcile_field_and_lab, ReconciliationFlag)

    field_samples = read_field_samples_csv(Path(field_csv))
    lab_results = read_lab_results_csv(Path(lab_csv))
    qa = QACollector()

    flags = reconcile_field_and_lab(
        field_samples, lab_results,
        date_tolerance_days=date_tolerance, qa=qa)
    write_records_csv(flags, Path(output), record_class=ReconciliationFlag)
    errors = sum(1 for f in flags if f.Severity == "ERROR")
    click.echo(f"Reconciliation: {len(flags)} flag(s) "
               f"({errors} errors) → {output}")
    _render_qa(qa, report, fail_on)


@envmon.command("draft-plume-boundary")
@click.option("--results", "results_csv", default=None, type=click.Path(exists=True),
              help="AnalyticalResultRecord CSV — filtered to ExceedsScreeningLevel=1 rows. "
                   "Mutually exclusive with --points.")
@click.option("--coords", "coords_csv", default=None, type=click.Path(exists=True),
              help="location_id,x,y CSV — required with --results.")
@click.option("--points", "points_csv", default=None, type=click.Path(exists=True),
              help="Pre-filtered location_id,x,y[,analyte,event_date] exceedance-point CSV. "
                   "Mutually exclusive with --results/--coords.")
@click.option("--site", "site_id", default="", help="Site ID stored for provenance.")
@click.option("--analyte", default=None,
              help="Filter to a single analyte (only used with --results).")
@click.option("--hull-method", type=click.Choice(["convex", "concave"]),
              default="convex", show_default=True)
@click.option("--k-neighbors", type=int, default=3, show_default=True,
              help="Starting k for --hull-method concave (npg enforces k>=3).")
@click.option("--out", "out_path", default=None, type=click.Path(),
              help="Write GeoJSON to this path (stdout if omitted).")
@click.option("--gdb", default=None, type=click.Path(),
              help="File geodatabase: write the draft polygon to "
                   "Env_PlumeBoundary_Draft (ArcGIS Pro).")
@click.option("--boundary-fc", default=None,
              help="Site-boundary polygon feature class: clip the hull to it "
                   "before the GDB write (requires --gdb).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Compute and print the boundary without writing to --gdb.")
@qa_report_options
def draft_plume_boundary_cmd(results_csv, coords_csv, points_csv, site_id, analyte,
                             hull_method, k_neighbors, out_path, gdb, boundary_fc,
                             dry_run, report, fail_on):
    """Tool 4.5: draft plume-extent polygon (convex/concave hull) from exceedance points.

    DRAFT output for analyst review only — not a geostatistical model. Provide
    either --points (pre-filtered) or --results + --coords (filtered here).
    """
    import json as _json

    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.draft_plume_boundary import (
        compute_draft_plume_boundary, filter_results_to_exceedance_points,
        load_exceedance_points_csv, result_to_geojson, result_to_wkt,
        write_plume_draft_to_gdb)

    if points_csv and (results_csv or coords_csv):
        raise click.UsageError("--points is mutually exclusive with --results/--coords.")
    if not points_csv and not (results_csv and coords_csv):
        raise click.UsageError("Provide --points, or both --results and --coords.")
    if boundary_fc and not gdb:
        raise click.UsageError("--boundary-fc requires --gdb (the clip happens "
                               "during the GDB write).")
    if gdb:
        _guard("draft-plume-boundary")

    qa = QACollector()
    if points_csv:
        points = load_exceedance_points_csv(Path(points_csv))
    else:
        points = filter_results_to_exceedance_points(
            Path(results_csv), Path(coords_csv), analyte=analyte, qa=qa)

    result = compute_draft_plume_boundary(
        points, hull_method=hull_method, k_neighbors=k_neighbors,
        site_id=site_id, analyte=analyte, qa=qa)

    if result is not None:
        click.echo(f"[DRAFT] {result.hull_method} hull, "
                   f"{len(result.hull_vertices)} vertices, "
                   f"{result.n_exceedance_points} exceedance point(s)")
        click.echo(f"[DRAFT] {result_to_wkt(result)}")
        geojson = _json.dumps(result_to_geojson(result), indent=2)
        if out_path:
            Path(out_path).write_text(geojson, encoding="utf-8")
            click.echo(f"GeoJSON written to {out_path}")
        else:
            click.echo(geojson)

        if gdb and not dry_run:
            written = write_plume_draft_to_gdb(gdb, site_id, result,
                                               boundary_fc=boundary_fc)
            if written:
                click.echo(f"Written to {gdb}/Env_PlumeBoundary_Draft (ReviewStatus=DRAFT)")
            else:
                click.echo(
                    f"WARNING: nothing written to {gdb}/Env_PlumeBoundary_Draft "
                    "-- the feature class is missing (run the GDB schema tool "
                    "first), --boundary-fc does not exist, or the hull does "
                    "not overlap it.")

    _render_qa(qa, report, fail_on)


@envmon.command("build-conc-surface")
@click.option("--results", "results_csv", required=True,
              type=click.Path(exists=True),
              help="AnalyticalResultRecord CSV (canonical-read applied here).")
@click.option("--coords", "coords_csv", required=True,
              type=click.Path(exists=True),
              help="location_id,x,y CSV.")
@click.option("--analyte", required=True,
              help="AnalyteCanonicalName — one surface per analyte "
                   "(ADR-0085 decision 5).")
@click.option("--site", "site_id", required=True, help="Site ID.")
@click.option("--event-date", required=True,
              help="Event date YYYY-MM-DD (raster naming + registry row).")
@click.option("--nondetect-rule",
              type=click.Choice(["exclude", "half_rl", "use_rl", "use_zero"]),
              default="exclude", show_default=True,
              help="Numeric substitution for nondetects (ADR-0085 "
                   "decision 4).")
@click.option("--unit", "surface_unit", default="ug/L", show_default=True,
              help="Declared surface unit (ADR-0022 registry); every "
                   "result/RL/DL is normalized into it, rows with unknown "
                   "or cross-dimension units are excluded with a warning.")
@click.option("--matrix", default=None,
              help="Optional Matrix filter (e.g. GW); rows outside it are "
                   "excluded.")
@click.option("--method", type=click.Choice(["IDW", "EBK"]), default="IDW",
              show_default=True,
              help="IDW needs Spatial Analyst; EBK needs Geostatistical "
                   "Analyst and also writes a standard-error raster.")
@click.option("--gdb", default=None, type=click.Path(),
              help="File geodatabase for the Draft_ raster(s) + "
                   "Env_SurfaceRegistry rows (ArcGIS Pro). Required unless "
                   "--dry-run.")
@click.option("--boundary-fc", default=None,
              help="Site-boundary polygon feature class: clip the surface "
                   "(requires --gdb).")
@click.option("--cell-size", type=float, default=None,
              help="Raster cell size (default: extent/250).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Collect and print the interpolation points headlessly; "
                   "no arcpy, no writes.")
@qa_report_options
def build_conc_surface_cmd(results_csv, coords_csv, analyte, site_id,
                           event_date, nondetect_rule, surface_unit, matrix,
                           method, gdb, boundary_fc, cell_size, dry_run,
                           report, fail_on):
    """BuildAnalyticalConcentrationSurface: DRAFT interpolated concentration
    raster for one analyte (Phase-5 slice 2, ADR-0085).

    Point collection (nondetect policy included) is headless; the
    interpolate/clip/write stage runs inside ArcGIS Pro only.
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.concentration_surface import (
        build_concentration_surface, collect_concentration_points,
    )

    if boundary_fc and not gdb:
        raise click.UsageError("--boundary-fc requires --gdb.")
    if not dry_run and not gdb:
        raise click.UsageError("Provide --gdb, or use --dry-run for the "
                               "headless point preview.")
    if gdb and not dry_run:
        _guard("build-conc-surface")

    qa = QACollector()
    points = collect_concentration_points(
        Path(results_csv), Path(coords_csv), site_id=site_id,
        event_date=event_date, analyte=analyte,
        nondetect_rule=nondetect_rule, surface_unit=surface_unit,
        matrix=matrix, qa=qa)
    click.echo(f"[DRAFT] {len(points)} interpolation point(s) for {analyte} "
               f"({surface_unit}, nondetect_rule={nondetect_rule})")
    if dry_run:
        for loc, x, y, v in points:
            click.echo(f"  {loc}: ({x}, {y}) = {v}")
    else:
        summary = build_concentration_surface(
            Path(gdb), site_id, event_date, analyte, points, qa,
            method=method, nondetect_rule=nondetect_rule,
            surface_unit=surface_unit,
            cell_size=cell_size, boundary_fc=boundary_fc)
        if summary["skipped"]:
            click.echo("WARNING: surface skipped — see QA report.")
        else:
            for rtype, name in summary["rasters"].items():
                click.echo(f"Written {gdb}/{name} ({rtype}, DRAFT)")

    _render_qa(qa, report, fail_on)


@envmon.command("build-cad-package")
@click.option("--layers", required=True, type=click.Path(exists=True),
              help="Text file listing selected GIS layers, one per line.")
@click.option("--mapping", required=True, type=click.Path(exists=True),
              help="YAML {gis_layer: {cad_layer, color, linetype}} mapping.")
@click.option("--crs", required=True, help="Output coordinate system, e.g. EPSG:2256.")
def build_cad_package_cmd(layers, mapping, crs):
    """Tool 8.9: export GIS layers to a CAD package (ArcGIS Pro)."""
    _guard("build-cad-package")
    from autogis.core.envmon import cad_layer_map  # noqa: F401
    raise click.ClickException(
        "build-cad-package runs inside ArcGIS Pro only. Use the "
        "BuildCADExportPackage tool in the .pyt toolbox."
    )


@envmon.command("export-civil3d")
@click.option("--points", "points_csv", required=True, type=click.Path(exists=True),
              help="CSV of elevation points: location_id,x,y,z[,description].")
@click.option("--crs", required=True, help="e.g. EPSG:2256; recorded in the projection note.")
@click.option("--out-dir", required=True, type=click.Path(),
              help="Directory for points_pnezd.csv + projection_note.txt.")
@click.option("--start-number", type=int, default=1, show_default=True,
              help="First PNEZD point number.")
@click.option("--landxml", is_flag=True, default=False,
              help="Also write points_pnezd.xml (LandXML CgPoints, headless). "
                   "Use the .pyt tool to export an existing Pro TIN surface.")
@click.option("--units", type=click.Choice(["foot", "USSurveyFoot", "meter"]),
              default=None,
              help="Linear unit of the point coordinates; required with "
                   "--landxml (written as the LandXML <Units> block so "
                   "Civil 3D imports without a unit-mismatch shift).")
@qa_report_options
def export_civil3d_cmd(points_csv, crs, out_dir, start_number, landxml, units,
                       report, fail_on):
    """Tool 8.2: PNEZD point CSV + projection note for Civil 3D (headless);
    --landxml adds a headless LandXML CgPoints export. Existing Pro TINs use
    the ExportContoursForCivil3D tool in the .pyt toolbox."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.civil3d_points import (
        build_pnezd, load_gwe_points_csv, write_pnezd_csv, write_pnezd_landxml,
        write_projection_note)

    # Validate --landxml prerequisites before writing anything, so a usage
    # error can't leave a partial package behind (issue #238).
    if landxml:
        if not units:
            raise click.UsageError(
                "--landxml requires --units (foot / USSurveyFoot / meter): "
                "Civil 3D shifts or scales imports whose LandXML units are "
                "missing and differ from the drawing's.")
        from autogis.core.common.landxml import parse_epsg
        if parse_epsg(crs) is None:
            raise click.UsageError(
                f"--landxml requires an EPSG-coded --crs (e.g. EPSG:2256): "
                f"{crs!r} cannot be written as a machine-readable "
                "<CoordinateSystem epsgCode>, so Civil 3D would silently "
                "fall back to the drawing's coordinate system.")

    qa = QACollector()
    records = load_gwe_points_csv(Path(points_csv))
    pts = build_pnezd(records, crs=crs, start_number=start_number, qa=qa)
    out = Path(out_dir)
    csv_path = write_pnezd_csv(pts, out / "points_pnezd.csv")
    note_path = write_projection_note(crs, out / "projection_note.txt")
    click.echo(f"{len(pts)} PNEZD point(s) -> {csv_path}")
    click.echo(f"Projection note -> {note_path}")
    if landxml:
        xml_path = write_pnezd_landxml(pts, out / "points_pnezd.xml",
                                       crs=crs, linear_unit=units)
        click.echo(f"LandXML CgPoints -> {xml_path}")
    _render_qa(qa, report, fail_on)


# Legacy single-command entry point kept as an alias.
main = autogis


if __name__ == "__main__":
    autogis()
