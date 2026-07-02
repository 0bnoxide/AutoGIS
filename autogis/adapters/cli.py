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


@envmon.command("well-inspection-report")
@click.option("--wells-csv", required=True, type=click.Path(exists=True),
              help="Wells CSV; must include a WellID column.")
@click.option("--site", "site_id", required=True, help="Site ID.")
@click.option("--output-dir", required=True, type=click.Path(),
              help="Directory to write one Markdown file per well + SiteSummary.md.")
@click.option("--maintenance-log-csv", default=None, type=click.Path(),
              help="Optional maintenance log CSV (WellID, InspectionDate, "
                   "Condition, Notes). Absent file -> no inspection history.")
@qa_report_options
def well_inspection_report_cmd(wells_csv, site_id, output_dir,
                               maintenance_log_csv, report, fail_on):
    """Generate Markdown well inspection reports + a site summary (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.well_inspection_report import build_well_inspection_reports

    qa = QACollector()
    written = build_well_inspection_reports(
        Path(wells_csv), Path(output_dir),
        site_id=site_id,
        maintenance_log_csv=Path(maintenance_log_csv) if maintenance_log_csv else None,
        qa=qa,
    )
    click.echo(f"Written {len(written)} Markdown file(s) to {output_dir}")
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
def build_callouts_cmd(site_config, figure_spec):
    """Tool 4: generate callout feature classes (ArcGIS Pro)."""
    _guard("build-callouts")
    from autogis.core.envmon import build_figure_dataset  # noqa: F401
    raise click.ClickException(
        "build-callouts runs inside ArcGIS Pro only. Use the BuildCallouts "
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
        _render_qa(result.qa, report, "warning")
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


@envmon.command("export-survey-cad")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--feature-code-map", "map_path", required=True, type=click.Path(exists=True),
              help="YAML feature-code -> layer-name mapping "
                   "(e.g. {MW: MonitoringWells, GCP: DroneControlPoints}).")
@click.option("--output-dir", required=True, type=click.Path(),
              help="Directory to write one CSV (+ manifest.json) per layer.")
@click.option("--geojson/--no-geojson", default=False,
              help="Also write a GeoJSON FeatureCollection per layer.")
@qa_report_options
def export_survey_cad_cmd(csv_path, map_path, output_dir, geojson, report, fail_on):
    """Export RTK survey points to feature-code-mapped CSV/GeoJSON layers (headless).

    CSV/GeoJSON only — DWG/DXF/LandXML CAD export is out of scope for this tool.
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
        write_geojson=geojson, qa=qa,
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


@envmon.command("batch-import-workbooks")
@click.option("--manifest", required=True, type=click.Path(exists=True),
              help="CSV with columns: workbook_path, profile_path, site_id.")
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
def batch_import_workbooks_cmd(manifest, output_dir, analytes, screening,
                               event_date, report, fail_on):
    """Tool 2.2: batch-import multiple EDD workbooks from a manifest CSV (headless)."""
    import yaml as _yaml
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import write_records_csv
    from autogis.core.envmon.batch_workbook_importer import (
        read_manifest_csv, run_batch_import, BatchManifestRow)

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
@click.option("--dry-run", is_flag=True, default=False,
              help="Compute and print the boundary without writing to --gdb.")
@qa_report_options
def draft_plume_boundary_cmd(results_csv, coords_csv, points_csv, site_id, analyte,
                             hull_method, k_neighbors, out_path, gdb, dry_run,
                             report, fail_on):
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
            write_plume_draft_to_gdb(gdb, site_id, result)
            click.echo(f"Written to {gdb}/Env_PlumeBoundary_Draft (ReviewStatus=DRAFT)")

    _render_qa(qa, report, fail_on)


# Legacy single-command entry point kept as an alias.
main = autogis


if __name__ == "__main__":
    autogis()
