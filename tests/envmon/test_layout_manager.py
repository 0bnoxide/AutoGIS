"""Tests for layout_manager's Tool 5.8 surface: the arcpy-free YAML values
loader, update_layout_text (arcpy mocked), and the update-layout-text CLI."""
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector, SEV_WARNING
from autogis.core.envmon.layout_manager import load_layout_text_yaml


# --- load_layout_text_yaml (arcpy-free) ---

def _yaml(tmp_path, text):
    p = tmp_path / "values.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_flat_mapping(tmp_path):
    p = _yaml(tmp_path, "Title: H281 Q2 Report\nEventDate: 2026-07-02\n")
    assert load_layout_text_yaml(p) == {
        "Title": "H281 Q2 Report", "EventDate": "2026-07-02"}


def test_load_list_form(tmp_path):
    p = _yaml(tmp_path,
              "- element_name: Title\n  text: Report Title\n"
              "- element_name: EventID\n  text: Q2-2026\n")
    assert load_layout_text_yaml(p) == {
        "Title": "Report Title", "EventID": "Q2-2026"}


def test_load_coerces_values_to_str(tmp_path):
    p = _yaml(tmp_path, "FigureNumber: 3\n")
    assert load_layout_text_yaml(p) == {"FigureNumber": "3"}


def test_load_empty_file_returns_empty_dict(tmp_path):
    assert load_layout_text_yaml(_yaml(tmp_path, "")) == {}


def test_load_scalar_raises(tmp_path):
    with pytest.raises(ValueError, match="Unexpected YAML structure"):
        load_layout_text_yaml(_yaml(tmp_path, "just a string"))


def test_load_list_missing_keys_raises(tmp_path):
    with pytest.raises(ValueError, match="element_name"):
        load_layout_text_yaml(_yaml(tmp_path, "- text: no name here\n"))


# --- update_layout_text (arcpy mocked, same pattern as
#     test_manage_callout_overrides) ---

def _element(name, text=""):
    return types.SimpleNamespace(name=name, text=text)


def _mock_arcpy(layouts):
    arcpy = MagicMock()
    aprx = MagicMock()
    aprx.listLayouts.return_value = layouts
    arcpy.mp.ArcGISProject.return_value = aprx
    return arcpy, aprx


def _layout(name, elements):
    lay = types.SimpleNamespace(name=name)
    lay.listElements = lambda kind: elements
    return lay


def test_update_sets_named_elements_and_resolves_placeholders(tmp_path):
    title = _element("Title", "old")
    footer = _element("Footer", "Site {{SiteName}} — {{Missing}}")
    arcpy, aprx = _mock_arcpy([_layout("L1", [title, footer])])
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        from autogis.core.envmon.layout_manager import update_layout_text
        update_layout_text(tmp_path / "x.aprx", "L1",
                           {"Title": "New Title", "SiteName": "H281"}, qa)
    assert title.text == "New Title"
    assert footer.text == "Site H281 — {{Missing}}"
    assert any(r.category == "unresolved_placeholder" for r in qa.records)
    aprx.save.assert_called_once()


def test_update_dry_run_does_not_save(tmp_path):
    el = _element("Title", "old")
    arcpy, aprx = _mock_arcpy([_layout("L1", [el])])
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        from autogis.core.envmon.layout_manager import update_layout_text
        update_layout_text(tmp_path / "x.aprx", "L1", {"Title": "New"}, qa,
                           dry_run=True)
    assert el.text == "New"
    aprx.save.assert_not_called()


def test_update_missing_layout_is_qa_error(tmp_path):
    arcpy, aprx = _mock_arcpy([_layout("Other", [])])
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        from autogis.core.envmon.layout_manager import update_layout_text
        update_layout_text(tmp_path / "x.aprx", "Nope", {"Title": "x"}, qa)
    assert any(r.category == "layout_missing" and r.severity == "ERROR"
               for r in qa.records)
    aprx.save.assert_not_called()


# --- set_layer_visibility (issue #345: never called qa, so a typo'd/renamed
#     layer name silently failed to toggle visibility) ---

def _layer(name, visible=True):
    return types.SimpleNamespace(name=name, visible=visible)


def _mock_arcpy_maps(maps):
    arcpy = MagicMock()
    aprx = MagicMock()
    aprx.listMaps.return_value = maps
    arcpy.mp.ArcGISProject.return_value = aprx
    return arcpy, aprx


def _map(layers):
    m = types.SimpleNamespace()
    m.listLayers = lambda: layers
    return m


def test_set_layer_visibility_toggles_matched_layers(tmp_path):
    wells = _layer("Wells", visible=True)
    plume = _layer("Plume", visible=False)
    arcpy, aprx = _mock_arcpy_maps([_map([wells, plume])])
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        from autogis.core.envmon.layout_manager import set_layer_visibility
        set_layer_visibility(tmp_path / "x.aprx", ["Plume"], ["Wells"], qa)
    assert plume.visible is True
    assert wells.visible is False
    assert qa.records == []
    aprx.save.assert_called_once()


def test_set_layer_visibility_warns_on_missing_layer(tmp_path):
    wells = _layer("Wells")
    arcpy, aprx = _mock_arcpy_maps([_map([wells])])
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        from autogis.core.envmon.layout_manager import set_layer_visibility
        set_layer_visibility(tmp_path / "x.aprx", ["Wells"],
                             ["Plume_Boundary_2026"], qa)
    warnings = [r for r in qa.records if r.category == "visibility_layer_missing"]
    assert len(warnings) == 1
    assert "Plume_Boundary_2026" in warnings[0].message
    assert warnings[0].severity == SEV_WARNING


# --- CLI wiring ---

def test_update_layout_text_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "update-layout-text" in result.output


def test_update_layout_text_without_arcpy_is_clean_guard(tmp_path):
    aprx = tmp_path / "p.aprx"
    aprx.write_text("", encoding="utf-8")
    values = _yaml(tmp_path, "Title: T\n")
    result = CliRunner().invoke(autogis, [
        "envmon", "update-layout-text",
        "--aprx", str(aprx), "--values", str(values),
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
