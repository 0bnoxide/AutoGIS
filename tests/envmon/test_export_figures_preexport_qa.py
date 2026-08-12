"""export_figures QA and layout-selection seams — #463 item 2, #459.

`GetCount` raising on a required layer was caught by a bare `except: pass`, so
the gate silently did not run and preexport_qa still returned True. "We could
not check" was indistinguishable from "we checked and it was fine", and the
export proceeded either way.

The second half covers `export_layouts`' layout filter, where `if layout_names:`
read an explicitly empty selection as "no filter" and exported every layout in
the APRX — the #459 deliverable, reachable from a spec whose `layout_name` is
YAML null.

arcpy is mocked throughout — the seams under test are the QA branch and the
filter, not arcpy.
"""
import types
from pathlib import Path
from unittest.mock import MagicMock

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon import export_figures


def _layer(name, *, broken=False):
    return types.SimpleNamespace(name=name, isBroken=broken,
                                 supports=lambda _cap: True)


def _install(monkeypatch, layers, count):
    """Mock arcpy so GetCount either returns `count` or raises it."""
    arcpy = MagicMock()
    aprx = MagicMock()
    a_map = MagicMock()
    a_map.listLayers.return_value = layers
    aprx.listMaps.return_value = [a_map]
    arcpy.mp.ArcGISProject.return_value = aprx

    def get_count(_lyr):
        if isinstance(count, Exception):
            raise count
        return [str(count)]

    arcpy.management.GetCount.side_effect = get_count
    monkeypatch.setattr(export_figures, "_arcpy", lambda: arcpy)
    return arcpy


def _run(monkeypatch, layers, count, required=("MonitoringWells",)):
    _install(monkeypatch, layers, count)
    qa = QACollector()
    ok = export_figures.preexport_qa(Path("p.aprx"), required, qa)
    return ok, qa


def test_empty_required_layer_warns(monkeypatch):
    ok, qa = _run(monkeypatch, [_layer("MonitoringWells")], 0)
    assert ok is True  # a warning, not a block — unchanged behavior
    assert [r.category for r in qa.records] == ["required_layer_empty"]


def test_populated_required_layer_is_silent(monkeypatch):
    ok, qa = _run(monkeypatch, [_layer("MonitoringWells")], 12)
    assert ok is True and qa.records == []


def test_uncheckable_required_layer_is_reported_not_swallowed(monkeypatch):
    """The regression: a bare `except: pass` here meant a required layer whose
    count could not be taken produced no record at all."""
    ok, qa = _run(monkeypatch, [_layer("MonitoringWells")],
                  RuntimeError("ERROR 000732: dataset does not exist"))
    assert ok is True  # still non-blocking, like the empty-layer warning
    assert [r.category for r in qa.records] == ["required_layer_uncheckable"]
    rec = qa.records[0]
    assert rec.severity == SEV_WARNING
    assert "MonitoringWells" in rec.message      # names the layer
    assert "RuntimeError" in rec.message          # and why it could not check
    assert rec.recommended_action


def test_non_required_layer_is_never_counted(monkeypatch):
    """Only required layers are counted; an unrelated layer must not produce
    an 'uncheckable' record just because GetCount would raise."""
    ok, qa = _run(monkeypatch, [_layer("Basemap")],
                  RuntimeError("boom"))
    assert ok is True and qa.records == []


def test_broken_source_still_blocks(monkeypatch):
    """The blocking check above the gate is untouched."""
    ok, qa = _run(monkeypatch, [_layer("MonitoringWells", broken=True)], 0)
    assert ok is False
    assert [r.category for r in qa.records] == ["broken_data_source"]
    assert qa.records[0].severity == SEV_ERROR


# --- the layout filter itself: [] must mean "nothing", not "everything" (#459)

def _export_arcpy(monkeypatch, layout_names_in_aprx):
    """Mock an APRX with N layouts whose exportToPDF actually writes a file."""
    arcpy = MagicMock()
    aprx = MagicMock()
    a_map = MagicMock()
    a_map.listLayers.return_value = []          # preexport_qa finds nothing
    aprx.listMaps.return_value = [a_map]

    def _layout(name):
        lay = MagicMock()
        lay.name = name
        lay.exportToPDF.side_effect = (
            lambda path, **kw: Path(path).write_text("pdf", encoding="utf-8"))
        return lay

    aprx.listLayouts.return_value = [_layout(n) for n in layout_names_in_aprx]
    arcpy.mp.ArcGISProject.return_value = aprx
    monkeypatch.setattr(export_figures, "_arcpy", lambda: arcpy)
    return arcpy


def _export(monkeypatch, tmp_path, layout_names, in_aprx=("Fig A", "Fig B")):
    _export_arcpy(monkeypatch, in_aprx)
    qa = QACollector()
    written = export_figures.export_layouts(
        tmp_path / "p.aprx", tmp_path / "out", "{site_id}", {"site_id": "S"},
        qa, layout_names=layout_names)
    return written, qa


def test_none_layout_names_exports_every_layout(monkeypatch, tmp_path):
    """The pre-existing 'no filter' contract, pinned so the change below is
    visibly a narrowing of `None` only."""
    written, _ = _export(monkeypatch, tmp_path, None)
    assert [p.name for p in written] == ["S.pdf", "S_v2.pdf"]


def test_empty_layout_names_exports_nothing(monkeypatch, tmp_path):
    """An empty selection means 'no layout resolved'. Read as falsy it fell
    through to the no-filter branch and exported EVERY layout under one
    colliding stem — #459, reachable from a spec with a null layout_name."""
    written, _ = _export(monkeypatch, tmp_path, [])
    assert written == []


def test_named_layout_exports_only_that_layout(monkeypatch, tmp_path):
    written, qa = _export(monkeypatch, tmp_path, ["Fig B"])
    assert [p.name for p in written] == ["S.pdf"]
    assert qa.records == []


def test_unmatched_layout_name_reports_layout_missing(monkeypatch, tmp_path):
    """The ERROR that was unreachable while layout_names was always None."""
    written, qa = _export(monkeypatch, tmp_path, ["Nope"])
    assert written == []
    assert [r.category for r in qa.records] == ["layout_missing"]
    assert qa.records[0].severity == SEV_ERROR


def test_combine_pdf_merges_the_exported_pdfs(monkeypatch, tmp_path):
    """`combine_pdf` has no in-tree caller since the dead combined_pdf_name
    read was dropped (ADR-0127 §7 keeps it as a library seam). Pinned rather
    than left unexercised — an untested arcpy branch is how the QA-writer
    overflow shipped past a green suite in #464."""
    arcpy = _export_arcpy(monkeypatch, ("Fig A", "Fig B"))
    qa = QACollector()
    written = export_figures.export_layouts(
        tmp_path / "p.aprx", tmp_path / "out", "{site_id}", {"site_id": "S"},
        qa, layout_names=None, combine_pdf="Packet.pdf")

    arcpy.mp.PDFDocumentCreate.assert_called_once()
    pdoc = arcpy.mp.PDFDocumentCreate.return_value
    assert pdoc.appendPages.call_count == 2
    pdoc.saveAndClose.assert_called_once()
    assert written[-1].name == "Packet.pdf"
    assert [r.category for r in qa.records] == ["combined_pdf"]


def test_layout_missing_reports_the_name_the_operator_typed(monkeypatch, tmp_path):
    """The record iterated the lowered lookup key, so a spec saying
    "Wrong Name" produced "Requested layout 'wrong name' not in APRX." — and
    two names differing only by case collapsed into one record."""
    written, qa = _export(monkeypatch, tmp_path, ["Wrong Name", "WRONG NAME"])
    assert written == []
    # Matching is case-insensitive, so those two ARE one request: reported
    # once, with the first spelling, not the lowered key and not last-wins.
    assert [r.message for r in qa.records] == [
        "Requested layout 'Wrong Name' not in APRX."]


def test_layout_missing_reports_each_distinct_name_in_caller_order(
        monkeypatch, tmp_path):
    written, qa = _export(monkeypatch, tmp_path, ["Zulu", "Alpha"])
    assert written == []
    assert [r.message for r in qa.records] == [
        "Requested layout 'Zulu' not in APRX.",
        "Requested layout 'Alpha' not in APRX."]
