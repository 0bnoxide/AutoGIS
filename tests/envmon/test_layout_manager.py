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


def test_malformed_yaml_raises_valueerror_not_parsererror(tmp_path):
    """A wrong *shape* got a message naming the file; a wrong *character*
    escaped as a raw yaml.ParserError traceback out of the CLI (#474). One
    file, one class of mistake, one kind of answer."""
    p = _yaml(tmp_path, 'Title: "unclosed\nEventDate: [1, 2\n')
    with pytest.raises(ValueError, match="Could not parse values YAML"):
        load_layout_text_yaml(p)


def test_non_string_defquery_key_applies_and_reports(tmp_path):
    """`layer_definition_queries: {2026: ...}` is an ordinary YAML mistake --
    an unquoted layer name arrives as an int. The int could never equal
    lyr.name, so the query was silently never applied, and then sorted(missing)
    -- the reporting that exists to catch exactly that -- raised TypeError
    comparing str to int, out of the CLI with no QA record (#474)."""
    from autogis.core.envmon.layout_manager import (
        apply_figure_definition_queries)

    lyr = types.SimpleNamespace(name="2026", definitionQuery="",
                                supports=lambda _cap: True)
    arcpy = MagicMock()
    aprx = MagicMock()
    a_map = MagicMock()
    a_map.listLayers.return_value = [lyr]
    aprx.listMaps.return_value = [a_map]
    arcpy.mp.ArcGISProject.return_value = aprx
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        apply_figure_definition_queries(
            tmp_path / "x.aprx", "H281", "2026-07-02", "SPEC", "GW",
            {2026: "SiteID = '{site_id}'", "Absent_Layer": "1=1"}, qa)
    # the coerced key matches the layer, so the query actually lands...
    assert lyr.definitionQuery == "SiteID = 'H281'"
    # ...and the genuinely-absent layer is reported, not swallowed by a crash
    assert [r.category for r in qa.records] == ["defquery_layer_missing"]
    assert "Absent_Layer" in qa.records[0].message


def test_defquery_keys_colliding_under_str_are_reported(tmp_path):
    """`2026:` and `"2026":` survive YAML as distinct keys and collapse under
    str(). Dropping one silently is the same last-writer-wins collapse this
    batch refuses for a duplicate figure_spec_id (gitar review, PR #494)."""
    from autogis.core.envmon.layout_manager import (
        apply_figure_definition_queries)

    lyr = types.SimpleNamespace(name="2026", definitionQuery="",
                                supports=lambda _cap: True)
    arcpy = MagicMock()
    aprx = MagicMock()
    a_map = MagicMock()
    a_map.listLayers.return_value = [lyr]
    aprx.listMaps.return_value = [a_map]
    arcpy.mp.ArcGISProject.return_value = aprx
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        apply_figure_definition_queries(
            tmp_path / "x.aprx", "H281", "2026-07-02", "SPEC", "GW",
            {2026: "SiteID = '{site_id}'", "2026": "1=1"}, qa)
    collisions = [r for r in qa.records
                  if r.category == "defquery_key_collision"]
    assert len(collisions) == 1
    assert "2026" in collisions[0].message


def test_defquery_collision_warning_names_only_colliding_keys(tmp_path):
    """A non-string key that does NOT collide (True -> "True") must not be
    named in the collision warning; only truly colliding names appear (#499)."""
    from autogis.core.envmon.layout_manager import (
        apply_figure_definition_queries)

    lyr = types.SimpleNamespace(name="2026", definitionQuery="",
                                supports=lambda _cap: True)
    arcpy = MagicMock()
    aprx = MagicMock()
    a_map = MagicMock()
    a_map.listLayers.return_value = [lyr]
    aprx.listMaps.return_value = [a_map]
    arcpy.mp.ArcGISProject.return_value = aprx
    qa = QACollector()
    with patch("autogis.core.envmon.layout_manager._arcpy", return_value=arcpy):
        apply_figure_definition_queries(
            tmp_path / "x.aprx", "H281", "2026-07-02", "SPEC", "GW",
            {2026: "a", "2026": "b", True: "c"}, qa)
    collisions = [r for r in qa.records
                  if r.category == "defquery_key_collision"]
    assert len(collisions) == 1
    assert "2026" in collisions[0].message
    assert "True" not in collisions[0].message


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


# --- prepare_figure_aprx: the shared ExportFigures chain (#459, #462) ---

def _chain_recorder(monkeypatch):
    """Replace every arcpy-touching step with a recorder.

    The defect under test is wiring, not arcpy: the .pyt and the CLI carried
    separate copies of this chain and had drifted apart (#462), and both
    selected layouts with a spec key that does not exist (#459).
    """
    from autogis.core.envmon import layout_manager as lm

    calls = []

    def rec(name, ret=None):
        def _f(*a, **kw):
            calls.append((name, a, kw))
            return ret
        return _f

    work = Path("/work/fig.aprx")
    monkeypatch.setattr(lm, "copy_template_aprx", rec("copy", work))
    monkeypatch.setattr(lm, "update_aprx_data_sources", rec("repath"))
    monkeypatch.setattr(lm, "apply_figure_definition_queries", rec("defquery"))
    monkeypatch.setattr(lm, "set_layer_visibility", rec("visibility"))
    monkeypatch.setattr(lm, "update_layout_text", rec("text"))
    monkeypatch.setattr(lm, "zoom_to_boundary", rec("zoom"))
    return calls, work


def _spec(**over):
    from autogis.core.common.config import FigureSpec
    data = {
        "figure_spec_id": "FS1", "layout_name": "GW Analytical Layout",
        "layer_definition_queries": {"Env_CalloutBoxes": "1=1"},
        "visible_layers": ["MonitoringWells"], "hidden_layers": ["Parcels"],
        "layout_text": {"FigureTitle": "T"},
        "extent_boundary_layer": "SiteBoundary", "extent_buffer_pct": 7,
    }
    data.update(over)
    return FigureSpec(data=data)


def test_prepare_figure_aprx_runs_every_step_of_the_chain(monkeypatch):
    """gen-map-series silently omitted visibility, layout text and extent —
    figures shipped with the template's defaults and no title (#462)."""
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    calls, work = _chain_recorder(monkeypatch)
    got, _ = prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"),
        "H281", "2026-06-15", _spec(), QACollector())

    assert got == work
    assert [c[0] for c in calls] == [
        "copy", "repath", "defquery", "visibility", "text", "zoom"]


def test_prepare_figure_aprx_selects_the_specs_layout(monkeypatch):
    """Both call sites read spec['layouts'], a key no figure spec defines, so
    layout_names was always None and export_layouts fell through its filter —
    exporting EVERY layout in the APRX, unconfigured (#459)."""
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    _chain_recorder(monkeypatch)
    _, layout_names = prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"),
        "H281", "2026-06-15", _spec(), QACollector())
    assert layout_names == ["GW Analytical Layout"]


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_prepare_figure_aprx_blocks_when_layout_name_is_empty(monkeypatch, bad):
    """FIGURE_REQUIRED is a key-PRESENCE check, so `layout_name:` (YAML null)
    or an empty string loads clean. Returning None for those would restore
    #459 exactly -- no filter, every layout exported under one colliding stem,
    and no QA record to show for it. An empty selection must block instead."""
    from autogis.core.common.qa import SEV_ERROR
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    _chain_recorder(monkeypatch)
    qa = QACollector()
    _, layout_names = prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"),
        "H281", "2026-06-15", _spec(layout_name=bad), qa)

    assert layout_names == []           # NOT None -- see export_layouts
    assert [r.category for r in qa.records] == ["layout_name_missing"]
    assert qa.records[0].severity == SEV_ERROR


def test_prepare_figure_aprx_strips_and_coerces_the_layout_name(monkeypatch):
    """A YAML scalar can arrive padded or non-str (`layout_name: 123`);
    export_layouts lowercases it, so it must be a stripped str by here."""
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    _chain_recorder(monkeypatch)
    _, layout_names = prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"),
        "H281", "2026-06-15", _spec(layout_name="  Padded Layout  "),
        QACollector())
    assert layout_names == ["Padded Layout"]


def test_prepare_figure_aprx_layout_text_merges_site_defaults(monkeypatch):
    """Site defaults < spec layout_text < the event date stamped last."""
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    calls, _ = _chain_recorder(monkeypatch)
    prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"),
        "H281", "2026-06-15", _spec(), QACollector(),
        layout_text={"FigureTitle": "site default", "Client": "Acme"})

    text = next(c for c in calls if c[0] == "text")[1][2]
    assert text == {"FigureTitle": "T", "Client": "Acme",
                    "EventDate": "2026-06-15"}


def test_prepare_figure_aprx_skips_zoom_without_a_boundary_layer(monkeypatch):
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    calls, _ = _chain_recorder(monkeypatch)
    prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"),
        "H281", "2026-06-15", _spec(extent_boundary_layer=None),
        QACollector())
    assert "zoom" not in [c[0] for c in calls]


# --- one match rule across every consumer of a resolved layout name ---

def test_prepare_figure_aprx_short_circuits_when_layout_name_is_missing(monkeypatch):
    """With no layout resolved, configuring means stamping text on and saving
    EVERY layout in the working APRX — output that is then never exported."""
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    calls, _ = _chain_recorder(monkeypatch)
    prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"),
        "H281", "2026-06-15", _spec(layout_name=None), QACollector())
    assert [c[0] for c in calls] == ["copy", "repath", "defquery", "visibility"]


def _aprx_with_layouts(*names):
    arcpy = MagicMock()
    aprx = MagicMock()
    aprx.listLayouts.return_value = [
        types.SimpleNamespace(name=n, listElements=lambda _k: []) for n in names]
    arcpy.mp.ArcGISProject.return_value = aprx
    return arcpy, aprx


@pytest.mark.parametrize("spec_name", [
    "GW Analytical Layout", "gw analytical layout", "GW ANALYTICAL LAYOUT"])
def test_update_layout_text_matches_the_layout_case_insensitively(
        monkeypatch, spec_name):
    """export_layouts has always lowercased; this module compared exactly. Once
    prepare_figure_aprx fed a real name to both, a case-mismatched spec
    EXPORTED the layout while silently skipping its text and extent — an
    unconfigured figure, beside an ERROR claiming the layout wasn't there."""
    from autogis.core.envmon import layout_manager as lm

    arcpy, _ = _aprx_with_layouts("GW Analytical Layout")
    monkeypatch.setattr(lm, "_arcpy", lambda: arcpy)
    qa = QACollector()
    lm.update_layout_text(Path("p.aprx"), spec_name, {"T": "x"}, qa)
    assert qa.records == []          # found it, whatever the casing


def test_zoom_to_boundary_reports_an_unmatched_layout(monkeypatch):
    """An empty layout list here was a silent no-op: the figure shipped with
    the template's saved extent and nothing said so."""
    from autogis.core.envmon import layout_manager as lm

    arcpy, _ = _aprx_with_layouts("GW Analytical Layout")
    monkeypatch.setattr(lm, "_arcpy", lambda: arcpy)
    qa = QACollector()
    lm.zoom_to_boundary(Path("p.aprx"), "No Such Layout", "SiteBoundary", 5, qa)
    assert [r.category for r in qa.records] == ["layout_missing"]


# --- config values at the trust boundary must not raise raw ---

@pytest.mark.parametrize("value", [None, "5%", "wide", [5]])
def test_bad_extent_buffer_pct_warns_and_defaults(monkeypatch, value):
    """Not FIGURE_REQUIRED, so such a spec loads clean; float() then raised a
    raw TypeError/ValueError out of the CLI."""
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    calls, _ = _chain_recorder(monkeypatch)
    qa = QACollector()
    prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"), "H281",
        "2026-06-15", _spec(extent_buffer_pct=value), qa)

    assert next(c for c in calls if c[0] == "zoom")[1][3] == 5.0
    if value is not None:
        assert "bad_extent_buffer_pct" in [r.category for r in qa.records]


def test_non_mapping_layout_text_warns_instead_of_raising(monkeypatch):
    """`layout_text: [a]` raised `dictionary update sequence element #0`."""
    from autogis.core.envmon.layout_manager import prepare_figure_aprx

    calls, _ = _chain_recorder(monkeypatch)
    qa = QACollector()
    prepare_figure_aprx(
        Path("t.aprx"), Path("/w"), "tag", Path("/g.gdb"), "H281",
        "2026-06-15", _spec(layout_text=["a"]), qa)

    assert next(c for c in calls if c[0] == "text")[1][2] == {
        "EventDate": "2026-06-15"}
    assert "spec_value_not_a_mapping" in [r.category for r in qa.records]


def test_scalar_visible_layers_is_not_iterated_per_character(monkeypatch):
    """`visible_layers: Wells` is a string; iterating it emitted one
    'layer missing' record per LETTER and toggled nothing."""
    from autogis.core.envmon import layout_manager as lm

    arcpy = MagicMock()
    aprx = MagicMock()
    a_map = MagicMock()
    a_map.listLayers.return_value = [types.SimpleNamespace(name="Wells",
                                                           visible=False)]
    aprx.listMaps.return_value = [a_map]
    arcpy.mp.ArcGISProject.return_value = aprx
    monkeypatch.setattr(lm, "_arcpy", lambda: arcpy)

    qa = QACollector()
    lm.set_layer_visibility(Path("p.aprx"), "Wells", [], qa)
    assert [r.category for r in qa.records] == ["spec_value_not_a_list"]
    assert a_map.listLayers.return_value[0].visible is True


@pytest.mark.parametrize("value,expected", [
    ("Wells", ["Wells"]),          # bare scalar
    (2026, ["2026"]),              # YAML int   -- used to raise TypeError
    (False, ["False"]),            # `no` in YAML -- used to raise TypeError
    (2.5, ["2.5"]),                # YAML float -- used to raise TypeError
    ({"Wells": 1}, None),          # mapping -- used to iterate as KEYS, silently
])
def test_non_list_layer_names_warn_instead_of_raising_or_iterating(
        value, expected):
    """Special-casing `str` alone left every other scalar raising a raw
    TypeError, and a mapping silently iterating as its keys — an accident that
    works until the keys are not layer names."""
    from autogis.core.envmon.layout_manager import _name_list

    qa = QACollector()
    got = _name_list(value, "visible_layers", qa)
    assert [r.category for r in qa.records] == ["spec_value_not_a_list"]
    if expected is not None:
        assert got == expected
    else:
        assert got == [str(value)]      # NOT ["Wells"] from iterating keys


def test_list_layer_names_pass_through_without_a_warning():
    from autogis.core.envmon.layout_manager import _name_list

    qa = QACollector()
    assert _name_list(["A", "B"], "visible_layers", qa) == ["A", "B"]
    assert qa.records == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -100, "-1"])
def test_extent_buffer_pct_rejects_non_finite_and_negative(bad):
    """float() accepts nan/inf, and a negative pads INWARD: -100 makes
    XMin_new == XMax_old — an inverted extent and a silently garbage figure."""
    from autogis.core.envmon.layout_manager import _buffer_pct

    qa = QACollector()
    assert _buffer_pct(bad, qa) == 5.0
    assert [r.category for r in qa.records] == ["bad_extent_buffer_pct"]


def test_extent_buffer_pct_accepts_a_real_number():
    from autogis.core.envmon.layout_manager import _buffer_pct

    qa = QACollector()
    assert _buffer_pct("7.5", qa) == 7.5
    assert qa.records == []


def test_figure_spec_layout_text_is_not_widened_to_the_values_file_list_form():
    """The two sides shared no rule for layout text, which was the drift to
    remove — but unifying by WIDENING the spec to accept a list form that no
    shipped spec uses, no schema mentions and nobody asked for is new surface
    area, not deduplication. The mapping rule is shared; the list form stays
    where the hand-written file format needs it."""
    from autogis.core.envmon.layout_manager import _text_map

    qa = QACollector()
    got = _text_map([{"element_name": "FigureTitle", "text": "GW Results"}],
                    "figure layout_text", qa)
    assert got == {}
    assert [r.category for r in qa.records] == ["spec_value_not_a_mapping"]
    # ...and the message stays operator-readable: no raw exception repr.
    assert "TypeError" not in qa.records[0].message
    assert "Error" not in qa.records[0].message


def test_values_file_still_accepts_the_list_form(tmp_path):
    """The affordance the file format actually needs is untouched."""
    p = _yaml(tmp_path, "- element_name: Title\n  text: Report Title\n")
    assert load_layout_text_yaml(p) == {"Title": "Report Title"}


def test_both_layout_text_sides_share_the_mapping_rule(tmp_path):
    """One rule for the shape they DO share, so they cannot drift again."""
    from autogis.core.envmon.layout_manager import _text_map

    mapping = {"FigureTitle": "GW Results", "FigureNumber": 2}
    p = _yaml(tmp_path, "FigureTitle: GW Results\nFigureNumber: 2\n")
    assert load_layout_text_yaml(p) == _text_map(
        mapping, "figure layout_text", QACollector())


def test_figure_spec_layout_text_warns_on_a_shape_neither_form_accepts():
    from autogis.core.envmon.layout_manager import _text_map

    qa = QACollector()
    assert _text_map(["just a string"], "figure layout_text", qa) == {}
    assert [r.category for r in qa.records] == ["spec_value_not_a_mapping"]


@pytest.mark.parametrize("yaml_bool", [True, False])
def test_extent_buffer_pct_rejects_a_yaml_boolean(yaml_bool):
    """`extent_buffer_pct: yes` is True, and float(True) is 1.0 — a silent 1%
    pad; `no` silently disabled padding. _name_list already treats a YAML bool
    as a first-class hazard; hardening one helper and not its sibling in the
    same commit is the half-done-helper pattern."""
    from autogis.core.envmon.layout_manager import _buffer_pct

    qa = QACollector()
    assert _buffer_pct(yaml_bool, qa) == 5.0
    assert [r.category for r in qa.records] == ["bad_extent_buffer_pct"]
