"""preexport_qa's empty-required-layer gate — #463 item 2.

`GetCount` raising on a required layer was caught by a bare `except: pass`, so
the gate silently did not run and preexport_qa still returned True. "We could
not check" was indistinguishable from "we checked and it was fine", and the
export proceeded either way. arcpy is mocked — the seam under test is the QA
branch, not arcpy.
"""
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
