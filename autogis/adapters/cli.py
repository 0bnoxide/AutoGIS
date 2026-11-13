Warning: truncated output (original token count: 86550)
Total output lines: 7157

import contextlib
import dataclasses
import json
import math
import os
import stat
import sys
import uuid
from datetime import datetime as _dt
from pathlib import Path

import click
import yaml

from autogis.adapters.guard import require_runtime, RuntimeUnavailable
from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice
from autogis.core.common.config import HarvestConfig, _unique_key_loader, load_config
from autogis.core.common.config_validation import KNOWN_MATRICES
from autogis.core.common.units import UNIT_REGISTRY
from autogis.core.envmon.import_rtk_survey import _EXTRA_COLUMN_VOCAB
from autogis.core.envmon.opentopo import DEFAULT_DATASET, DEM_DATASETS
from autogis.core.envmon.soil_interval_selector import IntervalTier
from autogis.core.envmon.synthetic_workbook import MESSINESS
from autogis.runtime.capabilities import RUNTIME_CLASSES, TOOL_REGISTRY
from autogis.runtime.sessions import agol_from_profile, list_connection_profiles


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


# ponytail: profile names snapshotted once at import. A CLI run is a fresh
# process so it's always current; the long-running GUI won't see a profile
# added mid-session until restart -- acceptable for a rarely-changing store.
# ``None`` when the box has no profile store, so the option stays plain text
# rather than an empty dropdown (keeps introspect's "choice fields carry
# choices" guard intact).
_CONNECTION_PROFILE_TYPE = (SuggestedChoice(_names) if (_names := list_connection_profiles())
                            else None)


def connection_profile_option(func):
    """Attach the shared AGOL ``--profile`` option (an ArcGIS API for Python
    connection profile) to a command.

    One home for the connection-profile contract: ``default=None`` (anonymous
    ``GIS`` when omitted) plus a ``SuggestedChoice`` of the locally-registered
    profile names, so the GUI renders an editable dropdown while the CLI still
    accepts any typed name. With no profiles registered the type is ``None``
    (plain text) -- a headless box may have no profile store at all.
    """
    return click.option(
        "--profile", default=None, type=_CONNECTION_PROFILE_TYPE,
        help="ArcGIS API for Python profile name.",
    )(func)


def _reject_report_path_in_artifact(report, artifact_dir) -> None:
    """Reject QA report paths that alias files inside an artifact directory."""
    if not report:
        return
    from autogis.core.envmon.report_figure_package import _is_link_or_reparse

    artifact_path = Path(artifact_dir).resolve(strict=False)
    report_path = Path(report).resolve(strict=False)
    if ":" in report_path.name:
        raise click.ClickException(
            "--report must not name an alternate data stream")
    conflicts = report_path.is_relative_to(artifact_path)
    if report_path.exists() and artifact_path.is_dir() and not conflicts:
        for current, dirnames, filenames in os.walk(
                artifact_path, followlinks=False):
            current_path = Path(current)
            for name in list(dirnames):
                try:
                    redirects = _is_link_or_reparse(current_path / name)
                except ValueError:
                    redirects = True
                if redirects:
                    dirnames.remove(name)
            for name in filenames:
                try:
                    conflicts = report_path.samefile(current_path / name)
                except OSError:
                    continue
                if conflicts:
                    break
            if conflicts:
                break
    if conflicts:
        raise click.ClickException(
            "--report must be outside the package directory")


def _reject_msl_report_collision(report, out_path, aoi, cache_dir):
    """Keep the optional QA report separate from DEM artifacts and inputs."""
    if not report:
        return
    target = Path(report).resolve(strict=False)
    out = Path(out_path).absolute()
    protected = [out, Path(str(out) + ".json")]
    if aoi:
        source = Path(aoi).absolute()
        protected.append(source)
        if source.suffix.lower() == ".shp":
            from glob import escape
            protected.extend(source.parent.glob(escape(source.stem) + ".*"))
    for path in protected:
        if (str(target).casefold() == str(path.resolve(strict=False)).casefold()
                or (target.exists() and path.exists() and target.samefile(path))):
            raise click.ClickException(
                "--report must not overwrite the DEM, provenance or AOI input")
    cache = Path(cache_dir) if cache_dir else Path(out_path).absolute().parent / ".msl-cache"
    _reject_report_path_in_artifact(report, cache)


def _read_yaml(path):
    """Load CLI YAML safely; report malformed, duplicate-key or unreadable input cleanly."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        return yaml.load(text, Loader=_unique_key_loader(yaml))  # noqa: S506 - SafeLoader subclass
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise click.ClickException(f"cannot read {path}: {exc}") from None


def run(config_path, where, out, incremental, *, harvest_fn=None):
    if harvest_fn is None:
        from autogis.core.harvest.harvester import harvest as harvest_fn

    raw = _read_yaml(config_path)
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
# Commands that self-log a richer RunRecord than the auto-recorder's empty
# outputs={}: `agol promote` (rows_copied etc. via promote.py's _log_promotion)
# and `event-status` (state counts + status='success' regardless of its semantic
# nonzero exit code, so a stale-finding read isn't mislogged as an error).
# `coc` uses its per-transition custody audit instead of run history (ADR-0107).
_SELF_LOGGING_COMMANDS = {"promote", "event-status", "coc"}
# Semantic nonzero exits that are findings, not failures (ADR-0115):
# diff-survey-schema exits 2 (review-required) / 3 (destructive drift).
# Without this, every drift finding would be mislogged as a tool error.
# reconcile-event exits 2 for a non-clean (residual/needs_review) event --
# also a finding, not a failure (not self-logging like `coc`, so it needs
# an explicit entry here or every discrepancy run-history record would be
# mislogged as status='error').
_SEMANTIC_EXIT_CODES = {"diff-survey-schema": {2, 3}, "reconcile-event": {2},
                        "trace-survey123": {2}}


def _record_tool_name(ctx) -> str:
    """Return the registry-level command name for a Click leaf context."""
    names = []
    current = ctx
    while current.parent is not None:
        if current.info_name:
            names.append(current.info_name)
        current = current.parent
    names.reverse()
    if names:
        return names[1] if len(names) > 1 else names[0]
    # No parent context: the command was invoked as its own console script
    # (the `autogis-harvest` legacy alias). ctx.info_name would be the script
    # name; the registry name is the command's own.
    return getattr(ctx.command, "name", "") or ""


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
        if exc.code == 130:      # 128 + SIGINT: a Ctrl-C cancellation
            return "cancelled"
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
            if (isinstance(exc, SystemExit)
                    and exc.code in _SEMANTIC_EXIT_CODES.get(tool_name, ())):
                status = "success"
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

    def main(self, *args, **kwargs):
        # Configure before Click parses arguments: eager --help output can
        # contain Unicode too. A stock Windows/redirected cp1252 stream cannot
        # encode characters such as → and would otherwise abort mid-command.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError, ValueError):
                pass
        return super().main(*args, **kwargs)


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


@autogis.command("handoff")
@click.option("--input", "input_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Source LandXML file containing the TIN surface.")
@click.option("--output", "output_path", required=True,
              type=click.Path(dir_okay=False),
              help="Contract-v1 package ZIP to write.")
@click.option("--surface-name", default="",
              help="Surface to package when the source declares several; "
                   "default is the first surface.")
@click.option("--vertical-unit", required=True,
              type=click.Choice(
                  ["metre", "international_foot", "us_survey_foot"]),
              help="Manifest vertical unit; always explicit, checked "
                   "against the surface's elevation-unit family "
                   "(ADR-0128, never inferred).")
@click.option("--vertical-datum-authority", default=None,
              help="Vertical datum authority; with code and name this "
                   "declares a known datum.")
@click.option("--vertical-datum-code", type=int, default=None,
              help="Vertical datum authority code (positive integer).")
@click.option("--vertical-datum-name", default=None,
              help="Vertical datum name, e.g. 'NAVD88 height'.")
@click.option("--vertical-datum-note", default=None,
              help="Optional note recorded with an unknown datum only.")
@click.option("--source-commit", default=None,
              help="Producing commit (7-64 lowercase hex), recorded "
                   "verbatim in the manifest.")
@click.option("--overwrite", is_flag=True, default=False,
              help="Replace an existing output package.")
def handoff_cmd(input_path, output_path, surface_name, vertical_unit,
                vertical_datum_authority, vertical_datum_code,
                vertical_datum_name, vertical_datum_note, source_commit,
                overwrite):
    """Emit a contract-v1 Civil 3D handoff package ZIP (ADR-0128)."""
    from autogis.core.handoff import build_handoff_package
    try:
        manifest = build_handoff_package(
            input_path, output_path,
            vertical_unit=vertical_unit,
            surface_name=surface_name,
            datum_authority=vertical_datum_authority,
            datum_code=vertical_datum_code,
            datum_name=vertical_datum_name,
            datum_note=vertical_datum_note,
            source_commit=source_commit,
            overwrite=overwrite)
    except (ValueError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc
    surface = manifest["surface"]
    datum = manifest["coordinate_reference"]["vertical"]["datum"]
    click.echo(
        f"handoff package -> {output_path} "
        f"({surface['point_count']} points, {surface['face_count']} faces, "
        f"datum {datum['status']})")


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
@click.option("--scan-rows", type=click.IntRange(min=0), default=40)
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
    from autogis.core.common.config import ConfigError, ParserProfile
    from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader

    try:
        parser = ParserProfile.load(Path(profile))
    except ConfigError as exc:
        raise click.ClickException(str(exc))
    try:
        reader = ProfileWorkbookReader(Path(workbook), parser)
    except Exception as exc:  # the reader's own open guard is this broad too
        raise click.ClickException(f"cannot open workbook {workbook}: {exc}")
    click.echo(f"Profile '{parser.profile_id}' opened against "
               f"{len(reader.sheet_names())} sheet(s).")


@envmon.command("figure-spec")
@click.argument("spec", type=click.Path(exists=True))
def figure_spec_cmd(spec):
    """Tool 10: load and validate a figure spec (headless)."""
    from autogis.core.common.config import FigureSpec

    fs = FigureSpec.load(Path(spec))
    click.echo(f"Figure spec '{fs.figure_spec_id}' loaded.")


def _validate_site_id(ctx, param, value):
    # Delegate to the core guard (single source of truth); it also protects
    # library callers of plan_site_skeleton.
    from autogis.core.envmon.init_site import check_site_id
    try:
        check_site_id(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc))
    return value


def _validate_site_name(ctx, param, value):
    from autogis.core.envmon.init_site import check_site_name
    try:
        check_site_name(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc))
    return value


@envmon.command("init-site")
@click.option("--site-id", required=True, callback=_validate_site_id,
              help="Site identifier, e.g. H281 (letters/digits, '-' and '_' only).")
@click.option("--site-name", required=True, callback=_validate_site_name,
              help="Human-readable site name (no double-quotes or backslashes).")
@click.option("--dest", type=click.Path(file_okay=False), default=None,
              help="Config root to write under (default: the packaged autogis/config).")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite existing target files (default: refuse).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Render, validate and report without writing any file.")
def init_site_cmd(site_id, site_name, dest, force, dry_run):
    """Phase 3: scaffold a new site's config skeleton from versioned templates.

    Renders the site / event / parser / figure config-family skeletons with the
    site identity substituted, guards existing files against overwrite, lists
    every _TODO anchor to complete, and runs the existing loaders as structural
    validators. Headless (arcpy-free).
    """
    import autogis
    from autogis.core.envmon.init_site import (
        plan_site_skeleton, regulatory_gaps, scan_anchors, validate_skeleton,
        write_skeleton)

    config_root = (Path(dest) if dest
                   else Path(autogis.__file__).resolve().parent / "config")
    files = plan_site_skeleton(site_id, site_name, config_root)
    validation = validate_skeleton(files)   # validates rendered text; dry-run safe

    blocked = []
    if dry_run:
        click.echo(f"[dry-run] would scaffold {len(files)} file(s) under {config_root}:")
        for sf in files:
            click.echo(f"  ({sf.family}) {sf.target}")
    else:
        written, blocked = write_skeleton(files, force=force)
        for p in written:
            click.echo(f"wrote {p}")
        for p in blocked:
            click.echo(f"[ERROR] exists, not overwritten (use --force): {p}")

    for family, ok, msg in validation:
        click.echo(f"validate {family}: {'OK' if ok else 'FAIL — ' + msg}")

    click.echo("Anchors to complete before production use:")
    total = 0
    for sf in files:
        for line_no, line in scan_anchors(sf.text):
            total += 1
            click.echo(f"  {sf.target.name}:{line_no}: {line}")
    click.echo(f"{total} _TODO anchor(s) across {len(files)} file(s).")

    gaps = regulatory_gaps()
    if gaps:
        click.echo("Regulatory content to configure (NOT scaffolded):")
        for g in gaps:
            click.echo(f"  - {g}")

    if blocked or any(not ok for _, ok, _ in validation):
        raise SystemExit(1)


@envmon.command("validate-recipe")
@click.argument("recipe", type=click.Path(exists=True, dir_okay=False))
def validate_recipe_cmd(recipe):
    """Phase 5: validate a saved linear workflow-recipe YAML (headless).

    Checks the recipe structure (name, ordered steps, each step's command /
    values / fail_on / pause_on_warning / message). The GUI workflow builder
    saves/loads this format; a recipe can also be hand-authored and checked here.
    """
    from autogis.core.common.config import ConfigError
    from autogis.core.common.workflow_recipe import load_recipe
    try:
        data = load_recipe(Path(recipe))
    except ConfigError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Recipe '{data['name']}' OK — {len(data['steps'])} step(s).")


@envmon.command("run-recipe")
@click.argument("recipe", type=click.Path(exists=True, dir_okay=False))
@click.option("--job-root", type=click.Path(file_okay=False), default=None,
              help="Directory for per-step outputs (default: a fresh temp dir).")
@click.option("--local-python", type=click.Path(), default=None,
              help="Python interpreter for LOCAL (arcpy) steps.")
@click.option("--timeout", type=click.FloatRange(min=0), default=None,
              help="Per-step timeout in seconds.")
@click.option("--continue-through-review", is_flag=True, default=False,
              help="Auto-resume past review checkpoints instead of stopping.")
def run_recipe_cmd(recipe, job_root, local_python, timeout,
                   continue_through_review):
    """Phase 5: run a saved workflow recipe headlessly, one step at a time.

    Loads/validates the recipe, then drives each step through the shared
    WorkflowRunner, reporting each decision. Stops at a review checkpoint unless
    --continue-through-review is given. Exit code: 0 done, 1 halted/errored,
    2 paused-for-review, 130 cancelled.
    """
    import subprocess
    import tempfile

    from autogis.adapters.gui.runner import RunState, WorkflowRunner
    from autogis.adapters.recipe_workflow import recipe_to_workflow
    from autogis.core.common.config import ConfigError
    from autogis.core.common.workflow_recipe import load_recipe

    try:
        workflow = recipe_to_workflow(load_recipe(Path(recipe)))
    except ConfigError as exc:
        raise click.ClickException(str(exc))

    root = (Path(job_root) if job_root
            else Path(tempfile.mkdtemp(prefix="autogis_recipe_")))
    runner = WorkflowRunner(workflow, root, local_python=local_python,
                            timeout=timeout)
    click.echo(f"Running recipe '{workflow.name}' "
               f"({len(workflow.steps)} step(s)) under {root}")

    terminal = {RunState.DONE, RunState.HALTED, RunState.CANCELLED}
    try:
        while runner.status not in terminal:
            if runner.status is RunState.PAUSED:
                if continue_through_review:
                    runner.resume()
                    continue
                break
            try:
                result = runner.advance()
            except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
                # run_step failed (timeout / missing local_python / bad command);
                # the runner is already HALTED. Report and stop.
                click.echo(f"[step {len(runner.results)}] ERROR: {exc}")
                break
            n = len(runner.results) - 1
            click.echo(f"[step {n}] {result.decision.value}: {result.reason}"
                       + (f" (exit {result.exit_code})"
                          if result.exit_code is not None else ""))
    except KeyboardInterrupt:
        # Ctrl-C during a step: the runner already left the step (HALTED). Report
        # the standard cancellation exit code rather than Click's Abort (exit 1).
        click.echo("Interrupted.")
        raise SystemExit(130)

    status = runner.status
    click.echo(f"Final: {status.value}")
    code = {RunState.DONE: 0, RunState.HALTED: 1, RunState.PAUSED: 2,
            RunState.CANCELLED: 130}.get(status, 1)
    if code:
        raise SystemExit(code)


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
    from autogis.core.common.config import ConfigError
    from autogis.core.envmon.manage_analyte_dict import (
        check_analyte_dictionary, list_analytes)

    if do_list:
        try:
            rows = list_analytes(Path(analytes))
        except ConfigError as exc:
            raise click.ClickException(str(exc))
        header = f"{'display':>7}  {'canonical':<24} {'abbr':<8} {'group':<14} aliases"
        click.echo(header)
        for row in rows:
            click.echo(f"{row['display_order']:>7}  {row['canonical']:<24} "
                       f"{row['abbreviation']:<8} {row['analytical_group']:<14} "
                       f"{row['alias_count']}")
        if not do_check:
            return
    # Default to check when --list was not requested, or when both given.
    try:
        qa = check_analyte_dictionary(Path(analytes))
    except ConfigError as exc:
        raise click.ClickException(str(exc))
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
@click.option("--threshold", type=click.FloatRange(min=0.0, max=1.0),
              default=0.8, show_default=True)
@qa_report_options
def reconcile_locations_cmd(site_config, workbook, profile_path, wells_csv, gdb,
                            threshold, report, fail_on):
    """Tool: pre-flight check that workbook location IDs match the well layer.

    SITE_CONFIG is not read by the headless (--wells-csv) check itself: it
    supplies run-history site identity (ADR-0076), and the .pyt twin reads it
    for the GDB well layer.
    """
    from autogis.core.common.config import ConfigError, ParserProfile
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

    try:
        profile = ParserProfile.load(Path(profile_path))
    except ConfigError as exc:
        raise click.ClickException(str(exc))
    try:
        reader = ProfileWorkbookReader(Path(workbook), profile)
    except Exception as exc:  # the reader's own open guard is this broad too
        raise click.ClickException(f"cannot open workbook {workbook}: {exc}")
    workbook_ids = extract_location_ids(reader, profile)
    try:
        well_ids = read_well_ids_csv(Path(wells_csv))
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(f"cannot read {wells_csv}: {exc}")

    result = reconcile(workbook_ids, well_ids, threshold=threshold)
    qa = reconcile_to_qa(result)
    # expected_sheet_missing lives on the reader's QA; dropping it let a
    # workbook without the profile's sheets report PASS.
    qa.records = reader.qa.records + qa.records
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
              help="CSV export of Env_Samples (optional; adds a 'Samples' sheet).")
@click.option("--output", required=True, type=click.Path(),
              help="Output .xlsx path.")
@click.option("--site-id", default="", help="Site ID label added to a 'Metadata' sheet.")
@click.option("--event-id", default="", help="Event ID label added to a 'Metadata' sheet.")
def export_summary_cmd(results_csv, samples_csv, output, site_id, event_id):
    """Tool: export Env_AnalyticalResults to an Excel summary workbook."""
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
              type=SuggestedChoice(sorted(t.command for t in TOOL_REGISTRY)),
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
              type=SuggestedChoice(sorted(t.command for t in TOOL_REGISTRY)),
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
@click.option("--current-event-date", default=None, type=IsoDate(),
              help="ISO date (YYYY-MM-DD) to force as the current event.")
@click.option("--stable-threshold", default=10.0, type=click.FloatRange(min=0),
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
@click.option("--survey-date", required=True, type=IsoDate(),
              help="ISO date YYYY-MM-DD.")
@click.option("--benchmark-id", required=True, help="point_id of the benchmark.")
@click.option("--known-elevation", required=True, type=float)
@click.option("--tolerance", default=None, type=click.FloatRange(min=0),
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
@click.option("--event-date", required=True, type=IsoDate(),
              help="ISO date YYYY-MM-DD.")
@click.option("--toc-csv", default=None, type=click.Path(exists=True),
              help="Optional CSV with location_id,toc_elevation columns.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def gw_level_summary_cmd(elevations_csv, output, event_date, toc_csv,
                         report, fail_on):
    """Per-well GW level/DTW/trend summary from elevation history."""
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
        with Path(toc_csv).open(newline="", encoding="utf-8-sig") as fh:
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


def _read_csv_rows(path) -> list:
    """Read a CSV input as DictReader rows. ``click.Path(exists=True)``
    admits a directory, and a non-UTF-8 file is a usage mistake -- report
    both as a ClickException, not a raw traceback (#573)."""
    import csv
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(f"cannot read {path}: {exc}")


def _read_id_list(path) -> set:
    """One id per line; blanks and '#' comments ignored."""
    if not path:
        return set()
    out = set()
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return out


@envmon.command("build-gwe-event")
@click.option("--water-levels", required=True, type=click.Path(exists=True),
              help="CSV of water-level rows (location_id,gwe_ft,dtw_ft,status,...).")
@click.option("--event-date", required=True, type=IsoDate(),
              help="ISO date YYYY-MM-DD.")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output EnvWaterLevelEvent CSV path.")
@click.option("--exclude", default=None, type=click.Path(exists=True),
              help="Text file of location_ids to exclude from contouring.")
@click.option("--perched", default=None, type=click.Path(exists=True),
              help="Text file of perched/separate-zone location_ids.")
@click.option("--anomaly-stdev", default=3.0, type=click.FloatRange(min=0),
              help="Robust outlier threshold (modified z-score; default 3.0).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def build_gwe_event_cmd(water_levels, event_date, out_path, exclude, perched,
                        anomaly_stdev, report, fail_on):
    """Tool 4.1: build the per-event GW-elevation contour layer with exclusion flags."""
    from autogis.core.envmon.build_gwe_event import (
        build_gwe_event, write_gwe_event)

    rows = _read_csv_rows(water_levels)
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
@click.option("--wells", default=10, type=click.IntRange(min=0), help="Number of wells.")
@click.option("--events", default=4, type=click.IntRange(min=0), help="Number of events.")
@click.option("--features", default="", type=CommaList(MESSINESS),
              help="Comma-separated messiness features (e.g. 'nondetects,rpd_sheet').")
@click.option("--seed", default=0, type=int, help="Deterministic seed.")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output .xlsx path.")
def gen_synthetic_workbook_cmd(site_id, wells, events, features, seed, out_path):
    """Tool 10.6: write a seeded synthetic environmental workbook for parser hardening."""
    from autogis.core.envmon.synthetic_workbook import (
        MESSINESS, generate_workbook, WorkbookScenario)

    feats = {f.strip() for f in features.split(",") if f.strip()}
    scenario = WorkbookScenario(site_id=site_id, n_wells=wells, n_events=events,
                                features=feats, seed=seed)
    try:
        out = generate_workbook(scenario, Path(out_path))
    except ValueError as exc:
        raise click.BadParameter(
            f"{exc}; valid: {', '.join(sorted(MESSINESS))}",
            param_hint="--features")
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
        ConfigError, load_analyte_dictionary, load_screening_levels)
    from autogis.core.envmon.build_analytical_key import (
        build_analytical_key, format_key_markdown, write_key_csv, write_key_xlsx)

    try:
        analytes = load_analyte_dictionary(Path(analyte_dict))
        screening = load_screening_levels(Path(screening_levels))
        flt = ([s.strip() for s in analyte_filter.split(",") if s.strip()]
               if analyte_filter else None)
        rows = build_analytical_key(analytes, screening, matrix=matrix,
                                    analyte_filter=flt)
    except ConfigError as exc:
        raise click.ClickException(str(exc))
    if not out_path:
        click.echo(format_key_markdown(rows, matrix=matrix, site_id=site_id))
        return
    target = Path(out_path).resolve(strict=False)
    for src in (analyte_dict, screening_levels):
        if (str(target).casefold() == str(Path(src).resolve()).casefold()
                or (target.exists() and target.samefile(src))):
            raise click.ClickException(
                f"--out must not overwrite an input file: {src}")
    suffix = Path(out_path).suffix.lower()
    try:
        if suffix == ".csv":
            write_key_csv(rows, Path(out_path))
        elif suffix == ".xlsx":
            write_key_xlsx(rows, Path(out_path), matrix=matrix)
        else:
            Path(out_path).write_text(
                format_key_markdown(rows, matrix=matrix, site_id=site_id),
                encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"cannot write {out_path}: {exc}")
    click.echo(f"Written: {out_path}  ({len(rows)} analytes, matrix={matrix})")


@envmon.command("identify-data-gaps")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--schedule", required=True, type=click.Path(exists=True),
              help="Expected-schedule YAML (wells + required_analytes).")
@click.option("--output", required=True, type=click.Path(),
              help="Output data-gap CSV path.")
@click.option("--event-date", default=None, type=IsoDate(),
              help="ISO date YYYY-MM-DD.")
@click.option("--event-window-days", default=30, type=click.IntRange(min=0))
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
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.data_gaps import identify_data_gaps, DataGapRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    sched = _read_yaml(schedule)
    dry: dict = {}
    if dry_wells:
        with Path(dry_wells).open(newline="", encoding="utf-8-sig") as fh:
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
    """Per-location per-analyte history summary across events."""
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
    """Validate monitoring schedule YAML structure and analyte names."""
    import csv as _csv
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.validate_schedule import validate_schedule

    schedule = _read_yaml(schedule_path)
    adict = None
    if analyte_dict:
        with Path(analyte_dict).open(newline="", encoding="utf-8-sig") as fh:
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
@click.option("--site", "site_id", default="",
              help="Site ID stamped on the run-history record so event-status "
                   "can find this screening-evaluation run (without it the record "
                   "carries no site and the checker never matches it).")
@click.option("--event", "event_id", default="",
              help="Event ID label for event-status scoping. Matched verbatim "
                   "against `event-status --event-id`.")
@qa_report_options
def apply_screening_cmd(results_csv, screening_path, output, site_id, event_id,
                        report, fail_on):
    """Re-evaluate ExceedsScreeningLevel on result records (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import read_records_csv, write_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.apply_screening import apply_screening_levels

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    screening = _read_yaml(screening_path)
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
@click.option("--event-date", default=None, type=IsoDate(),
              help="Event date ISO (YYYY-MM-DD); inferred from results if omitted.")
@click.option("--window-days", type=click.IntRange(min=0), default=30, show_default=True,
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
       …53550 tokens truncated…ick.option("--report", default=None, type=click.Path())
def export_geopackage_cmd(wells_path, results_path, wl_path, out,
                           overwrite, report):
    """Export envmon data to OGC GeoPackage (stdlib sqlite3, headless)."""
    from autogis.core.envmon.geopackage_exporter import export_env_data_geopackage

    wells = _read_csv_rows(wells_path)
    results = _read_csv_rows(results_path)
    wl_rows = None
    if wl_path:
        wl_rows = _read_csv_rows(wl_path)
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
@click.option("--top-n", type=click.IntRange(min=0), default=5, show_default=True)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def generate_site_narrative_cmd(site_id, event_label, max_results_path,
                                 change_log_path, plan_path, results_path,
                                 sl_path, top_n, out, report):
    """Generate template-driven site monitoring narrative (headless)."""
    from autogis.core.envmon.site_narrative_generator import generate_site_narrative
    from autogis.core.common.config import ConfigError, load_flat_screening_levels

    try:
        sl = load_flat_screening_levels(Path(sl_path)) if sl_path else None
    except ConfigError as exc:
        raise click.ClickException(str(exc))
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
@click.option("--out-dir", required=True, type=click.Path(file_okay=False))
@click.option("--site", "site_id", default="")
@click.option("--event-label", default="")
@click.option("--report", default=None, type=click.Path())
def build_report_package_cmd(spec_path, out_dir, site_id, event_label, report):
    """Assemble deliverable folder from YAML spec (headless)."""
    from autogis.core.envmon.report_figure_package import (
        load_deliverable_spec, assemble_figure_package)
    from autogis.core.common.qa import QACollector

    _reject_report_path_in_artifact(report, out_dir)
    entries = load_deliverable_spec(Path(spec_path))
    qa = QACollector()
    try:
        result = assemble_figure_package(
            entries, Path(out_dir), site_id=site_id,
            event_label=event_label, qa=qa)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Copied: {result.copied_count}  Missing: {result.missing_count}  "
               f"Out: {out_dir}")
    _render_qa(qa, report, "warning")


@envmon.command("verify-report-package")
@click.argument("package_dir", type=click.Path(exists=True, file_okay=False))
@qa_report_options
def verify_report_package_cmd(package_dir, report, fail_on):
    """Verify a report package against its manifest and SHA-256 hashes."""
    from autogis.core.envmon.report_package_verifier import verify_report_package

    package_path = Path(package_dir)
    _reject_report_path_in_artifact(report, package_path)
    result = verify_report_package(package_path)
    click.echo(
        f"Manifest: {result.manifest_count}  Expected: {result.expected_count}  "
        f"Verified: {result.verified_count}  Extra: {result.extra_count}")
    _render_qa(result.qa, report, fail_on)


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
    from autogis.core.envmon.lab_request_exporter import (
        build_lab_request_rows, write_lab_request_workbook, write_lab_request_csv)

    plan = _read_csv_rows(plan_path)
    groups = _read_yaml(groups_path)
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
    from autogis.core.envmon.report_appendix_builder import (
        build_appendix_sheet_specs, write_appendix_workbook)
    from autogis.core.common.qa import QACollector
    from autogis.core.common.config import ConfigError, load_flat_screening_levels

    rows = _read_csv_rows(results_path)
    try:
        sl = load_flat_screening_levels(Path(sl_path)) if sl_path else None
    except ConfigError as exc:
        raise click.ClickException(str(exc))
    group_map = (_read_yaml(group_map_path)
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
@click.option("--export-dir", default=None, type=click.Path(file_okay=False),
              help="Also write one <TableName>.json file per Dash_* table for "
                   "'agol refresh-dashboard --mart-dir'.")
def build_dashboard_data_mart_cmd(gdb, site_id, event_id, prior_event_id,
                                  export_dir):
    """Tool 6.7: rebuild Dash_* tables and optionally export refresh JSON."""
    _guard("build-dashboard-data-mart")
    from autogis.core.envmon.dashboard_data_mart import build_dashboard_data_mart
    summary = build_dashboard_data_mart(gdb, site_id, event_id,
                                        prior_event_id=prior_event_id,
                                        export_dir=export_dir)
    for table, n in summary.row_counts.items():
        click.echo(f"{table}: {n} row(s)")
    click.echo(f"Updated {len(summary.tables_updated)} table(s) "
               f"for {site_id}/{event_id}.")
    if export_dir:
        click.echo(f"Exported {len(summary.tables_updated)} JSON file(s) "
                   f"to {export_dir}.")


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
    from autogis.core.envmon.build_exceedance_event import (
        build_exceedance_event, write_exceedance_event_csv)
    from autogis.core.common.qa import QACollector
    from autogis.core.common.config import ConfigError, load_flat_screening_levels

    rows = _read_csv_rows(results_path)
    try:
        sl = load_flat_screening_levels(Path(sl_path))
    except ConfigError as exc:
        raise click.ClickException(str(exc))
    date_range = (date_from, date_to) if (date_from and date_to) else None
    qa = QACollector()
    try:
        records = build_exceedance_event(
            rows, sl, rule=rule, event_date=event_date,
            date_range=date_range, qa=qa)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    write_exceedance_event_csv(records, Path(out))
    exceed = sum(1 for r in records if r.has_exceedance)
    click.echo(f"Records: {len(records)}  Exceedances: {exceed}  Output: {out}")
    _render_qa(qa, report, "warning")


@envmon.command("list-tools")
@click.option("--runtime", "runtime_filter", default=None,
              type=click.Choice(sorted(RUNTIME_CLASSES),
                                case_sensitive=False))
@click.option("--domain", default=None,
              type=click.Choice(sorted({t.domain for t in TOOL_REGISTRY}),
                                case_sensitive=False))
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
@click.option("--max-per-sheet", type=click.IntRange(min=1), default=20, show_default=True)
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
        from autogis.core.common.config import ConfigError, load_flat_screening_levels
        try:
            sl_map = load_flat_screening_levels(Path(sl_path))
        except ConfigError as exc:
            raise click.ClickException(str(exc))
        for s in series_list:
            if s.analyte_name in sl_map:
                s.screening_level = sl_map[s.analyte_name]
    chart_count = write_trend_charts(series_list, Path(out),
                                     max_per_sheet=max_per_sheet)
    click.echo(f"Written: {out}  ({len(series_list)} series, "
               f"{chart_count} chart(s))")
    _render_qa(qa, report, fail_on)


def _read_tracker_or_fail(path) -> list:
    """read_tracker_csv, with a directory or non-UTF-8 tracker reported as a
    ClickException, not a raw traceback (#585)."""
    import csv
    from autogis.core.envmon.ingest_reviewer_comments import read_tracker_csv
    try:
        return read_tracker_csv(Path(path))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise click.ClickException(f"cannot read {path}: {exc}")


@envmon.command("ingest-reviewer-comments")
@click.argument("input_file", metavar="INPUT", type=click.Path(exists=True))
@click.option("--out", "out_path", required=True,
              type=click.Path(dir_okay=False),
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
    import csv
    from zipfile import BadZipFile
    from autogis.core.envmon.ingest_reviewer_comments import (
        ingest_comments, merge_tracker, write_tracker_csv,
        format_comment_summary)

    qa = QACollector()
    try:
        incoming = ingest_comments(Path(input_file), qa=qa)
    except (OSError, ValueError, csv.Error, BadZipFile, KeyError) as exc:
        # ValueError covers JSONDecodeError and UnicodeDecodeError; BadZipFile
        # and KeyError are openpyxl on a file that is not a real .xlsx (#585).
        raise click.ClickException(f"cannot read {input_file}: {exc}")
    existing = _read_tracker_or_fail(tracker_path) if tracker_path else []
    merged = merge_tracker(existing, incoming, qa=qa)
    out = Path(out_path)
    try:
        write_tracker_csv(merged, out)
    except OSError as exc:
        raise click.ClickException(f"cannot write {out}: {exc}")
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
              type=CommaList(
                  (IntervalTier.HOTSPOT, IntervalTier.DETECT, IntervalTier.ND,
                   IntervalTier.NO_DATA),
                  case_sensitive=False),
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
        IntervalTier, load_soil_results_csv, select_intervals,
        write_intervals_csv)
    from autogis.core.common.qa import QACollector

    analyte_list = [a.strip() for a in analytes.split(",")] if analytes else None
    tier_list = [t.strip().upper() for t in tiers.split(",")] if tiers else None
    unknown_tiers = sorted(set(tier_list or ()) - IntervalTier.ALL)
    if unknown_tiers:
        raise click.BadParameter(
            f"unknown tier(s): {', '.join(unknown_tiers)}; "
            f"valid: {', '.join(sorted(IntervalTier.ALL))}",
            param_hint="--tiers")
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
    """Export comparison results to a formatted Excel workbook (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.export_comparison_excel import export_comparison_excel

    records = _read_csv_rows(comparison_csv)
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

    spec = _read_yaml(manifest) or {}
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
@click.option("--scan-rows", type=click.IntRange(min=0), default=40, show_default=True,
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
@click.option("--output-dir", required=True, type=click.Path(file_okay=False),
              help="Directory to write sample_records.csv, result_records.csv, "
                   "and batch_manifest.csv.")
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary YAML (optional).")
@click.option("--screening", default=None, type=click.Path(exists=True),
              help="Screening levels YAML (optional).")
@click.option("--event-date", default=None, type=IsoDate(),
              help="Force event date for all workbooks (YYYY-MM-DD).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def batch_import_workbooks_cmd(manifest, edd_dir, profile, site, pattern,
                               output_dir, analytes, screening,
                               event_date, report, fail_on):
    """Tool 2.2: batch-import EDD workbooks from a manifest CSV or a directory (headless)."""
    from datetime import date as _date
    from autogis.core.common.config import ConfigError, load_config
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
        try:
            manifest_rows = read_manifest_csv(Path(manifest))
        except (OSError, UnicodeDecodeError) as exc:
            raise click.ClickException(f"cannot read {manifest}: {exc}")
        except ValueError as exc:  # missing columns, rows or values
            raise click.ClickException(f"{manifest}: {exc}")
    try:
        analyte_dict = load_config(Path(analytes)) if analytes else {}
        screening_lvls = load_config(Path(screening)) if screening else {}
    except ConfigError as exc:
        raise click.ClickException(str(exc))
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
@click.option("--default-matrix", default="GW", show_default=True,
              type=SuggestedChoice(sorted(KNOWN_MATRICES) + ["SED", "SW"]))
@click.option("--default-units", default="ug/L", show_default=True,
              type=SuggestedChoice(sorted(UNIT_REGISTRY)))
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
    units_map = _read_yaml(units_yaml) \
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
@click.option("--event-date", required=True, type=IsoDate(),
              help="Planned sampling date YYYY-MM-DD.")
@click.option("--site-id", default="", help="Site ID.")
@click.option("--prior-event-date", default=None, type=IsoDate(),
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
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.records_csv import write_records_csv
    from autogis.core.envmon.sampling_plan import (
        read_well_network_csv, create_sampling_plan,
        PlannedSample, BottleCountRow)

    wells = read_well_network_csv(Path(wells_csv))
    groups = _read_yaml(analyte_groups)
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
@click.option("--date-tolerance", type=click.IntRange(min=0), default=1, show_default=True,
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
@click.option("--event-date", required=True, type=IsoDate(),
              help="Event date YYYY-MM-DD (raster naming + registry row).")
@click.option("--nondetect-rule",
              type=click.Choice(["exclude", "half_rl", "use_rl", "use_zero"]),
              default="exclude", show_default=True,
              help="Numeric substitution for nondetects (ADR-0085 "
                   "decision 4).")
@click.option("--unit", "surface_unit", default="ug/L", show_default=True,
              type=SuggestedChoice(sorted(UNIT_REGISTRY)),
              help="Declared surface unit (ADR-0022 registry); every "
                   "result/RL/DL is normalized into it, rows with unknown "
                   "or cross-dimension units are excluded with a warning.")
@click.option("--matrix", default=None,
              type=SuggestedChoice(sorted(KNOWN_MATRICES) + ["SED", "SW"]),
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

    # Validate the unit up front and narrowly: collect_concentration_points
    # also raises ValueError for malformed --coords rows, and a blanket
    # "Invalid value for --unit" would send the operator to fix the wrong
    # option (codex review). Same registry check the core function runs.
    from autogis.core.common.units import normalize_unit
    if normalize_unit(surface_unit) is None:
        raise click.BadParameter(
            f"not in the ADR-0022 unit registry: {surface_unit!r}",
            param_hint="--unit")

    qa = QACollector()
    try:
        points = collect_concentration_points(
            Path(results_csv), Path(coords_csv), site_id=site_id,
            event_date=event_date, analyte=analyte,
            nondetect_rule=nondetect_rule, surface_unit=surface_unit,
            matrix=matrix, qa=qa)
    except ValueError as exc:
        # remaining ValueErrors (coords parse, date shape) still get a clean
        # message instead of a traceback, just not blamed on --unit
        raise click.ClickException(str(exc))
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
@click.option("--out-dir", required=True, type=click.Path(file_okay=False),
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
    """Tool 8.10: PNEZD point CSV + projection note for Civil 3D (headless);
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


@envmon.command("transform-landxml")
@click.option("--input", "input_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Input LandXML file containing one or more TIN surfaces.")
@click.option("--output", "output_path", required=True,
              type=click.Path(dir_okay=False),
              help="Output single-surface LandXML file.")
@click.option("--source-crs", required=True,
              help="Authority-coded source CRS, e.g. EPSG:4326 or "
                   "ESRI:102700.")
@click.option("--target-crs", required=True,
              help="Projected target CRS, e.g. EPSG:2232.")
@click.option("--source-unit",
              type=click.Choice(["meter", "foot", "USSurveyFoot"]),
              default=None, hidden=True,
              help="Deprecated assertion for the source unit.")
@click.option("--target-unit",
              type=click.Choice(["meter", "foot", "USSurveyFoot"]),
              default=None, hidden=True,
              help="Deprecated assertion for the target unit.")
@click.option("--source-z-unit",
              type=click.Choice(["meter", "foot", "USSurveyFoot"]),
              default=None,
              help="Actual input elevation unit; default is inferred from "
                   "the source CRS or geographic LandXML <Units>.")
@click.option("--geographic-transformation", default=None,
              help="Exact geographic transformation name or authority code "
                   "(for example ESRI:108190); default selects the best "
                   "available operation for the surface extent.")
@click.option("--z-scale", type=float, default=None,
              help="Positive custom Z multiplier. Replaces automatic unit "
                   "conversion and cannot be combined with --source-z-unit.")
@click.option("--surface", "surface_name", default="",
              help="Surface name to transform; required when input has several.")
@click.option("--output-surface-name", default="",
              help="Optional renamed surface in the output LandXML.")
@click.option("--override-source-metadata", is_flag=True, default=False,
              help="Trust the explicit source CRS/unit interpretation when "
                   "input metadata differs.")
@click.option("--overwrite", is_flag=True, default=False,
              help="Replace an existing output file (never overwrites input).")
def transform_landxml_cmd(input_path, output_path, source_crs, target_crs,
                          source_unit, target_unit, source_z_unit,
                          geographic_transformation, z_scale, surface_name,
                          output_surface_name, override_source_metadata,
                          overwrite):
    """Project one LandXML TIN surface and scale its elevations."""
    from autogis.core.envmon.landxml_transform import transform_landxml_surface

    try:
        result = transform_landxml_surface(
            Path(input_path),
            Path(output_path),
            source_crs=source_crs,
            target_crs=target_crs,
            source_unit=source_unit,
            target_unit=target_unit,
            source_z_unit=source_z_unit,
            geographic_transformation=geographic_transformation,
            z_scale=z_scale,
            surface_name=surface_name,
            output_surface_name=output_surface_name,
            override_source_metadata=override_source_metadata,
            overwrite=overwrite,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc))
    click.echo(
        f"{result.surface_name}: {result.point_count} points / "
        f"{result.face_count} faces; {result.source_crs} ({result.source_unit}) "
        f"-> {result.target_crs} ({result.target_unit}); Z "
        f"{result.source_z_unit or 'unspecified'} -> {result.target_unit} x "
        f"{result.z_scale:.15g} ({result.z_scale_mode})")
    operation_id = (
        f" [{result.operation_authority}:{result.operation_code}]"
        if result.operation_authority and result.operation_code else ""
    )
    accuracy = (
        f"; accuracy {result.operation_accuracy:g} m"
        if result.operation_accuracy is not None else ""
    )
    click.echo(
        f"Coordinate operation: {result.operation_name}{operation_id}"
        f"{accuracy}")
    click.echo(f"LandXML surface -> {result.output_path}")


@envmon.group("photos")
def photos_group():
    """Photo-metadata tools over a harvest output folder (EXIF-driven).

    All headless: they read the harvest manifest + the photo files' EXIF
    (GPS, compass heading, timestamp). Requires Pillow
    (pip install "autogis[report]").
    """


def _load_photo_records_or_fail(harvest_dir, qa):
    from autogis.core.envmon.photo_metadata import load_photo_records
    try:
        return load_photo_records(Path(harvest_dir), qa)
    except (FileNotFoundError, ImportError, ValueError) as exc:
        # ValueError also catches json.JSONDecodeError (its subclass) from a
        # malformed manifest.json -- a clean ClickException, not a traceback.
        raise click.ClickException(str(exc))


def _reject_harvest_input_overwrite(harvest_dir, *out_paths):
    """Refuse an output path that resolves onto any harvested input."""
    from autogis.core.envmon.photo_metadata import load_harvest_input_paths

    root = Path(harvest_dir).resolve(strict=False)
    manifest_paths = tuple((root / n).resolve(strict=False)
                           for n in ("manifest.json", "manifest.csv"))
    def identity(value):
        return str(value).replace("\\", "/").casefold()

    input_paths = manifest_paths + load_harvest_input_paths(root)
    inputs = {identity(p) for p in input_paths}
    outputs = [(p, Path(p), identity(Path(p).resolve(strict=False)))
               for p in out_paths if p]
    if len({key for _, _, key in outputs}) != len(outputs):
        raise click.ClickException(
            "multiple outputs resolve to the same output path")
    checked_outputs = []
    for p, target, key in outputs:
        if key in inputs:
            raise click.ClickException(
                f"output path {p} would overwrite a harvest input")
        if target.exists() and not target.is_file():
            raise click.ClickException(
                f"output path {p} is not a writable file target")
        if target.exists():
            try:
                if any(candidate.exists()
                       and os.path.samefile(target, candidate)
                       for candidate in input_paths):
                    raise click.ClickException(
                        f"output path {p} would overwrite a harvest input")
                if any(os.path.samefile(target, candidate)
                       for candidate in checked_outputs):
                    raise click.ClickException(
                        "multiple outputs resolve to the same output file")
            except OSError as exc:
                raise click.ClickException(
                    f"cannot verify output path {p}: {exc}") from exc
            checked_outputs.append(target)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                with target.open("r+b"):
                    pass
            else:
                probe = target.parent / f".autogis-probe-{uuid.uuid4().hex}"
                try:
                    with probe.open("xb"):
                        pass
                finally:
                    probe.unlink(missing_ok=True)
        except OSError as exc:
            raise click.ClickException(
                f"output path {p} is not writable: {exc}") from exc


@photos_group.command("points")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--out-csv", default=None, type=click.Path(),
              help="Write photo points CSV here.")
@click.option("--out-geojson", default=None, type=click.Path(),
              help="Write photo points GeoJSON here.")
@qa_report_options
def photos_points_cmd(harvest_dir, out_csv, out_geojson, report, fail_on):
    """One point per GPS-bearing photo (EXIF position + heading)."""
    if not out_csv and not out_geojson:
        raise click.UsageError("pass --out-csv and/or --out-geojson")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_points import (
        write_points_csv, write_points_geojson)
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    _reject_harvest_input_overwrite(
        harvest_dir, out_csv, out_geojson, report)
    n = 0
    if out_csv:
        n = write_points_csv(records, Path(out_csv))
    if out_geojson:
        n = write_points_geojson(records, Path(out_geojson))
    skipped = len(records) - n
    click.echo(f"Photo points: {n} point(s) from {len(records)} photo(s)"
               + (f" ({skipped} without GPS)" if skipped else ""))
    _render_qa(qa, report, fail_on)


@photos_group.command("qa")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--max-offset-m", default=100.0, show_default=True,
              type=click.FloatRange(min=0.0),
              help="Flag photos whose EXIF GPS is farther than this from "
                   "their source feature.")
@qa_report_options
def photos_qa_cmd(harvest_dir, max_offset_m, report, fail_on):
    """Cross-check photo EXIF against the features they are attached to."""
    if not math.isfinite(max_offset_m):
        raise click.BadParameter(
            "must be finite", param_hint="--max-offset-m")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_metadata import evaluate_photo_qa
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    _reject_harvest_input_overwrite(harvest_dir, report)
    s = evaluate_photo_qa(records, qa, max_offset_m=max_offset_m)
    click.echo(f"Photo QA: {s['n_photos']} photo(s); "
               f"offset {s['flagged_offset']}/{s['checked_offset']} flagged; "
               f"date {s['flagged_date']}/{s['checked_date']} flagged; "
               f"{s['missing_gps']} missing GPS; "
               f"{s['missing_datetime']} missing datetime; "
               f"{s['unreadable']} unreadable")
    _render_qa(qa, report, fail_on)


@photos_group.command("log")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output file (extension need not match --format).")
@click.option("--format", "fmt", default="xlsx", show_default=True,
              type=click.Choice(["xlsx", "html", "docx"]))
@click.option("--title", default="Photographic Log", show_default=True)
@qa_report_options
def photos_log_cmd(harvest_dir, out_path, fmt, title, report, fail_on):
    """Photographic log appendix (thumbnail, date, direction, coordinates)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_log import write_log
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    _reject_harvest_input_overwrite(harvest_dir, out_path, report)
    try:
        n = write_log(records, Path(out_path), fmt=fmt, title=title)
    except ImportError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Photo log: {n} photo(s) -> {out_path} ({fmt})")
    _render_qa(qa, report, fail_on)


@photos_group.command("kmz")
@click.option("--harvest-dir", required=True,
              type=click.Path(exists=True, file_okay=False),
              help="Harvest output directory (contains manifest.csv/json).")
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output .kmz path.")
@click.option("--thumb-px", default=800, show_default=True,
              type=click.IntRange(min=1),
              help="Max thumbnail edge (pixels) embedded in the KMZ.")
@qa_report_options
def photos_kmz_cmd(harvest_dir, out_path, thumb_px, report, fail_on):
    """Google Earth KMZ of GPS-bearing photos with view-direction styling."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.photo_points import write_kmz
    qa = QACollector()
    records = _load_photo_records_or_fail(harvest_dir, qa)
    _reject_harvest_input_overwrite(harvest_dir, out_path, report)
    n = write_kmz(records, Path(out_path), thumb_px=thumb_px)
    click.echo(f"KMZ: {n} placemark(s) -> {out_path}")
    _render_qa(qa, report, fail_on)


# Legacy single-command entry point kept as an alias.
main = autogis


if __name__ == "__main__":
    autogis()
