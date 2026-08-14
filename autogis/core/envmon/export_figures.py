"""Export layouts to PDF/PNG/TIFF/JPEG with pre-export QA and registry.

Pre-export QA blocks (or warns) on:
* broken data sources (layer.isBroken)
* required layers with zero features after definition queries
* missing layout

Exports never overwrite silently: existing files are versioned with a
numeric suffix unless overwrite=True.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..common.logging import get_logger
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

LOG = get_logger(__name__)

FORMATS = ("PDF", "PNG", "TIFF", "JPEG")


from ...runtime.sessions import arcpy_env as _arcpy


def preexport_qa(aprx_path: Path, required_layers: Sequence[str],
                 qa: QACollector) -> bool:
    """Returns True if export may proceed (no broken sources)."""
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    ok = True
    req = {r.lower() for r in required_layers}
    for m in aprx.listMaps():
        for lyr in m.listLayers():
            if lyr.isBroken:
                qa.add(QARecord(severity=SEV_ERROR, category="broken_data_source",
                                message=f"Layer {lyr.name!r} has a broken data "
                                        "source; export blocked.",
                                recommended_action="Run data-source repathing."))
                ok = False
                continue
            if lyr.name.lower() in req and lyr.supports("DATASOURCE"):
                try:
                    n = int(arcpy.management.GetCount(lyr)[0])
                    if n == 0:
                        qa.add(QARecord(
                            severity=SEV_WARNING, category="required_layer_empty",
                            message=f"Required layer {lyr.name!r} draws zero "
                                    "features under the current definition "
                                    "query.",
                        ))
                except Exception as exc:
                    # "We could not check" must not read as "we checked and it
                    # was fine" — a bare pass here silently skipped the
                    # empty-required-layer gate and still returned ok (#463).
                    qa.add(QARecord(
                        severity=SEV_WARNING, category="required_layer_uncheckable",
                        message=f"Could not count features on required layer "
                                f"{lyr.name!r} ({type(exc).__name__}: {exc}); "
                                "the empty-layer check did not run for it.",
                        recommended_action="Open the APRX and confirm the "
                                           "layer draws features before "
                                           "trusting this figure.",
                    ))
    del aprx
    return ok


def versioned_path(path: Path, overwrite: bool) -> Path:
    """The module's no-silent-overwrite policy, as one function.

    Public because ``gen-map-series`` writes its cross-APRX combined appendix
    outside this module and must obey the same policy -- it did not, so the
    run versioned every intermediate figure and overwrote the one file the
    client actually receives (#471). One policy, one implementation.
    """
    if overwrite or not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem}_v{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _filter_layouts(layouts, layout_names, qa: QACollector) -> List:
    """Select the requested layouts and report any the APRX does not have.

    ``layout_names is None`` means "no filter"; an explicitly EMPTY list means
    "no layout resolved, export nothing" and must not be read as the former --
    that read is #459. First spelling wins and insertion order is kept, so two
    requests differing only by case report once, deterministically, in the
    order the caller listed them; and the record names the caller's spelling,
    not the lowered lookup key.

    Extracted because ``export_layouts`` was already past this repo's
    complexity threshold before this batch added another branch to it.
    """
    if layout_names is None:
        return layouts
    wanted: Dict[str, str] = {}
    for n in layout_names:
        wanted.setdefault(str(n).lower(), str(n))
    selected = [l for l in layouts if l.name.lower() in wanted]
    found = {l.name.lower() for l in selected}
    for key, original in wanted.items():
        if key not in found:
            qa.add(QARecord(severity=SEV_ERROR, category="layout_missing",
                            message=f"Requested layout {original!r} not in "
                                    "APRX."))
    return selected


def export_layouts(
    aprx_path: Path,
    export_dir: Path,
    filename_pattern: str,
    pattern_values: Dict[str, str],
    qa: QACollector,
    layout_names: Optional[Sequence[str]] = None,
    formats: Sequence[str] = ("PDF",),
    dpi: int = 300,
    required_layers: Sequence[str] = (),
    combine_pdf: Optional[str] = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> List[Path]:
    """Export each layout in every requested format; returns written paths."""
    arcpy = _arcpy()
    for f in formats:
        if f not in FORMATS:
            raise ValueError(f"Unsupported export format {f!r}; use {FORMATS}")

    if not preexport_qa(aprx_path, required_layers, qa):
        qa.add(QARecord(severity=SEV_ERROR, category="export_blocked",
                        message="Export blocked by pre-export QA."))
        return []

    export_dir.mkdir(parents=True, exist_ok=True)
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    layouts = _filter_layouts(aprx.listLayouts(), layout_names, qa)
    written: List[Path] = []
    pdfs: List[Path] = []
    for lay in layouts:
        vals = dict(pattern_values)
        vals.setdefault("layout", lay.name)
        try:
            stem = filename_pattern.format(**vals)
        except KeyError as exc:
            qa.add(QARecord(severity=SEV_ERROR, category="filename_pattern_error",
                            message=f"Pattern key {exc} missing; using layout "
                                    "name."))
            stem = lay.name
        for fmt in formats:
            ext = {"PDF": ".pdf", "PNG": ".png", "TIFF": ".tif",
                   "JPEG": ".jpg"}[fmt]
            out = versioned_path(export_dir / f"{stem}{ext}", overwrite)
            if dry_run:
                LOG.info("[dry-run] would export %s -> %s", lay.name, out)
                continue
            if fmt == "PDF":
                lay.exportToPDF(str(out), resolution=dpi,
                                image_quality="BEST", embed_fonts=True)
                pdfs.append(out)
            elif fmt == "PNG":
                lay.exportToPNG(str(out), resolution=dpi)
            elif fmt == "TIFF":
                lay.exportToTIFF(str(out), resolution=dpi)
            else:
                lay.exportToJPEG(str(out), resolution=dpi)
            if not out.exists():
                qa.add(QARecord(severity=SEV_ERROR, category="export_file_missing",
                                message=f"Export reported success but {out} "
                                        "does not exist."))
            else:
                written.append(out)
    del aprx

    if combine_pdf and pdfs and not dry_run:
        combined = versioned_path(export_dir / combine_pdf, overwrite)
        # Build beside the target, publish atomically with os.replace (same
        # pattern as dashboard_data_mart). PDFDocumentCreate needs a free path
        # (Esri's own example os.remove()s an existing file first), but
        # unlinking the live target before the multi-step build meant one bad
        # appendPages destroyed the previous deliverable with overwrite=True
        # (#500). No-op difference when versioning already chose a free name.
        tmp = combined.with_name(combined.name + ".tmp.pdf")
        tmp.unlink(missing_ok=True)
        try:
            pdoc = arcpy.mp.PDFDocumentCreate(str(tmp))
            for p in pdfs:
                pdoc.appendPages(str(p))
            pdoc.saveAndClose()
            os.replace(tmp, combined)
        finally:
            tmp.unlink(missing_ok=True)
        written.append(combined)
        qa.add(QARecord(severity=SEV_INFO, category="combined_pdf",
                        message=f"Combined PDF written: {combined.name} "
                                f"({len(pdfs)} figures)."))
    return written


def register_exports(gdb, written: Sequence[Path], site_id: str,
                     event_date: str, figure_spec_id: str,
                     qa: QACollector) -> None:
    arcpy = _arcpy()
    table = str(gdb / "Env_FigureRegistry")
    if not arcpy.Exists(table):
        qa.add(QARecord(severity=SEV_WARNING, category="registry_missing",
                        message="Env_FigureRegistry not found; exports not "
                                "registered."))
        return
    stamp = _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    fields = ["SiteID", "EventDate", "FigureSpecID", "ExportPath",
              "ExportTimestamp", "Status"]
    with arcpy.da.InsertCursor(table, fields) as cur:
        for p in written:
            cur.insertRow([site_id, event_date, figure_spec_id,
                           str(p), stamp, "EXPORTED"])
