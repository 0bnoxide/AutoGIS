import dataclasses
from pathlib import Path

import click
import yaml

from autogis.adapters.guard import require_runtime, RuntimeUnavailable
from autogis.core.common.config import HarvestConfig
from autogis.runtime.sessions import agol_from_profile


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
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
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
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
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
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
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
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
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
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.export_summary import export_analytical_summary

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    samples = (read_records_csv(Path(samples_csv), SampleRecord)
               if samples_csv else [])
    if not site_id and results:
        site_id = results[0].SiteID
    out = export_analytical_summary(samples, results, Path(output), site_id, event_id)
    click.echo(f"Written: {out}  ({len(results)} result(s))")


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
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
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
def validate_db_cmd(gdb):
    """Tool 8: validate the geodatabase schema/contents (ArcGIS Pro)."""
    _guard("validate-db")
    from autogis.core.envmon import validate_database  # noqa: F401
    raise click.ClickException(
        "validate-db runs inside ArcGIS Pro only. Use the ValidateDatabase "
        "tool in the .pyt toolbox."
    )


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
    _guard("LOCAL")
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


# Legacy single-command entry point kept as an alias.
main = autogis


if __name__ == "__main__":
    autogis()
