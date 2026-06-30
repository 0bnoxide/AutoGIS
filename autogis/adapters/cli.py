import dataclasses
from pathlib import Path

import click
import yaml

from autogis.adapters.guard import require_runtime, RuntimeUnavailable
from autogis.core.common.config import HarvestConfig
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
    func = click.option("--report", default=None, type=click.Path())(func)
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


@click.group()
def autogis():
    """AutoGIS suite — harvest + envmon tools."""


@autogis.command("harvest")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("--where", default=None)
@click.option("--out", default=None)
@click.option("--incremental/--no-incremental", default=None)
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
    """Tool: pre-flight check that workbook location IDs match the well layer."""
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
    from autogis.core.envmon.export_summary import export_analytical_summary

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    samples = (read_records_csv(Path(samples_csv), SampleRecord)
               if samples_csv else [])
    if not site_id and results:
        site_id = results[0].SiteID
    out = export_analytical_summary(samples, results, Path(output), site_id, event_id)
    click.echo(f"Written: {out}  ({len(results)} result(s))")


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
              help="Output Markdown (.md) file path.")
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
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def generate_event_report_cmd(
    site_id, event_id, output,
    results_csv, comparison_csv, history_csv, gaps_csv, rpd_qa_csv,
    report, fail_on,
):
    """Tool 10.5: assemble Markdown monitoring event report from CSV tool outputs."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.generate_event_report import generate_event_report

    qa = QACollector()
    content = generate_event_report(
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
@envmon.command("import-gdb")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("workbook", type=click.Path(exists=True))
def import_gdb_cmd(site_config, workbook):
    """Tool 2: import a workbook into the file geodatabase (ArcGIS Pro)."""
    _guard("import-gdb")
    from autogis.core.envmon import import_to_gdb  # noqa: F401  (arcpy path)
    raise click.ClickException(
        "import-gdb runs inside ArcGIS Pro only. Use the HarvestAttachments "
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
def build_callouts_cmd(site_config, figure_spec):
    """Tool 4: generate callout feature classes (ArcGIS Pro)."""
    _guard("build-callouts")
    from autogis.core.envmon import build_figure_dataset  # noqa: F401
    raise click.ClickException(
        "build-callouts runs inside ArcGIS Pro only. Use the BuildFigureDataset "
        "tool in the .pyt toolbox."
    )


@envmon.command("optimize-callouts")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("figure_spec", type=click.Path(exists=True))
def optimize_callouts_cmd(site_config, figure_spec):
    """Tool 5.2: run callout placement optimizer (ArcGIS Pro)."""
    _guard("optimize-callouts")
    raise click.ClickException(
        "optimize-callouts runs inside ArcGIS Pro only. "
        "Use the OptimizeCalloutPlacement tool in the .pyt toolbox."
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
def manage_overrides_list_cmd(gdb, site, spec):
    """List all placement overrides for a site/figure spec."""
    _guard("manage-callout-overrides")
    raise click.ClickException(
        "manage-callout-overrides runs inside ArcGIS Pro only. "
        "Use the ManageCalloutPlacementOverrides tool in the .pyt toolbox."
    )


@manage_callout_overrides_group.command("clear")
@_OV_GDB
@_OV_SITE
@_OV_SPEC
def manage_overrides_clear_cmd(gdb, site, spec):
    """Delete all unlocked overrides for a site/figure spec."""
    _guard("manage-callout-overrides")
    raise click.ClickException(
        "manage-callout-overrides runs inside ArcGIS Pro only. "
        "Use the ManageCalloutPlacementOverrides tool in the .pyt toolbox."
    )


@manage_callout_overrides_group.command("lock")
@_OV_GDB
@_OV_SITE
@_OV_SPEC
@click.option("--location", required=True, help="LocationID to lock.")
@click.option("--anchor-x", type=float, required=True,
              help="Box lower-left X in map units.")
@click.option("--anchor-y", type=float, required=True,
              help="Box lower-left Y in map units.")
@click.option("--map-type", default="", help="MapType filter (default: all).")
def manage_overrides_lock_cmd(gdb, site, spec, location,
                               anchor_x, anchor_y, map_type):
    """Lock a callout to a fixed position."""
    _guard("manage-callout-overrides")
    raise click.ClickException(
        "manage-callout-overrides runs inside ArcGIS Pro only. "
        "Use the ManageCalloutPlacementOverrides tool in the .pyt toolbox."
    )


@manage_callout_overrides_group.command("unlock")
@_OV_GDB
@_OV_SITE
@_OV_SPEC
@click.option("--location", required=True, help="LocationID to unlock.")
def manage_overrides_unlock_cmd(gdb, site, spec, location):
    """Remove the lock on a callout (override becomes a quadrant hint)."""
    _guard("manage-callout-overrides")
    raise click.ClickException(
        "manage-callout-overrides runs inside ArcGIS Pro only. "
        "Use the ManageCalloutPlacementOverrides tool in the .pyt toolbox."
    )


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
def import_edd_cmd(edd_path, profile_path, site_id, gdb_path,
                   analytes, screening, event_date):
    """Tool 2.3: import a lab EDD CSV/XLSX into the envmon GDB (needs ArcGIS Pro)."""
    _guard("import-edd")
    from autogis.core.envmon.edd_profile import LabEDDProfile
    from autogis.core.envmon.edd_importer import run_edd_import
    from autogis.core.common.config import load_config

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

    batch_id = run_edd_import(
        edd_path=Path(edd_path),
        profile=profile,
        gdb_path=Path(gdb_path),
        site_id=site_id,
        analyte_dictionary=analyte_dictionary,
        screening_levels=screening_levels,
        event_date_override=override,
    )
    click.echo(f"Import complete. Batch ID: {batch_id}")


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


@autogis.group()
def agol():
    """AGOL / cloud tools."""


@agol.command("publish-layer")
@click.option("--profile", default=None, help="ArcGIS API for Python profile name")
@click.option("--title", required=True, help="Hosted service title")
@click.option("--source", required=True, type=click.Path(exists=True),
              help="Zip of FGDB or JSON FeatureSet to publish")
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


@envmon.command("validate-rtk-survey")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True)
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="warning")
def validate_rtk_survey_cmd(csv_path, hrms_threshold, vrms_threshold, report, fail_on):
    """Validate an RTK survey CSV for precision and fix-type QA (headless)."""
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv
    from autogis.core.envmon.validate_rtk_survey import validate_rtk_points
    points = parse_rtk_csv(Path(csv_path))
    qa = validate_rtk_points(points, hrms_threshold, vrms_threshold)
    _render_qa(qa, report, fail_on)


@envmon.command("import-rtk-survey")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--gdb", required=True, type=click.Path())
@click.option("--batch-id", default=None)
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True)
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True)
def import_rtk_survey_cmd(csv_path, site_id, gdb, batch_id, hrms_threshold, vrms_threshold):
    """Import RTK survey CSV into SurveyPoints_Raw/QA (ArcGIS Pro)."""
    import uuid
    _guard("import-rtk-survey")
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv, import_rtk_survey, assign_qa_flags
    bid = batch_id or f"RTK-{uuid.uuid4().hex[:8].upper()}"
    points = parse_rtk_csv(Path(csv_path))
    import_rtk_survey(gdb, site_id, bid, points, hrms_threshold, vrms_threshold)
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
@click.option("--site-id", required=True, help="Site identifier for logging.")
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


@envmon.command("reconcile-survey123-lab")
@click.option("--survey", "survey_csv", required=True, type=click.Path(exists=True),
              help="Survey123 export CSV.")
@click.option("--edd", "edd_path", required=True, type=click.Path(exists=True),
              help="Lab EDD CSV or XLSX.")
@click.option("--edd-profile", "profile_path", required=True, type=click.Path(exists=True),
              help="Lab EDD profile YAML.")
@click.option("--site", "site_id", required=True)
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
@click.option("--report", default=None, type=click.Path())
def merge_event_results_cmd(result_paths, results_dir, event_labels,
                             out, manifest_path, no_dedup, report):
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
    _render_qa(result.qa, report, "warning")


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
@click.option("--report", default=None, type=click.Path())
def build_dashboard_data_mart_cmd(gdb, site_id, event_id, prior_event_id, report):
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
              type=click.Choice(["stable", "draft", "planned"], case_sensitive=False))
@click.option("--search", default=None)
@click.option("--verbose", is_flag=True, default=False)
def list_tools_cmd(runtime_filter, domain, status, search, verbose):
    """List available envmon tools with capability metadata (headless)."""
    from autogis.core.envmon.tool_registry import (
        get_all_tools, filter_tools, format_tool_table)

    entries = filter_tools(get_all_tools(), runtime=runtime_filter,
                           domain=domain, status=status, search=search)
    if not entries:
        click.echo("No tools match the given filters.")
        return
    click.echo(format_tool_table(entries, verbose=verbose))
    click.echo(f"\n{len(entries)} tool(s).")


# Legacy single-command entry point kept as an alias.
main = autogis


if __name__ == "__main__":
    autogis()
