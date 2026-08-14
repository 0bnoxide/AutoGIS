"""APRX layout management.

Operates on a COPY of the template APRX (the template is never
modified). All layout/text/extent edits happen on the copy, which is
then used for export.
"""

from __future__ import annotations

import math
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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
    # YAML mapping keys are not necessarily strings: an unquoted `2026:` or
    # `no:` layer name arrives as int/bool. Such a key can never equal
    # lyr.name, so the query was silently never applied -- and then
    # sorted(missing), the reporting that exists to catch exactly that, raised
    # TypeError comparing str to int, out of the CLI and the Pro tool with no
    # QA record (#474). Coercing at the boundary fixes both halves at once,
    # and is the rule _name_list already applies to the sibling spec fields.
    raw_queries = layer_queries or {}
    layer_queries = {str(k): v for k, v in raw_queries.items()}
    if len(layer_queries) < len(raw_queries):
        # `2026:` and `"2026":` in one mapping survive YAML as distinct keys
        # and collapse under str(). Report rather than drop silently -- that
        # last-writer-wins collapse is the same failure this batch refuses for
        # a duplicate figure_spec_id (#470), and here the operator would
        # otherwise get a figure whose def query is simply not the one the
        # spec's last line asked for.
        counts = Counter(str(k) for k in raw_queries)
        collapsed = sorted(name for name, n in counts.items() if n > 1)
        qa.add(QARecord(
            severity=SEV_WARNING, category="defquery_key_collision",
            message=f"Figure spec layer_definition_queries has keys that "
                    f"collide once coerced to text ({', '.join(collapsed)}); "
                    "only the last query for each survived.",
            recommended_action="Quote the layer names so each appears once."))
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


def _select_layouts(aprx, layout_name: Optional[str]) -> List:
    """Layouts matching ``layout_name``, compared case-insensitively.

    One rule for every consumer of a resolved layout name. ``export_layouts``
    has always lowercased; this module compared exactly. That only became
    reachable once ``prepare_figure_aprx`` started passing a real name to both
    -- a case-mismatched spec then EXPORTED the layout while silently skipping
    its text and extent, shipping an unconfigured figure alongside an ERROR
    claiming the layout was not in the APRX.
    """
    if not layout_name:
        return aprx.listLayouts()
    want = layout_name.lower()
    return [l for l in aprx.listLayouts() if l.name.lower() == want]


def _name_list(value, field: str, qa: QACollector) -> List[str]:
    """Coerce a spec list-of-names to a real list.

    Tests for a list rather than enumerating scalar types, so every shape a
    YAML scalar can produce takes the warned single-value path. Special-casing
    ``str`` alone left `visible_layers: 2026` and `: no` (bool) raising a raw
    TypeError, and a mapping silently iterating as its KEYS -- which happens to
    work until the keys are not layer names.
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        qa.add(QARecord(
            severity=SEV_WARNING, category="spec_value_not_a_list",
            message=f"Figure spec {field} is the single value {value!r} "
                    f"({type(value).__name__}), not a list; treating it as a "
                    "one-item list.",
            recommended_action=f"Write {field} as a YAML list."))
        return [str(value)]
    return [str(v) for v in value]


def _as_text_map(raw) -> Dict[str, str]:
    """Mapping form of a layout-text block -> ``{element_name: text}``.

    Shared by the Tool 5.8 values file (:func:`load_layout_text_yaml`) and a
    figure spec's ``layout_text:``, which had drifted to different rules inside
    this one module. The values file ALSO accepts a list of
    ``{element_name, text}`` dicts; that is an affordance of a hand-written
    file format and stays in its loader rather than widening the figure spec to
    a shape no shipped spec uses. One grammar per file kind is still one
    grammar.

    Raises ValueError naming the shape; callers decide whether that is fatal
    (the values file) or a QA warning (the figure spec).
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    raise ValueError(
        f"expected a mapping {{ElementName: text}}, got {type(raw).__name__}")


def _text_map(value, field: str, qa: QACollector) -> Dict[str, str]:
    """Figure-spec side of :func:`_as_text_map`: a bad shape is a QA warning,
    not a crash. A YAML list here used to raise a raw
    `ValueError: dictionary update sequence element #0` out of the CLI."""
    try:
        return _as_text_map(value)
    except ValueError as exc:
        qa.add(QARecord(
            severity=SEV_WARNING, category="spec_value_not_a_mapping",
            message=f"{field}: {exc}; ignored.",
            recommended_action=f"Write {field} as a YAML mapping of layout "
                               "element name to text."))
        return {}


def _buffer_pct(value, qa: QACollector) -> float:
    """Coerce extent_buffer_pct. Neither it nor layout_text is FIGURE_REQUIRED,
    so a spec carrying `extent_buffer_pct:` (null) or "5%" loads clean and used
    to crash the CLI with a raw TypeError/ValueError at this trust boundary."""
    if value is None:
        return 5.0
    pct = None
    # bool before float(): YAML `yes`/`no` are True/False, and float(True) is
    # 1.0 -- a silent 1% pad, or 0% for `no`. _name_list already treats a YAML
    # bool as a first-class hazard; both helpers must.
    if not isinstance(value, bool):
        try:
            pct = float(value)
        except (TypeError, ValueError):
            pct = None
    # float() happily accepts nan/inf, and a negative pads inward: -100 makes
    # XMin_new == XMax_old, an inverted extent and a silently garbage figure.
    if pct is None or not math.isfinite(pct) or pct < 0:
        qa.add(QARecord(
            severity=SEV_WARNING, category="bad_extent_buffer_pct",
            message=f"extent_buffer_pct {value!r} is not a finite "
                    "non-negative number; using 5.",
            recommended_action="Set extent_buffer_pct to a plain number >= 0."))
        return 5.0
    return pct


def set_layer_visibility(aprx_path: Path, visible: Sequence[str],
                         hidden: Sequence[str], qa: QACollector) -> None:
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    vis = {v.lower(): v for v in _name_list(visible, "visible_layers", qa)}
    hid = {h.lower(): h for h in _name_list(hidden, "hidden_layers", qa)}
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

    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        # A wrong *shape* already gets a message naming the file and the
        # accepted forms; a wrong *character* escaped as a raw ParserError
        # traceback out of `envmon update-layout-text` (#474). One file, one
        # class of mistake, one kind of answer -- the trust-boundary
        # convention _load_json_option sets in cli.py.
        raise ValueError(
            f"Could not parse values YAML {path}: {exc}") from None
    if isinstance(raw, list):
        try:
            return {str(e["element_name"]): str(e["text"]) for e in raw}
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"List-form values YAML {path} needs 'element_name' and "
                f"'text' keys on every entry ({exc!r}).") from exc
    try:
        return _as_text_map(raw)
    except ValueError as exc:
        raise ValueError(
            f"Unexpected YAML structure in {path}: {exc}, or a list of "
            "{element_name, text} dicts.") from None


def update_layout_text(
    aprx_path: Path,
    layout_name: Optional[str],
    text_values: Dict[str, str],
    qa: QACollector,
    *,
    dry_run: bool = False,
) -> None:
    """Set layout text elements by element name; then substitute any
    {{placeholder}} tokens in remaining text elements. ``layout_name`` is
    matched case-insensitively (``None`` = every layout). Unresolved
    placeholders raise a QA warning (the figure should not ship with
    template tokens visible). ``dry_run`` reports without saving the APRX."""
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    layouts = _select_layouts(aprx, layout_name)
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


def prepare_figure_aprx(
    template: Path,
    working_dir: Path,
    tag: str,
    gdb: Path,
    site_id: str,
    event: str,
    spec,
    qa: QACollector,
    *,
    layout_text: Optional[Dict[str, str]] = None,
) -> Tuple[Path, List[str]]:
    """Run the full figure-preparation chain on a copy of ``template``.

    Copies the template APRX, repaths its data sources to ``gdb``, applies the
    spec's definition queries, sets layer visibility, stamps layout text and
    zooms to the boundary layer. Returns ``(working_aprx, layout_names)`` where
    ``layout_names`` is ready to hand to
    :func:`~autogis.core.envmon.export_figures.export_layouts`.

    This exists so ``ExportFigures`` (.pyt) and ``gen-map-series`` (CLI) share
    one chain. They previously carried separate copies of it and had drifted:
    the CLI omitted visibility, layout text and extent entirely (#462), and
    *both* selected layouts with ``spec["layouts"]`` — a key no figure spec
    defines — so ``layout_names`` was always ``None`` and every export emitted
    every layout in the APRX, unconfigured, colliding on one filename stem
    (#459). The schema key is the singular ``layout_name``, which is in
    ``FIGURE_REQUIRED``; resolving it here keeps that fix in one place.

    ``spec`` is duck-typed on ``.get()`` / ``.figure_spec_id`` (a
    ``FigureSpec``) so this module keeps no config dependency.
    """
    work = copy_template_aprx(template, working_dir, tag)
    update_aprx_data_sources(work, gdb, qa)

    lq = spec.get("layer_definition_queries", {})
    if lq:
        apply_figure_definition_queries(
            work, site_id, event, spec.figure_spec_id,
            spec.get("map_type", "GW_ANALYTICAL"), lq, qa)

    set_layer_visibility(work, spec.get("visible_layers", []),
                         spec.get("hidden_layers", []), qa)

    # FIGURE_REQUIRED is a key-PRESENCE check (config._require), so a spec with
    # `layout_name:` (YAML null) or an empty string loads clean. Returning None
    # for those would put us straight back in #459 -- no filter, every layout in
    # the APRX exported under one colliding stem -- with no QA record at all.
    # An empty selection blocks the export the same way a wrong name does.
    raw = spec.get("layout_name")
    layout_name = str(raw).strip() if raw is not None else ""
    if not layout_name:
        qa.add(QARecord(
            severity=SEV_ERROR, category="layout_name_missing",
            message="Figure spec declares no layout_name; cannot choose which "
                    "layout to configure and export.",
            recommended_action="Set layout_name in the figure spec to the "
                               "template APRX layout to export."))
        # Short-circuit: with no layout resolved, configuring means stamping
        # text on and saving EVERY layout in the working APRX -- work whose
        # output is then never exported, plus placeholder warnings for layouts
        # that cannot ship.
        return work, []

    text = _text_map(layout_text, "site default_layout_text", qa)
    text.update(_text_map(spec.get("layout_text"), "figure layout_text", qa))
    text.setdefault("EventDate", event)
    update_layout_text(work, layout_name, text, qa)

    boundary = spec.get("extent_boundary_layer")
    if boundary:
        zoom_to_boundary(work, layout_name, boundary,
                         _buffer_pct(spec.get("extent_buffer_pct"), qa), qa)

    return work, [layout_name]


def zoom_to_boundary(aprx_path: Path, layout_name: Optional[str],
                     boundary_layer: str, buffer_pct: float,
                     qa: QACollector) -> None:
    arcpy = _arcpy()
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    layouts = _select_layouts(aprx, layout_name)
    if not layouts:
        # An empty list here used to be a silent no-op: the figure shipped with
        # the template's saved extent and nothing said so.
        qa.add(QARecord(severity=SEV_ERROR, category="layout_missing",
                        message=f"Layout {layout_name!r} not found in APRX; "
                                "extent not zoomed to the site boundary."))
        del aprx
        return
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
