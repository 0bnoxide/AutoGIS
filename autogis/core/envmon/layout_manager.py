"""APRX layout management.

Operates on a COPY of the template APRX (the template is never
modified). All layout/text/extent edits happen on the copy, which is
then used for export.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..common.logging import get_logger
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

LOG = get_logger(__name__)

PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")


from ...runtime.sessions import arcpy_env as _arcpy


def copy_template_aprx(template: Path, working_dir: Path, tag: str) -> Path:
    if not template.exists():
        raise FileNotFoundError(
            f"Template APRX not found: {template}. Place the site template "
            "in templates/aprx/ and reference it from the figure spec.")
    working_dir.mkdir(parents=True, exist_ok=True)
    dest = working_dir / f"{template.stem}__{tag}.aprx"
    shutil.copy2(template, dest)
    LOG.info("Template %s copied to %s (template untouched).", template.name, dest)
    return dest


def update_aprx_data_sources(aprx_path: Path, gdb: Path, qa: QACollector) -> int:
    """Repath every GDB-backed layer/table to *gdb*. Returns layers updated."""
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    n = 0
    for m in aprx.listMaps():
        for lyr in m.listLayers():
            if not lyr.supports("CONNECTIONPROPERTIES") or lyr.connectionProperties is None:
                continue
            cp = lyr.connectionProperties
            try:
                new_cp = dict(cp)
                conn = dict(new_cp.get("connection_info", {}))
                if "database" in conn:
                    conn["database"] = str(gdb)
                    new_cp["connection_info"] = conn
                    lyr.updateConnectionProperties(cp, new_cp,
                                                   auto_update_joins_and_relates=True,
                                                   validate=False)
                    n += 1
            except Exception as exc:
                qa.add(QARecord(severity=SEV_WARNING, category="repath_failed",
                                message=f"Layer {lyr.name!r}: repath failed ({exc})."))
        for tbl in m.listTables():
            try:
                cp = tbl.connectionProperties
                if cp:
                    new_cp = dict(cp)
                    conn = dict(new_cp.get("connection_info", {}))
                    if "database" in conn:
                        conn["database"] = str(gdb)
                        new_cp["connection_info"] = conn
                        tbl.updateConnectionProperties(cp, new_cp, validate=False)
                        n += 1
            except Exception as exc:
                qa.add(QARecord(severity=SEV_WARNING, category="repath_failed",
                                message=f"Table {tbl.name!r}: repath failed ({exc})."))
    aprx.save()
    del aprx
    return n


def apply_figure_definition_queries(
    aprx_path: Path,
    site_id: str,
    event_date: str,
    figure_spec_id: str,
    map_type: str,
    layer_queries: Dict[str, str],
    qa: QACollector,
) -> None:
    """Apply def queries; *layer_queries* maps layer name -> query template
    with {site_id} {event_date} {figure_spec_id} {map_type} placeholders."""
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    fmt = dict(site_id=site_id, event_date=event_date,
               figure_spec_id=figure_spec_id, map_type=map_type)
    applied = set()
    for m in aprx.listMaps():
        for lyr in m.listLayers():
            if lyr.name in layer_queries and lyr.supports("DEFINITIONQUERY"):
                lyr.definitionQuery = layer_queries[lyr.name].format(**fmt)
                applied.add(lyr.name)
    missing = set(layer_queries) - applied
    for name in sorted(missing):
        qa.add(QARecord(severity=SEV_WARNING, category="defquery_layer_missing",
                        message=f"Definition query target layer {name!r} not "
                                "found in APRX."))
    aprx.save()
    del aprx


def set_layer_visibility(aprx_path: Path, visible: Sequence[str],
                         hidden: Sequence[str], qa: QACollector) -> None:
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    vis = {v.lower(): v for v in visible}
    hid = {h.lower(): h for h in hidden}
    matched = set()
    for m in aprx.listMaps():
        for lyr in m.listLayers():
            n = lyr.name.lower()
            if n in vis:
                lyr.visible = True
                matched.add(n)
            elif n in hid:
                lyr.visible = False
                matched.add(n)
    missing = (set(vis) | set(hid)) - matched
    for n in sorted(missing):
        original = vis.get(n, hid.get(n, n))
        qa.add(QARecord(severity=SEV_WARNING, category="visibility_layer_missing",
                        message=f"Layer {original!r} requested for visibility "
                                "toggle not found in APRX; figure may render "
                                "with an unexpected layer visible or hidden."))
    aprx.save()
    del aprx


def load_layout_text_yaml(path: Path) -> Dict[str, str]:
    """Load a Tool 5.8 values file into the ``text_values`` dict that
    ``update_layout_text`` expects. Arcpy-free.

    Accepted YAML shapes:
    - flat mapping:  ``{ElementName: "new text", ...}``
    - list of dicts: ``[{element_name: ..., text: ...}, ...]``
    """
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        try:
            return {str(e["element_name"]): str(e["text"]) for e in raw}
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"List-form values YAML {path} needs 'element_name' and "
                f"'text' keys on every entry ({exc!r}).")
    raise ValueError(
        f"Unexpected YAML structure in {path}: expected a mapping "
        f"{{ElementName: text}} or a list of {{element_name, text}} dicts, "
        f"got {type(raw).__name__}.")


def update_layout_text(
    aprx_path: Path,
    layout_name: Optional[str],
    text_values: Dict[str, str],
    qa: QACollector,
    *,
    dry_run: bool = False,
) -> None:
    """Set layout text elements by element name; then substitute any
    {{placeholder}} tokens in remaining text elements. Unresolved
    placeholders raise a QA warning (the figure should not ship with
    template tokens visible). ``dry_run`` reports without saving the APRX."""
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    layouts = ([l for l in aprx.listLayouts() if l.name == layout_name]
               if layout_name else aprx.listLayouts())
    if not layouts:
        qa.add(QARecord(severity=SEV_ERROR, category="layout_missing",
                        message=f"Layout {layout_name!r} not found in APRX."))
        del aprx
        return
    for lay in layouts:
        for el in lay.listElements("TEXT_ELEMENT"):
            if el.name in text_values:
                el.text = text_values[el.name]
                continue
            if el.text and PLACEHOLDER_RE.search(el.text):
                def sub(mt):
                    key = mt.group(1)
                    if key in text_values:
                        return text_values[key]
                    qa.add(QARecord(
                        severity=SEV_WARNING, category="unresolved_placeholder",
                        message=f"Layout {lay.name!r} element {el.name!r}: "
                                f"placeholder {{{{{key}}}}} has no value.",
                    ))
                    return mt.group(0)
                el.text = PLACEHOLDER_RE.sub(sub, el.text)
    if not dry_run:
        aprx.save()
    del aprx


def zoom_to_boundary(aprx_path: Path, layout_name: Optional[str],
                     boundary_layer: str, buffer_pct: float,
                     qa: QACollector) -> None:
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    layouts = ([l for l in aprx.listLayouts() if l.name == layout_name]
               if layout_name else aprx.listLayouts())
    for lay in layouts:
        for mf in lay.listElements("MAPFRAME_ELEMENT"):
            target = None
            for lyr in mf.map.listLayers():
                if lyr.name.lower() == boundary_layer.lower():
                    target = lyr
                    break
            if target is None:
                qa.add(QARecord(severity=SEV_WARNING, category="boundary_layer_missing",
                                message=f"Boundary layer {boundary_layer!r} not "
                                        f"in map frame {mf.name!r}; extent "
                                        "unchanged."))
                continue
            ext = mf.getLayerExtent(target, True, True)
            w = ext.XMax - ext.XMin
            h = ext.YMax - ext.YMin
            pad_x = w * buffer_pct / 100.0
            pad_y = h * buffer_pct / 100.0
            new_ext = arcpy.Extent(ext.XMin - pad_x, ext.YMin - pad_y,
                                   ext.XMax + pad_x, ext.YMax + pad_y)
            mf.camera.setExtent(new_ext)
    aprx.save()
    del aprx
