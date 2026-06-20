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
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..common.logging import get_logger
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

LOG = get_logger(__name__)

FORMATS = ("PDF", "PNG", "TIFF", "JPEG")


def _arcpy():
    import arcpy
    return arcpy


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
                except Exception:
                    pass
    del aprx
    return ok


def _versioned(path: Path, overwrite: bool) -> Path:
    if overwrite or not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem}_v{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


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
    layouts = aprx.listLayouts()
    if layout_names:
        wanted = {n.lower() for n in layout_names}
        layouts = [l for l in layouts if l.name.lower() in wanted]
        for n in wanted - {l.name.lower() for l in layouts}:
            qa.add(QARecord(severity=SEV_ERROR, category="layout_missing",
                            message=f"Requested layout {n!r} not in APRX."))
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
            out = _versioned(export_dir / f"{stem}{ext}", overwrite)
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
        combined = _versioned(export_dir / combine_pdf, overwrite)
        pdoc = arcpy.mp.PDFDocumentCreate(str(combined))
        for p in pdfs:
            pdoc.appendPages(str(p))
        pdoc.saveAndClose()
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
