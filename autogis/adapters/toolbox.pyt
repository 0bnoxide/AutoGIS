# -*- coding: utf-8 -*-
"""toolbox.pyt — reference ArcGIS Pro Python toolbox for the AutoGIS suite.

A marshaller over the installed ``autogis`` package: each tool's ``execute()``
pulls params off the GUI and hands them to the pure ``autogis.core`` functions
(arcpy-touching where noted), rendering QA via ``_msg``. No ``sys.path`` hack —
install the package (``pip install -e .``) into the cloned ``arcgispro-py3`` env
so it imports normally. See ``docs/pro-install.md``.

This file is intentionally never imported by the test suite: its top-level
``import arcpy`` only resolves inside ArcGIS Pro.
"""

import json
from pathlib import Path

import arcpy

from autogis.adapters import toolbox_core
from autogis.core.common.config import (
    ParserProfile, SiteConfig, load_config, load_analyte_dictionary,
    FigureSpec,
)
from autogis.core.common.qa import QACollector


def _msg(messages, qa: QACollector):
    for rec in qa.records:
        line = f"[{rec.severity}] {rec.category}: {rec.message}"
        if rec.severity in ("ERROR", "CRITICAL"):
            messages.addErrorMessage(line)
        elif rec.severity == "WARNING":
            messages.addWarningMessage(line)
        else:
            messages.addMessage(line)


def _param(name, display, datatype, required=True, direction="Input",
           default=None, domain=None, multi=False):
    p = arcpy.Parameter(
        displayName=display, name=name, datatype=datatype,
        parameterType="Required" if required else "Optional",
        direction=direction, multiValue=multi,
    )
    if default is not None:
        p.value = default
    if domain:
        p.filter.type = "ValueList"
        p.filter.list = list(domain)
    return p


class Toolbox(object):
    def __init__(self):
        self.label = "AutoGIS Suite"
        self.alias = "autogis"
        self.tools = [
            HarvestAttachments,
            # envmon — headless (CLOUD): no arcpy required.
            InspectWorkbook,         # tool 1
            ReadParserProfile,       # tool 9
            LoadFigureSpec,          # tool 10
            # envmon — LOCAL (arcpy): runtime-guarded.
            ImportToGdb,             # tool 2
            BuildCurrentEvent,       # tool 3
            BuildCallouts,           # tool 4
            GroundwaterContours,     # tool 5
            RunGWModelPipeline,      # Phase-5 slice 1 (ADR-0085)
            BuildConcentrationSurface,  # Phase-5 slice 2 (ADR-0085)
            ExportFigures,           # tool 6
            FullPipeline,            # tool 7
            ValidateDatabase,        # tool 8
            ReconcileSampleLocations,
            ConditionDEM,
            CompareDroneSurfaces,
            ExportContoursForCivil3D,  # tool 8.2 TIN -> LandXML surface
            BuildCADExportPackage,   # tool 8.9
            DownloadOpenTopoDEM,     # OpenTopography DEM fetch + add-to-map
        ]


class HarvestAttachments(object):
    def __init__(self):
        self.label = "Harvest Attachments"
        self.description = ("Download attachments from a hosted feature layer "
                            "into grouped/templated folders. Pure marshalling "
                            "over autogis.core.harvest. Exposes a subset of "
                            "HarvestConfig — layer_index/all_sublayers/"
                            "skip_existing/retries/backoff_seconds are not "
                            "toolbox parameters; set them via the CLI's "
                            "--config YAML path instead.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("directory", "Output directory", "DEFolder"),
            _param("group_template", "Group folder template", "GPString"),
            _param("filename_template", "Filename template", "GPString"),
            _param("url", "Feature layer URL", "GPString", required=False),
            _param("item_id", "AGOL item id", "GPString", required=False),
            _param("where", "WHERE clause", "GPString",
                   required=False, default="1=1"),
            _param("incremental", "Incremental", "GPBoolean",
                   required=False, default=False),
        ]

    def execute(self, parameters, messages):
        from autogis.runtime.sessions import pro_active_portal
        p = {q.name: q for q in parameters}
        qa = QACollector()
        config = toolbox_core.build_harvest_config(
            directory=p["directory"].valueAsText,
            group_template=p["group_template"].valueAsText,
            filename_template=p["filename_template"].valueAsText,
            url=p["url"].valueAsText or None,
            item_id=p["item_id"].valueAsText or None,
            where=p["where"].valueAsText or "1=1",
            incremental=bool(p["incremental"].value),
        )
        results = toolbox_core.run_harvest(config, pro_active_portal())
        messages.addMessage(f"{len(results)} attachment(s) processed.")
        _msg(messages, qa)


# ==========================================================================
# envmon Tool classes — faithful ports of the staging
# EnvironmentalMonitoringTools.pyt over the packaged ``autogis.core`` modules.
# Headless tools (1/9/10) call the openpyxl-only core directly; LOCAL tools
# (2-8) call ``require_runtime`` first so a missing arcpy is a clean error,
# then the arcpy-touching core.
# ==========================================================================

# ---------------------------------------------------------- headless (CLOUD)
class InspectWorkbook(object):
    """Tool 1 — workbook structure inspection (openpyxl only)."""

    def __init__(self):
        self.label = "1. Inspect Environmental Workbook"
        self.description = ("Profile every sheet of a workbook (merged cells, "
                            "header rows, formula issues) and write a "
                            "structure report. Read-only.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("workbook", "Source workbook (.xlsx)", "DEFile"),
            _param("output_dir", "Inspection output folder", "DEFolder"),
        ]

    def execute(self, parameters, messages):
        from autogis.core.envmon.excel_workbook_inspector import (
            inspect_workbook_structure, write_inspection_outputs,
        )
        qa = QACollector()
        wb = Path(parameters[0].valueAsText)
        out = Path(parameters[1].valueAsText)
        report = inspect_workbook_structure(wb, qa)
        json_path = out / f"{wb.stem}_inspection.json"
        csv_path = out / f"{wb.stem}_inspection.csv"
        write_inspection_outputs(report, json_path, csv_path)
        messages.addMessage(f"Wrote {json_path}")
        messages.addMessage(f"Wrote {csv_path}")
        _msg(messages, qa)


class ReadParserProfile(object):
    """Tool 9 — inspect a workbook and write a DRAFT parser profile."""

    def __init__(self):
        self.label = "9. Create Parser Profile Draft from Workbook"
        self.description = ("Inspect a workbook and write a DRAFT parser "
                            "profile YAML with _TODO flags for human review. "
                            "Never import with an unreviewed draft.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("workbook", "Source workbook (.xlsx)", "DEFile"),
            _param("output_profile", "Output profile path (.yaml)",
                   "DEFile", direction="Output"),
        ]

    def execute(self, parameters, messages):
        from autogis.core.envmon.excel_workbook_inspector import (
            inspect_workbook_structure, propose_parser_profile,
        )
        qa = QACollector()
        wb = Path(parameters[0].valueAsText)
        out = Path(parameters[1].valueAsText)
        report = inspect_workbook_structure(wb, qa)
        draft = propose_parser_profile(report, profile_id=f"DRAFT_{wb.stem}")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml
            out.write_text(yaml.safe_dump(draft, sort_keys=False),
                           encoding="utf-8")
        except ImportError:
            out = out.with_suffix(".json")
            out.write_text(json.dumps(draft, indent=2, default=str),
                           encoding="utf-8")
        messages.addWarningMessage(
            f"DRAFT profile written to {out}. Review every _TODO before "
            "importing — header-row guesses are heuristics, not facts.")
        _msg(messages, qa)


class LoadFigureSpec(object):
    """Tool 10 — write a commented figure-spec YAML skeleton (no arcpy)."""

    def __init__(self):
        self.label = "10. Create Figure Spec Template"
        self.description = "Write a commented figure-spec YAML skeleton."
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("output_spec", "Output figure spec (.yaml)", "DEFile",
                   direction="Output"),
            _param("template_kind", "Callout template", "GPString",
                   default="CKG_GW",
                   domain=("CKG_GW", "ZT42_GW", "ZT42_SOIL", "METALS", "IBI",
                           "COMPACT_KV", "CUSTOM_ANALYTICAL")),
        ]

    def execute(self, parameters, messages):
        out = Path(parameters[0].valueAsText)
        kind = parameters[1].valueAsText
        skeleton = f"""# Figure spec template — fill in every _TODO
figure_spec_id: _TODO_unique_id
site_id: _TODO
matrix: GW            # GW | SOIL
map_type: GW_ANALYTICAL
figure_number: _TODO
reference_scale: 1200
analyte_set_name: petroleum_six_pack   # or custom_list: [...]
sample_selection_rule: latest_per_location
duplicate_handling_rule: prefer_parent
callout_template:
  template_id: {kind}
  base_font_points: 6
  standoff_points: 18
  point_buffer_points: 10
template_aprx: ../../templates/aprx/_TODO.aprx
layout_name: _TODO
extent_boundary_layer: SiteBoundary
output_filename_pattern: "{{site_id}}_{{figure_number}}_{{event_date}}"
layer_definition_queries:
  Env_CalloutBoxes: "SiteID = '{{site_id}}' AND FigureSpecID = '{{figure_spec_id}}' AND EventDate = '{{event_date}}'"
"""
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(skeleton, encoding="utf-8")
        messages.addMessage(f"Template written: {out}")


# ------------------------------------------------------------- LOCAL (arcpy)
class ImportToGdb(object):
    """Tool 2 — import a workbook into the file geodatabase (arcpy)."""

    def __init__(self):
        self.label = "2. Import Environmental Workbook"
        self.description = ("Parse a workbook with a parser profile and load "
                            "normalized records into the GDB. Source workbook "
                            "is never modified.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("workbook", "Source workbook (.xlsx)", "DEFile"),
            _param("gdb", "Target file geodatabase", "DEWorkspace"),
            _param("site_config", "Site config (YAML/JSON)", "DEFile"),
            _param("parser_profile", "Parser profile (YAML/JSON)", "DEFile"),
            _param("analyte_dictionary", "Analyte dictionary", "DEFile"),
            _param("screening_levels", "Screening levels config", "DEFile"),
            _param("qa_output_dir", "QA output folder", "DEFolder"),
            _param("mode", "Import mode", "GPString", default="validate_only",
                   domain=("validate_only", "append", "replace_batch",
                           "replace_site_event")),
            _param("matrix_filter", "Matrix filter", "GPString",
                   required=False, domain=("GW", "SOIL")),
            _param("batch_id_to_replace", "Batch ID to replace (replace_batch)",
                   "GPString", required=False),
            _param("event_date", "Event date YYYY-MM-DD (replace_site_event)",
                   "GPString", required=False),
            _param("allow_duplicates", "Allow duplicate records",
                   "GPBoolean", required=False, default=False),
            _param("allow_errors", "Override ERROR-level QA block",
                   "GPBoolean", required=False, default=False),
        ]

    @toolbox_core.record_pyt_run("import-gdb")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("import-gdb")
        from autogis.core.envmon.import_to_gdb import run_import
        p = {q.name: q for q in parameters}
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        profile = ParserProfile.load(Path(p["parser_profile"].valueAsText))
        summary = run_import(
            workbook=Path(p["workbook"].valueAsText),
            gdb=Path(p["gdb"].valueAsText),
            site_config=site,
            profile=profile,
            analyte_dictionary_path=Path(p["analyte_dictionary"].valueAsText),
            screening_levels_path=Path(p["screening_levels"].valueAsText),
            qa_output_dir=Path(p["qa_output_dir"].valueAsText),
            mode=p["mode"].valueAsText,
            matrix_filter=p["matrix_filter"].valueAsText or None,
            batch_id_to_replace=p["batch_id_to_replace"].valueAsText or None,
            event_date=p["event_date"].valueAsText or None,
            allow_duplicate_records=bool(p["allow_duplicates"].value),
            allow_errors_override=bool(p["allow_errors"].value),
        )
        messages.addMessage(json.dumps(summary, indent=2, default=str))


class BuildCurrentEvent(object):
    """Tool 3 — build current-event feature data (arcpy)."""

    def __init__(self):
        self.label = "3. Build Current Event Tables"
        self.description = ("Apply a figure spec's sample-selection, depth, "
                            "and duplicate rules; write Env_CurrentEventWide.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("site_config", "Site config", "DEFile"),
            _param("figure_spec", "Figure spec (YAML/JSON)", "DEFile"),
            _param("analyte_dictionary", "Analyte dictionary", "DEFile"),
            _param("event_date", "Event date YYYY-MM-DD (rule-dependent)",
                   "GPString", required=False),
        ]

    @toolbox_core.record_pyt_run("build-event")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("build-event")
        from autogis.core.envmon.build_current_event import (
            build_current_event_wide,
        )
        qa = QACollector()
        p = {q.name: q for q in parameters}
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        spec = FigureSpec.load(Path(p["figure_spec"].valueAsText))
        adict = load_analyte_dictionary(Path(p["analyte_dictionary"].valueAsText))
        wide = build_current_event_wide(
            Path(p["gdb"].valueAsText), site.site_id, spec, adict, qa,
            event_date=p["event_date"].valueAsText or None,
        )
        messages.addMessage(f"{len(wide)} wide rows written.")
        _msg(messages, qa)


class BuildCallouts(object):
    """Tool 4 — generate callout feature classes (arcpy)."""

    def __init__(self):
        self.label = "4. Build Analytical Callouts"
        self.description = ("Generate table-style callout boxes, gridlines, "
                            "leaders, and cell anchors with collision-aware "
                            "placement and user-override support.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("site_config", "Site config", "DEFile"),
            _param("figure_spec", "Figure spec", "DEFile"),
            _param("analyte_dictionary", "Analyte dictionary", "DEFile"),
            _param("event_date", "Event date YYYY-MM-DD", "GPString"),
            _param("map_type", "Map type", "GPString", default="GW_ANALYTICAL"),
            _param("replace_existing", "Replace existing callouts",
                   "GPBoolean", required=False, default=True),
            _param("use_hull_collision", "Use hull collision (numpy)",
                   "GPBoolean", required=False, default=False),
        ]

    @toolbox_core.record_pyt_run("build-callouts")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("build-callouts")
        from autogis.core.envmon.build_current_event import (
            build_current_event_wide,
        )
        from autogis.core.envmon.build_figure_dataset import (
            generate_callout_features,
        )
        qa = QACollector()
        p = {q.name: q for q in parameters}
        gdb = Path(p["gdb"].valueAsText)
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        spec = FigureSpec.load(Path(p["figure_spec"].valueAsText))
        adict = load_analyte_dictionary(Path(p["analyte_dictionary"].valueAsText))
        ev = p["event_date"].valueAsText
        wide = build_current_event_wide(gdb, site.site_id, spec, adict, qa,
                                        event_date=ev)
        n = generate_callout_features(
            gdb, site.site_id, spec, wide, adict, qa,
            event_date=ev, map_type=p["map_type"].valueAsText,
            replace_existing=bool(p["replace_existing"].value),
            map_units=site.get("map_units", "feet"),
            use_hull_collision=bool(p["use_hull_collision"].value),
        )
        messages.addMessage(f"{n} callouts generated.")
        _msg(messages, qa)


class GroundwaterContours(object):
    """Tool 5 — build groundwater contours (arcpy)."""

    def __init__(self):
        self.label = "5. Build Groundwater Contours (DRAFT)"
        self.description = ("Interpolate DRAFT potentiometric contours and a "
                            "DRAFT flow arrow. Output requires professional "
                            "review before use.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("site_config", "Site config", "DEFile"),
            _param("event_date", "Event date YYYY-MM-DD", "GPString"),
            _param("method", "Interpolation method", "GPString",
                   default="TIN",
                   domain=("TIN", "IDW", "NaturalNeighbor", "SkipContours",
                           "EBK")),
            _param("interval", "Contour interval (ft)", "GPDouble",
                   required=False, default=1.0),
            _param("min_points", "Minimum valid points", "GPLong",
                   required=False, default=3),
            _param("boundary_fc", "Clip boundary feature class",
                   "DEFeatureClass", required=False),
        ]

    @toolbox_core.record_pyt_run("gw-contours")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("gw-contours")
        from autogis.core.envmon.groundwater_contours import (
            build_groundwater_contours,
        )
        qa = QACollector()
        p = {q.name: q for q in parameters}
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        summary = build_groundwater_contours(
            Path(p["gdb"].valueAsText), site.site_id,
            p["event_date"].valueAsText, qa,
            method=p["method"].valueAsText,
            contour_interval=float(p["interval"].value or 1.0),
            min_valid_points=int(p["min_points"].value or 3),
            boundary_fc=p["boundary_fc"].valueAsText or None,
        )
        messages.addMessage(json.dumps(summary, indent=2))
        _msg(messages, qa)


class RunGWModelPipeline(object):
    """Phase-5 slice 1 — multi-model GW pipeline with LOO ranking (arcpy).

    RunFieldToGroundwaterModelPipeline per ADR-0085; select a single method
    for the BuildGroundwaterSurfaceModel mode. Approval is recorded
    afterwards with the `approve-gw-model` CLI verb.
    """

    def __init__(self):
        self.label = "5b. Run GW Model Pipeline (DRAFT)"
        self.description = ("Build DRAFT contours per interpolation method "
                            "(TIN/IDW/EBK), leave-one-out cross-validate, "
                            "rank by RMSE and persist GW_ModelRun/"
                            "GW_ModelCrossValidation (ReviewStatus=DRAFT). "
                            "EBK (slice 2) also writes a Draft_ standard-"
                            "error raster and needs Geostatistical Analyst. "
                            "Rank 1 is a suggestion only — a hydrogeologist "
                            "approves a model with approve-gw-model.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        methods = _param("methods", "Interpolation methods", "GPString",
                         multi=True, domain=("TIN", "IDW", "EBK"))
        methods.value = ["TIN", "IDW"]  # EBK is opt-in (slice-2 D6)
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("site_config", "Site config", "DEFile"),
            _param("event_date", "Event date YYYY-MM-DD", "GPString"),
            methods,
            _param("interval", "Contour interval (ft)", "GPDouble",
                   required=False, default=1.0),
            _param("min_points", "Minimum valid points", "GPLong",
                   required=False, default=3),
            _param("boundary_fc", "Clip boundary feature class",
                   "DEFeatureClass", required=False),
            _param("tolerance_ft", "CV tolerance (ft)", "GPDouble",
                   required=False, default=0.5),
            _param("observations_csv", "Audit observations CSV", "DEFile",
                   required=False, direction="Output"),
            _param("stats_csv", "Ranked stats CSV", "DEFile",
                   required=False, direction="Output"),
        ]

    @toolbox_core.record_pyt_run("run-gw-model-pipeline")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("run-gw-model-pipeline")
        from autogis.core.envmon.gw_model_pipeline import (
            run_field_to_groundwater_model_pipeline,
        )
        qa = QACollector()
        p = {q.name: q for q in parameters}
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        methods = [m.strip() for m in
                   (p["methods"].valueAsText or "TIN;IDW").split(";") if m]
        summary = run_field_to_groundwater_model_pipeline(
            Path(p["gdb"].valueAsText), site.site_id,
            p["event_date"].valueAsText, qa,
            methods=methods,
            contour_interval=float(p["interval"].value or 1.0),
            min_valid_points=int(p["min_points"].value or 3),
            boundary_fc=p["boundary_fc"].valueAsText or None,
            tolerance_ft=float(p["tolerance_ft"].value or 0.5),
            observations_csv=(Path(p["observations_csv"].valueAsText)
                              if p["observations_csv"].valueAsText else None),
            stats_csv=(Path(p["stats_csv"].valueAsText)
                       if p["stats_csv"].valueAsText else None),
        )
        messages.addMessage(json.dumps(summary, indent=2))
        _msg(messages, qa)


class BuildConcentrationSurface(object):
    """Phase-5 slice 2 — DRAFT interpolated concentration raster (arcpy).

    BuildAnalyticalConcentrationSurface per ADR-0085: one analyte per
    surface, configurable nondetect policy, optional site-boundary clip.
    EBK also writes a standard-error companion raster.
    """

    def __init__(self):
        self.label = "5c. Build Concentration Surface (DRAFT)"
        self.description = ("Interpolate a DRAFT per-analyte concentration "
                            "raster (IDW: Spatial Analyst; EBK: "
                            "Geostatistical Analyst, adds a standard-error "
                            "raster). Nondetects follow the selected rule "
                            "(ADR-0085 decision 4). Rasters get a Draft_ "
                            "name prefix and an Env_SurfaceRegistry row "
                            "(ReviewStatus=DRAFT).")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("site_config", "Site config", "DEFile"),
            _param("event_date", "Event date YYYY-MM-DD", "GPString"),
            _param("results_csv", "Analytical results CSV", "DEFile"),
            _param("coords_csv", "Well coords CSV (location_id,x,y)",
                   "DEFile"),
            _param("analyte", "Analyte canonical name", "GPString"),
            _param("nondetect_rule", "Nondetect rule", "GPString",
                   required=False, default="exclude",
                   domain=("exclude", "half_rl", "use_rl", "use_zero")),
            _param("surface_unit", "Surface unit (ADR-0022 registry)",
                   "GPString", required=False, default="ug/L"),
            _param("matrix", "Matrix filter (e.g. GW)", "GPString",
                   required=False),
            _param("method", "Interpolation method", "GPString",
                   required=False, default="IDW", domain=("IDW", "EBK")),
            _param("boundary_fc", "Clip boundary feature class",
                   "DEFeatureClass", required=False),
            _param("cell_size", "Cell size", "GPDouble", required=False),
        ]

    @toolbox_core.record_pyt_run("build-conc-surface")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("build-conc-surface")
        from autogis.core.envmon.concentration_surface import (
            build_concentration_surface, collect_concentration_points,
        )
        qa = QACollector()
        p = {q.name: q for q in parameters}
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        points = collect_concentration_points(
            Path(p["results_csv"].valueAsText),
            Path(p["coords_csv"].valueAsText),
            site_id=site.site_id,
            event_date=p["event_date"].valueAsText,
            analyte=p["analyte"].valueAsText,
            nondetect_rule=p["nondetect_rule"].valueAsText or "exclude",
            surface_unit=p["surface_unit"].valueAsText or "ug/L",
            matrix=p["matrix"].valueAsText or None,
            qa=qa)
        summary = build_concentration_surface(
            Path(p["gdb"].valueAsText), site.site_id,
            p["event_date"].valueAsText, p["analyte"].valueAsText,
            points, qa,
            method=p["method"].valueAsText or "IDW",
            nondetect_rule=p["nondetect_rule"].valueAsText or "exclude",
            surface_unit=p["surface_unit"].valueAsText or "ug/L",
            cell_size=(float(p["cell_size"].value)
                       if p["cell_size"].value else None),
            boundary_fc=p["boundary_fc"].valueAsText or None,
        )
        messages.addMessage(json.dumps(summary, indent=2))
        _msg(messages, qa)


class ExportFigures(object):
    """Tool 6 — export figure layouts (arcpy)."""

    def __init__(self):
        self.label = "6. Export Environmental Figures"
        self.description = ("Copy the template APRX, repath to the GDB, apply "
                            "definition queries/text/extent, run pre-export "
                            "QA, export PDF/PNG/TIFF/JPEG.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("site_config", "Site config", "DEFile"),
            _param("figure_spec", "Figure spec", "DEFile"),
            _param("event_date", "Event date YYYY-MM-DD", "GPString"),
            _param("export_dir", "Export folder", "DEFolder"),
            _param("formats", "Formats", "GPString", default="PDF",
                   domain=("PDF", "PNG", "TIFF", "JPEG"), multi=True),
            _param("dpi", "DPI", "GPLong", required=False, default=300),
            _param("dry_run", "Dry run (no files written)", "GPBoolean",
                   required=False, default=False),
        ]

    @toolbox_core.record_pyt_run("export-figures")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("export-figures")
        from autogis.core.envmon.export_figures import (
            export_layouts, register_exports,
        )
        from autogis.core.envmon.layout_manager import (
            copy_template_aprx, update_aprx_data_sources,
            apply_figure_definition_queries, set_layer_visibility,
            update_layout_text, zoom_to_boundary,
        )
        qa = QACollector()
        p = {q.name: q for q in parameters}
        gdb = Path(p["gdb"].valueAsText)
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        spec = FigureSpec.load(Path(p["figure_spec"].valueAsText))
        ev = p["event_date"].valueAsText
        export_dir = Path(p["export_dir"].valueAsText)

        template = Path(spec.get("template_aprx") or spec.get("aprx_template") or "")
        if not template.is_absolute():
            template = Path(p["figure_spec"].valueAsText).parent / template
        work = copy_template_aprx(template, export_dir / "_working",
                                  f"{site.site_id}_{spec.figure_spec_id}_{ev}")
        update_aprx_data_sources(work, gdb, qa)
        lq = spec.get("layer_definition_queries", {})
        if lq:
            apply_figure_definition_queries(
                work, site.site_id, ev, spec.figure_spec_id,
                spec.get("map_type", "GW_ANALYTICAL"), lq, qa)
        set_layer_visibility(work, spec.get("visible_layers", []),
                             spec.get("hidden_layers", []), qa)
        text = dict(site.get("default_layout_text", {}))
        text.update(spec.get("layout_text", {}))
        text.setdefault("EventDate", ev)
        update_layout_text(work, spec.get("layout_name"), text, qa)
        b = spec.get("extent_boundary_layer")
        if b:
            zoom_to_boundary(work, spec.get("layout_name"), b,
                             float(spec.get("extent_buffer_pct", 5)), qa)

        written = export_layouts(
            work, export_dir,
            spec.get("output_filename_pattern",
                         "{site_id}_{figure_number}_{event_date}"),
            {"site_id": site.site_id, "event_date": ev,
             "figure_number": spec.get("figure_number", "Fig"),
             "figure_spec_id": spec.figure_spec_id},
            qa,
            layout_names=spec.get("layouts"),
            formats=[f.strip() for f in
                     (p["formats"].valueAsText or "PDF").split(";")],
            dpi=int(p["dpi"].value or 300),
            required_layers=spec.get("required_layers", []),
            combine_pdf=spec.get("combined_pdf_name"),
            dry_run=bool(p["dry_run"].value),
        )
        register_exports(gdb, written, site.site_id, ev,
                         spec.figure_spec_id, qa)
        for w in written:
            messages.addMessage(f"Exported {w}")
        _msg(messages, qa)


class FullPipeline(object):
    """Tool 7 — run the full import-to-figures pipeline (arcpy)."""

    def __init__(self):
        self.label = "7. Run Full Figure Pipeline"
        self.description = ("Import -> current event -> callouts -> contours "
                            "(optional) -> export, with QA gates between "
                            "stages.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("workbook", "Source workbook (.xlsx)", "DEFile"),
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("site_config", "Site config", "DEFile"),
            _param("parser_profile", "Parser profile", "DEFile"),
            _param("analyte_dictionary", "Analyte dictionary", "DEFile"),
            _param("screening_levels", "Screening levels", "DEFile"),
            _param("figure_specs", "Figure specs", "DEFile", multi=True),
            _param("event_date", "Event date YYYY-MM-DD", "GPString"),
            _param("qa_output_dir", "QA output folder", "DEFolder"),
            _param("export_dir", "Export folder", "DEFolder"),
            _param("import_mode", "Import mode", "GPString", default="append",
                   domain=("append", "replace_site_event")),
            _param("build_contours", "Build DRAFT contours", "GPBoolean",
                   required=False, default=False),
        ]

    @toolbox_core.record_pyt_run("full-pipeline")
    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("full-pipeline")
        from autogis.core.envmon.import_to_gdb import run_import
        from autogis.core.envmon.build_current_event import (
            build_current_event_wide,
        )
        from autogis.core.envmon.build_figure_dataset import (
            generate_callout_features,
        )
        from autogis.core.envmon.groundwater_contours import (
            build_groundwater_contours,
        )
        p = {q.name: q for q in parameters}
        gdb = Path(p["gdb"].valueAsText)
        site = SiteConfig.load(Path(p["site_config"].valueAsText))
        profile = ParserProfile.load(Path(p["parser_profile"].valueAsText))
        adict_path = Path(p["analyte_dictionary"].valueAsText)
        adict = load_analyte_dictionary(adict_path)
        ev = p["event_date"].valueAsText

        summary = run_import(
            workbook=Path(p["workbook"].valueAsText), gdb=gdb,
            site_config=site, profile=profile,
            analyte_dictionary_path=adict_path,
            screening_levels_path=Path(p["screening_levels"].valueAsText),
            qa_output_dir=Path(p["qa_output_dir"].valueAsText),
            mode=p["import_mode"].valueAsText, event_date=ev,
        )
        messages.addMessage(f"Import: {json.dumps(summary, default=str)}")
        if summary["qa_status"] == "FAIL":
            messages.addErrorMessage(
                "Pipeline halted: import QA failed. Review qa_output and "
                "re-run, or use Tool 2 with the error override after review.")
            return

        for spec_path in (p["figure_specs"].valueAsText or "").split(";"):
            spec = FigureSpec.load(Path(spec_path.strip()))
            qa = QACollector()
            wide = build_current_event_wide(gdb, site.site_id, spec, adict, qa,
                                            event_date=ev)
            generate_callout_features(
                gdb, site.site_id, spec, wide, adict, qa, event_date=ev,
                map_type=spec.get("map_type", "GW_ANALYTICAL"),
                map_units=site.get("map_units", "feet"),
            )
            if bool(p["build_contours"].value) and \
                    spec.get("map_type") == "GW_POTENTIOMETRIC":
                build_groundwater_contours(gdb, site.site_id, ev, qa)
            _msg(messages, qa)
        messages.addMessage(
            "Pipeline data stages complete. Run Tool 6 per figure spec to "
            "export (kept separate so layouts can be reviewed first).")


class ValidateDatabase(object):
    """Tool 8 — validate the geodatabase schema/contents (arcpy)."""

    def __init__(self):
        self.label = "8. Validate Environmental Database"
        self.description = "Read-only cross-table integrity checks."
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("analyte_dictionary", "Analyte dictionary", "DEFile"),
            _param("qa_output_dir", "QA output folder", "DEFolder"),
        ]

    def execute(self, parameters, messages):
        from autogis.adapters.guard import require_runtime
        require_runtime("validate-db")
        from autogis.core.envmon.validate_database import validate_database
        import datetime as dt
        qa = QACollector()
        p = {q.name: q for q in parameters}
        adict = load_analyte_dictionary(Path(p["analyte_dictionary"].valueAsText))
        summary = validate_database(Path(p["gdb"].valueAsText), qa, adict)
        out = Path(p["qa_output_dir"].valueAsText)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        qa.write_csv(out / f"validate_{stamp}.csv")
        qa.write_markdown(out / f"validate_{stamp}.md",
                          title="Database Validation")
        messages.addMessage(json.dumps(summary, indent=2))
        _msg(messages, qa)


class ReconcileSampleLocations(object):
    """Pre-flight: do workbook location IDs match the well feature class?

    Reads well LocationIDs from the site GDB via arcpy, extracts workbook
    location IDs through the parser profile (openpyxl), and reports matches /
    typos / unsampled wells. Read-only.
    """
    def __init__(self):
        self.label = "Reconcile Sample Locations"
        self.description = ("Compare workbook location IDs against the "
                            "monitoring-well feature class (read-only).")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("site_config", "Site config (YAML/JSON)", "DEFile"),
            _param("workbook", "Workbook (.xlsx)", "DEFile"),
            _param("profile", "Parser profile (YAML/JSON)", "DEFile"),
            _param("gdb", "Geodatabase", "DEWorkspace"),
            _param("threshold", "Fuzzy match threshold", "GPDouble",
                   required=False, default=0.8),
        ]

    @toolbox_core.record_pyt_run("reconcile-locations")
    def execute(self, parameters, messages):
        from autogis.runtime.sessions import arcpy_env
        from autogis.core.envmon.reconcile_locations import (
            extract_location_ids, reconcile, reconcile_to_qa)
        from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader

        p = {q.name: q for q in parameters}
        site = load_config(Path(p["site_config"].valueAsText))
        well_fc = site.get("monitoring_wells_fc", "MonitoringWells")
        gdb = Path(p["gdb"].valueAsText)
        threshold = float(p["threshold"].value or 0.8)

        profile = ParserProfile.load(Path(p["profile"].valueAsText))
        reader = ProfileWorkbookReader(Path(p["workbook"].valueAsText), profile)
        workbook_ids = extract_location_ids(reader, profile)

        arcpy = arcpy_env()
        well_ids = []
        with arcpy.da.SearchCursor(str(gdb / well_fc), ["LocationID"]) as cur:
            for (loc,) in cur:
                if loc is not None:
                    well_ids.append(str(loc))

        result = reconcile(workbook_ids, well_ids, threshold=threshold)
        qa = reconcile_to_qa(result)
        messages.addMessage(
            f"{len(result.matches)} matched, "
            f"{len(result.unmatched_workbook)} unmatched workbook ID(s), "
            f"{len(result.unmatched_wells)} unsampled well(s).")
        _msg(messages, qa)


class ConditionDEM(object):
    """DEMConditioningPipeline — void-fill/smooth a drone flight's DEM and
    derive hillshade/slope/contours (arcpy)."""

    def __init__(self):
        self.label = "Condition Drone DEM"
        self.description = ("Void-fill and smooth a drone flight's DEM, then "
                            "derive hillshade/slope/contours. Registers each "
                            "output as a DroneProductRegistry row.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("flight_id", "Drone flight ID", "GPString"),
            _param("out_dir", "Output folder", "DEFolder"),
            _param("fill_voids", "Fill voids", "GPBoolean",
                   required=False, default=False),
            _param("fill_voids_max_pixels", "Fill-voids max pixels", "GPLong",
                   required=False, default=9),
            _param("smooth", "Smooth method", "GPString", required=False,
                   domain=("median",)),
            _param("with_slope", "Derive slope", "GPBoolean",
                   required=False, default=False),
            _param("with_contours", "Derive contours", "GPBoolean",
                   required=False, default=False),
        ]

    @toolbox_core.record_pyt_run("condition-dem", site_config_param=None)
    def execute(self, parameters, messages):
        from autogis.core.envmon.dem_conditioning import (
            build_config, condition_dem, validate_config)
        p = {q.name: q for q in parameters}
        config = build_config(
            fill_voids=(int(p["fill_voids_max_pixels"].value or 9)
                       if bool(p["fill_voids"].value) else None),
            smooth=(p["smooth"].valueAsText or None) or None,
            with_slope=bool(p["with_slope"].value),
            with_contours=bool(p["with_contours"].value),
        )
        qa = QACollector()
        validate_config(config, qa)
        _msg(messages, qa)
        if qa.has_blocking():
            return
        records = condition_dem(
            p["gdb"].valueAsText, p["flight_id"].valueAsText,
            p["out_dir"].valueAsText, config)
        messages.addMessage(f"Wrote {len(records)} product(s).")


class CompareDroneSurfaces(object):
    """CompareDroneSurfaces — raster-diff a drone DEM against a prior flight
    or a LandXML design surface (arcpy)."""

    def __init__(self):
        self.label = "Compare Drone Surfaces"
        self.description = ("Diff a drone DEM against a second "
                            "DroneProductRegistry DEM or a LandXML design "
                            "surface, classified by a limit-of-detection "
                            "threshold.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("gdb", "File geodatabase", "DEWorkspace"),
            _param("primary_product_id", "Primary DEM product ID", "GPString"),
            _param("baseline_product_id", "Baseline DEM product ID",
                   "GPString", required=False),
            _param("baseline_landxml", "Baseline LandXML surface", "DEFile",
                   required=False),
            _param("lod_threshold_ft", "LOD threshold (ft)", "GPDouble",
                   required=False, default=0.2),
        ]

    @toolbox_core.record_pyt_run("compare-drone-surfaces", site_config_param=None)
    def execute(self, parameters, messages):
        from autogis.core.envmon.compare_drone_surfaces import (
            compare_surfaces, validate_baseline_args)
        p = {q.name: q for q in parameters}
        baseline_product_id = p["baseline_product_id"].valueAsText or None
        baseline_landxml = p["baseline_landxml"].valueAsText or None
        validate_baseline_args(baseline_product_id, baseline_landxml)
        lod_value = p["lod_threshold_ft"].value
        summary = compare_surfaces(
            p["gdb"].valueAsText, p["primary_product_id"].valueAsText,
            baseline_product_id=baseline_product_id or "",
            baseline_landxml_path=baseline_landxml or "",
            lod_threshold_ft=float(lod_value if lod_value is not None else 0.2))
        messages.addMessage(
            f"{summary.change_count}/{summary.count} cell(s) changed "
            f"(max {summary.max_diff_ft:.2f} ft, mean {summary.mean_diff_ft:.2f} ft).")


_CAD_OUTPUT_TYPES = (
    "DWG_R2018", "DWG_R2013", "DWG_R2010", "DWG_R2007", "DWG_R2005",
    "DWG_R2004", "DWG_R2000", "DWG_R14",
    "DXF_R2018", "DXF_R2013", "DXF_R2010", "DXF_R2007", "DXF_R2005",
    "DXF_R2004", "DXF_R2000", "DXF_R14",
    "DGN_V8",
)


class BuildCADExportPackage(object):
    """Tool 8.9 — export GIS layers to a CAD package (arcpy Export To CAD).

    Scratch copies receive ArcGIS's reserved CAD layer-property fields before
    export, so the mapping config controls CAD layer name/color/linetype
    without modifying the source feature classes (ADR-0089).
    """

    def __init__(self):
        self.label = "8.9 Build CAD Export Package"
        self.description = ("Export selected GIS layers to a DWG/DXF CAD "
                            "file, plus a projection note and a GIS->CAD "
                            "layer-mapping report.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("layers", "GIS layers to export", "GPFeatureLayer", multi=True),
            _param("mapping", "CAD layer mapping (YAML/JSON)", "DEFile"),
            _param("crs", "Coordinate system of the input layers "
                   "(e.g. EPSG:2256; validated against each layer, recorded "
                   "in the projection note)", "GPString"),
            _param("output_type", "CAD output type", "GPString",
                   default="DWG_R2018", domain=_CAD_OUTPUT_TYPES),
            _param("output_file", "Output CAD file", "DEFile", direction="Output"),
            _param("export_dir", "Folder for projection note + mapping report",
                   "DEFolder"),
        ]

    @toolbox_core.record_pyt_run("build-cad-package", site_config_param=None)
    def execute(self, parameters, messages):
        from autogis.core.common.landxml import parse_epsg
        from autogis.core.envmon.cad_layer_map import (
            find_prj_conflicts, load_cad_mapping, resolve_cad_plan,
            write_mapping_report, write_projection_note,
        )
        p = {q.name: q for q in parameters}
        raw_layers = p["layers"].valueAsText or ""
        layer_paths = [tok.strip().strip("'\"") for tok in raw_layers.split(";") if tok.strip()]
        layer_names = [arcpy.Describe(lp).name for lp in layer_paths]
        mapping_config = load_cad_mapping(Path(p["mapping"].valueAsText))
        crs = p["crs"].valueAsText

        plan = resolve_cad_plan(layer_names, mapping_config, crs=crs)
        _msg(messages, plan.qa)
        if plan.qa.has_blocking():
            return

        # ExportCAD writes each layer's SOURCE coordinates unchanged (no
        # output-CRS parameter, no reprojection) — a requested CRS that
        # doesn't match a layer would yield CAD in one CRS with a sidecar
        # claiming another (PR #246 review). Block on any mismatch.
        epsg = parse_epsg(crs)
        if epsg is None:
            messages.addErrorMessage(
                f"CRS {crs!r} is not an EPSG code (e.g. EPSG:2256), so the "
                "input layers' coordinate systems cannot be validated "
                "against it. Export To CAD keeps each layer's source CRS; "
                "refusing to export with an unverifiable claim.")
            return
        mismatched = [
            f"{name} (EPSG:{code or 'unknown'})"
            for name, code in (
                (lp, getattr(arcpy.Describe(lp).spatialReference,
                             "factoryCode", 0) or 0)
                for lp in layer_paths)
            if code != epsg]
        if mismatched:
            messages.addErrorMessage(
                "Export To CAD exports source coordinates unchanged (no "
                f"reprojection); these layers do not match EPSG:{epsg}: "
                + "; ".join(mismatched)
                + ". Project them first or pass their actual CRS.")
            return

        # An associated projection or world file (<stem>.prj/.wld, or a
        # folder-wide esri_cad.prj/.wld / *.uprj / *.uwld) makes Export To
        # CAD project/transform the output while projection_note.txt still
        # claims the source EPSG (issue #238). Refuse rather than
        # parse/compare their contents.
        output_file = p["output_file"].valueAsText
        prj_conflicts = find_prj_conflicts(Path(output_file))
        if prj_conflicts:
            messages.addErrorMessage(
                "Associated CAD projection/world file(s) would move the "
                "exported coordinates away from the source CRS: "
                + "; ".join(str(f) for f in prj_conflicts)
                + ". Remove them or export to a clean folder.")
            return

        export_dir = Path(p["export_dir"].valueAsText)
        write_projection_note(crs, export_dir / "projection_note.txt")
        report_path = write_mapping_report(plan, export_dir / "mapping_report.csv")

        output_type = p["output_type"].valueAsText or "DWG_R2018"
        with toolbox_core.staged_cad_layers(
                arcpy, layer_paths, plan.mappings) as staged_layers:
            # Pin the Output Coordinate System environment to the validated
            # source EPSG so an ambient env setting can't silently reproject
            # the export (Export To CAD honors that environment; issue #238).
            with arcpy.EnvManager(
                    outputCoordinateSystem=arcpy.SpatialReference(epsg)):
                arcpy.conversion.ExportCAD(
                    staged_layers, output_type, output_file)

        messages.addMessage(f"Exported {len(layer_paths)} layer(s) -> {output_file} ({output_type}).")
        messages.addMessage(f"Mapping report -> {report_path}")
        messages.addMessage("Applied mapped CAD layer names/properties to the exported file.")


class ExportContoursForCivil3D(object):
    """Tool 8.2 — export an existing ArcGIS TIN as a LandXML TIN surface."""

    def __init__(self):
        self.label = "8.2 Export Civil 3D TIN LandXML"
        self.description = (
            "Export an existing ArcGIS TIN to a coordinate-aware LandXML "
            "surface. Civil 3D imports the preserved triangle faces and can "
            "generate contour polylines from the resulting surface.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("input_tin", "Input TIN surface", "GPTinLayer"),
            _param("surface_name", "Civil 3D surface name", "GPString"),
            _param("crs", "Coordinate system of the TIN (e.g. EPSG:2256; "
                   "validated against the input)", "GPString"),
            _param("units", "Horizontal and elevation units", "GPString",
                   default="USSurveyFoot",
                   domain=("foot", "USSurveyFoot", "meter")),
            _param("output_file", "Output LandXML surface", "DEFile",
                   direction="Output"),
            # Appended AFTER output_file: the arcpy-generated signature is
            # positional in this order, so the optional parameter must not
            # displace the pre-existing required slots (Esri: required
            # parameters precede optional; PR #258 review P1). Order is
            # pinned by test_toolbox_cad.test_export_civil3d_pyt_parameter_order.
            _param("z_unit", "TIN vertical unit (blank = same as units; "
                   "declare when the TIN's elevations use a different unit "
                   "-- they are converted by the exact factor)", "GPString",
                   required=False, domain=("foot", "USSurveyFoot", "meter")),
        ]

    @toolbox_core.record_pyt_run(
        "export-civil3d", gdb_param="input_tin", site_config_param=None)
    def execute(self, parameters, messages):
        p = {q.name: q for q in parameters}
        units = p["units"].valueAsText
        z_unit = p["z_unit"].valueAsText or None
        try:
            output = toolbox_core.export_tin_landxml(
                arcpy,
                p["input_tin"].valueAsText,
                Path(p["output_file"].valueAsText),
                surface_name=p["surface_name"].valueAsText,
                crs=p["crs"].valueAsText,
                linear_unit=units,
                z_unit=z_unit,
            )
        except ValueError as exc:
            messages.addErrorMessage(str(exc))
            return
        if z_unit and z_unit != units:
            messages.addMessage(
                f"Converted TIN elevations from {z_unit} to {units} by the "
                f"exact unit ratio.")
        messages.addMessage(f"Civil 3D LandXML TIN surface -> {output}")


class DownloadOpenTopoDEM(object):
    """Download OpenTopography DEM — resolve a Pro AOI to WGS84, fetch the
    DEM via the arcpy-free core (autogis.core.envmon.opentopo), then add the
    raster to the active map. arcpy is used only for AOI resolution and the
    map steps."""

    def __init__(self):
        self.label = "Download OpenTopography DEM"
        self.description = (
            "Download a DEM GeoTIFF from OpenTopography for an AOI (active "
            "map extent, a feature layer honoring any selection, or a manual "
            "WGS84 bbox) and optionally add it to the active map. Requires "
            "an OpenTopography API key ($OPENTOPOGRAPHY_API_KEY or the "
            "API-key parameter). Optionally reprojects horizontally and "
            "converts elevation cell values between meters, international "
            "feet, and US survey feet. Writes a provenance/citation .json "
            "sidecar.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        from autogis.core.envmon.opentopo import DEFAULT_DATASET, DEM_DATASETS
        parameters = [
            _param("dataset", "DEM dataset", "GPString",
                   default=DEFAULT_DATASET, domain=sorted(DEM_DATASETS)),
            _param("aoi_source", "AOI source", "GPString",
                   default="Active map extent",
                   domain=("Active map extent",
                           "Feature layer (selection if any)",
                           "Manual bbox")),
            _param("aoi_layer", "AOI feature layer", "GPFeatureLayer",
                   required=False),
            _param("manual_bbox", "Manual bbox (W S E N, WGS84)", "GPString",
                   required=False),
            _param("out_raster", "Output raster (.tif)", "DEFile",
                   direction="Output"),
            _param("api_key", "API key (blank = $OPENTOPOGRAPHY_API_KEY)",
                   "GPString", required=False),
            _param("add_to_map", "Add result to active map", "GPBoolean",
                   required=False, default=True),
            _param("reproject", "Reproject to map CRS (lossy resample)",
                   "GPBoolean", required=False, default=False),
            _param("convert_elevation", "Convert elevation values (Raster Calculator)",
                   "GPBoolean", required=False, default=False),
            _param("elevation_conversion", "Elevation unit conversion", "GPString",
                   required=False, default="Meters to international feet",
                   domain=tuple(toolbox_core.ELEVATION_CONVERSIONS)),
        ]
        parameters[-1].enabled = False
        return parameters

    def updateParameters(self, parameters):
        p = {q.name: q for q in parameters}
        p["elevation_conversion"].enabled = bool(
            p["convert_elevation"].value)

    # ---- arcpy AOI resolution (Pro-only; untestable headless) ------------
    @staticmethod
    def _to_wgs84(extent):
        projected = extent.projectAs(arcpy.SpatialReference(4326))
        return (projected.XMin, projected.YMin,
                projected.XMax, projected.YMax)

    def _resolve_aoi_wgs84(self, source, p):
        if source == "Manual bbox":
            parts = (p["manual_bbox"].valueAsText or "").split()
            if len(parts) != 4:
                raise ValueError(
                    "Manual bbox must be 'W S E N' in WGS84 decimal degrees.")
            west, south, east, north = (float(v) for v in parts)
            return (west, south, east, north)

        if source.startswith("Feature layer"):
            layer = p["aoi_layer"].value
            if layer is None:
                raise ValueError(
                    "AOI source is 'Feature layer' but no layer was chosen.")
            xmin = ymin = float("inf")
            xmax = ymax = float("-inf")
            sr = None
            # SearchCursor honors the layer's selection automatically, which
            # is why 'Selected features' needs no separate option.
            with arcpy.da.SearchCursor(layer, ["SHAPE@"]) as cursor:
                for (shape,) in cursor:
                    if shape is None:
                        continue
                    e = shape.extent
                    sr = sr or e.spatialReference
                    xmin, ymin = min(xmin, e.XMin), min(ymin, e.YMin)
                    xmax, ymax = max(xmax, e.XMax), max(ymax, e.YMax)
            if sr is None:
                raise ValueError("AOI layer has no (selected) features.")
            return self._to_wgs84(arcpy.Extent(xmin, ymin, xmax, ymax,
                                               spatial_reference=sr))

        # Active map extent (default)
        view = arcpy.mp.ArcGISProject("CURRENT").activeView
        if view is None or not hasattr(view, "camera"):
            raise ValueError(
                "No active map view — open a map, or choose another AOI source.")
        return self._to_wgs84(view.camera.getExtent())

    def execute(self, parameters, messages):
        from autogis.core.envmon.opentopo import download_dem
        p = {q.name: q for q in parameters}
        try:
            bbox = self._resolve_aoi_wgs84(
                p["aoi_source"].valueAsText or "Active map extent", p)
        except ValueError as err:
            messages.addErrorMessage(str(err))
            return

        out = Path(p["out_raster"].valueAsText)
        try:
            # overwrite=True: Pro's own output-parameter overwrite handling
            # already fronts this tool; the CLI keeps the strict guard.
            result = download_dem(
                p["dataset"].valueAsText, bbox=bbox, out_path=out,
                api_key=p["api_key"].valueAsText or None, overwrite=True)
        except (ValueError, RuntimeError, OSError) as err:
            messages.addErrorMessage(str(err))
            return
        _msg(messages, result.qa)
        if not result.bytes_written:
            return
        out = result.out_path
        p["out_raster"].value = str(out)
        messages.addMessage(
            f"Wrote {result.out_path} ({result.bytes_written:,} bytes) + "
            f"provenance sidecar {result.out_path.name}.json")

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        add_path = result.out_path
        if bool(p["reproject"].value) and active_map is not None:
            map_sr = active_map.spatialReference
            projected = out.with_name(
                f"{out.stem}_epsg{map_sr.factoryCode or 'map'}{out.suffix}")
            # BILINEAR (not the ProjectRaster NEAREST default) — a DEM is
            # continuous elevation; nearest-neighbour resampling stair-steps it.
            arcpy.management.ProjectRaster(
                str(out), str(projected), map_sr, "BILINEAR")
            add_path = projected
            messages.addMessage(f"Reprojected to {map_sr.name}: {projected}")
        if bool(p["convert_elevation"].value):
            conversion = (p["elevation_conversion"].valueAsText
                          or "Meters to international feet")
            try:
                add_path = toolbox_core.convert_raster_elevation_units(
                    arcpy, add_path, conversion)
            except ValueError as err:
                messages.addErrorMessage(str(err))
                return
            messages.addMessage(
                f"Converted elevation values ({conversion}): {add_path}")
            messages.addWarningMessage(
                "Elevation conversion changed raster cell values only; "
                "verify the output vertical coordinate system metadata.")
        if bool(p["add_to_map"].value) and active_map is not None:
            layer = active_map.addDataFromPath(str(add_path))
            view = aprx.activeView
            zoomed = view is not None and hasattr(view, "camera")
            if zoomed:
                view.camera.setExtent(view.getLayerExtent(layer))
            messages.addMessage(
                f"Added {add_path} to map '{active_map.name}'"
                + (" and zoomed to it." if zoomed else "."))
