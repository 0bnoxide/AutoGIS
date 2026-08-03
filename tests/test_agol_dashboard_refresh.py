import ast
import inspect
from unittest.mock import MagicMock

import autogis.core.agol.dashboard_refresh as dashboard_refresh
from autogis.core.agol.dashboard_refresh import RefreshResult, refresh_dashboard_data


def _fake_layer(fields=None):
    """A MagicMock standing in for an arcgis FeatureLayer, with real dict-based
    fields (arcgis's PropertyMap supports dict-style access, so a plain dict
    of {"name": ...} is a faithful enough double)."""
    layer = MagicMock()
    layer.properties.fields = [{"name": n} for n in (fields or [])]
    return layer


def _fake_gis(layers_by_id, as_table=False):
    """layers_by_id: item_id -> fake layer, or an Exception instance to raise
    when that item is fetched (simulates a hosted-layer failure). Dash_* are
    non-spatial, so real hosted items expose them via ``.tables``, not
    ``.layers`` -- ``as_table=True`` doubles as that item shape."""
    gis = MagicMock()

    def _get(item_id):
        target = layers_by_id[item_id]
        if isinstance(target, Exception):
            raise target
        item = MagicMock()
        item.layers = [] if as_table else [target]
        item.tables = [target] if as_table else []
        return item

    gis.content.get.side_effect = _get
    return gis


def test_module_has_no_top_level_arcgis_import():
    """dashboard_refresh must not import arcgis at module level (spec point 1).

    Every arcgis object here comes through the injected ``gis``, so there is
    nothing to import lazily either -- assert statically that no top-level
    import statement names arcgis (the module-level import already succeeding
    above, with arcgis absent from this environment, is the runtime half of
    this proof)."""
    tree = ast.parse(inspect.getsource(dashboard_refresh))
    top_level_modules = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top_level_modules.append(node.module or "")
    assert not any(m == "arcgis" or m.startswith("arcgis.") for m in top_level_modules)


def test_refresh_truncates_then_appends_in_order():
    layer = _fake_layer(["SiteID", "SiteName"])
    calls = []
    layer.manager.truncate.side_effect = lambda: calls.append("truncate")
    layer.edit_features.side_effect = lambda **kw: calls.append("append")
    gis = _fake_gis({"item-1": layer})

    mart = {"Dash_SiteStatus": [{"SiteID": "S1", "SiteName": "Site One"}]}
    layer_map = {"Dash_SiteStatus": "item-1"}

    result = refresh_dashboard_data(gis, mart, layer_map)

    assert calls == ["truncate", "append"]
    assert isinstance(result, RefreshResult)
    assert result.tables_refreshed == 1
    assert result.rows_pushed == {"Dash_SiteStatus": 1}
    assert result.failures == []


def test_rows_pushed_matches_input_row_counts():
    layer_a = _fake_layer(["SiteID"])
    layer_b = _fake_layer(["SiteID", "EventID"])
    gis = _fake_gis({"a": layer_a, "b": layer_b})
    mart = {
        "Dash_SiteStatus": [{"SiteID": "S1"}, {"SiteID": "S2"}],
        "Dash_EventStatus": [{"SiteID": "S1", "EventID": "E1"}],
    }
    layer_map = {"Dash_SiteStatus": "a", "Dash_EventStatus": "b"}

    result = refresh_dashboard_data(gis, mart, layer_map)

    assert result.rows_pushed == {"Dash_SiteStatus": 2, "Dash_EventStatus": 1}
    assert result.tables_refreshed == 2
    assert result.failures == []


def test_missing_layer_map_warns_and_skips_not_crash():
    gis = _fake_gis({})
    mart = {"Dash_Unmapped": [{"SiteID": "S1"}]}
    layer_map = {}

    result = refresh_dashboard_data(gis, mart, layer_map)

    assert result.tables_refreshed == 0
    assert result.rows_pushed == {}
    assert result.failures == []
    assert any(r.severity == "WARNING" and r.category == "refresh_no_layer_mapping"
               for r in result.qa.records)
    gis.content.get.assert_not_called()


def test_one_table_failure_does_not_abort_others():
    good_layer = _fake_layer(["SiteID"])
    gis = _fake_gis({"bad": RuntimeError("boom"), "good": good_layer})
    mart = {
        "Dash_Bad": [{"SiteID": "S1"}],
        "Dash_Good": [{"SiteID": "S1"}],
    }
    layer_map = {"Dash_Bad": "bad", "Dash_Good": "good"}

    result = refresh_dashboard_data(gis, mart, layer_map)

    assert result.failures == ["Dash_Bad"]
    assert result.rows_pushed == {"Dash_Good": 1}
    assert result.tables_refreshed == 1
    assert any(r.severity == "ERROR" and r.category == "refresh_table_failed"
               for r in result.qa.records)


def test_dry_run_validates_without_writing():
    layer = _fake_layer(["SiteID", "SiteName"])
    gis = _fake_gis({"item-1": layer})
    mart = {"Dash_SiteStatus": [{"SiteID": "S1", "SiteName": "Site One"}]}
    layer_map = {"Dash_SiteStatus": "item-1"}

    result = refresh_dashboard_data(gis, mart, layer_map, dry_run=True)

    layer.manager.truncate.assert_not_called()
    layer.edit_features.assert_not_called()
    assert result.tables_refreshed == 1
    assert result.failures == []
    assert any(r.category == "refresh_dry_run_ok" for r in result.qa.records)


def test_dry_run_schema_mismatch_is_a_failure_and_writes_nothing():
    layer = _fake_layer(["SiteID"])  # missing SiteName field
    gis = _fake_gis({"item-1": layer})
    mart = {"Dash_SiteStatus": [{"SiteID": "S1", "SiteName": "Site One"}]}
    layer_map = {"Dash_SiteStatus": "item-1"}

    result = refresh_dashboard_data(gis, mart, layer_map, dry_run=True)

    assert result.failures == ["Dash_SiteStatus"]
    assert result.tables_refreshed == 0
    layer.manager.truncate.assert_not_called()
    layer.edit_features.assert_not_called()
    assert any(r.severity == "ERROR" and r.category == "refresh_dry_run_schema_mismatch"
               for r in result.qa.records)


def test_resolves_non_spatial_dash_table_via_item_tables():
    """Dash_* are non-spatial (no SHAPE column) -- a real hosted item for one
    exposes it under item.tables, not item.layers. Must not IndexError."""
    layer = _fake_layer(["SiteID"])
    gis = _fake_gis({"item-1": layer}, as_table=True)
    mart = {"Dash_SiteStatus": [{"SiteID": "S1"}]}
    layer_map = {"Dash_SiteStatus": "item-1"}

    result = refresh_dashboard_data(gis, mart, layer_map)

    assert result.failures == []
    assert result.tables_refreshed == 1
    layer.manager.truncate.assert_called_once()


def test_empty_rows_still_truncates_but_skips_append_call():
    layer = _fake_layer(["SiteID"])
    gis = _fake_gis({"item-1": layer})
    mart = {"Dash_SiteStatus": []}
    layer_map = {"Dash_SiteStatus": "item-1"}

    result = refresh_dashboard_data(gis, mart, layer_map)

    layer.manager.truncate.assert_called_once()
    layer.edit_features.assert_not_called()
    assert result.rows_pushed == {"Dash_SiteStatus": 0}
    assert result.tables_refreshed == 1


# ── issue #424: an empty mart reported success ────────────────────────────

def test_empty_mart_tables_raises_instead_of_reporting_success():
    """`tables_refreshed=0 rows_pushed={} failures=[]` at exit 0 is
    indistinguishable from a real refresh, so automation could not tell the
    no-op apart. Fail closed instead."""
    import pytest

    gis = _fake_gis({})
    with pytest.raises(ValueError) as exc:
        refresh_dashboard_data(gis, {}, {"Dash_SiteStatus": "item-1"})
    assert "nothing" in str(exc.value)
    gis.content.get.assert_not_called()


def test_cli_rejects_an_empty_mart_dir_before_authenticating(tmp_path, monkeypatch):
    """The CLI half of #424: an existing but empty --mart-dir used to
    authenticate, refresh nothing and exit 0."""
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis

    def _no_auth(*a, **kw):
        raise AssertionError("must fail closed before authenticating")

    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", _no_auth)
    mart_dir = tmp_path / "mart"
    mart_dir.mkdir()
    layer_map = tmp_path / "layers.yaml"
    layer_map.write_text("Dash_SiteStatus: item-1\n", encoding="utf-8")

    res = CliRunner().invoke(autogis, [
        "agol", "refresh-dashboard",
        "--mart-dir", str(mart_dir), "--layer-map", str(layer_map)])
    assert res.exit_code != 0
    assert "No Dash_*.json files" in res.output


# ── issue #428: a partial append was counted as a refreshed table ──────────

def test_rejected_adds_are_blocking_failures_not_success():
    """ArcGIS edit APIs report per-feature failures inside a normal response
    rather than raising, so the table could be truncated, only partly
    restored, counted as refreshed, and exit 0."""
    layer = _fake_layer(["SiteID"])
    layer.edit_features.return_value = {"addResults": [
        {"objectId": 1, "success": True},
        {"success": False, "error": {"code": 1000, "description": "bad field"}},
    ]}
    gis = _fake_gis({"item-1": layer})
    result = refresh_dashboard_data(
        gis, {"Dash_SiteStatus": [{"SiteID": "A"}, {"SiteID": "B"}]},
        {"Dash_SiteStatus": "item-1"})

    assert result.failures == ["Dash_SiteStatus"]
    assert result.tables_refreshed == 0
    assert "Dash_SiteStatus" not in result.rows_pushed
    msg = " ".join(r.message for r in result.qa.records)
    assert "PARTIAL" in msg                    # destructive state surfaced
    assert "bad field" in msg                  # service's own reason
    assert "Re-run this command" in msg        # documented recovery


def test_all_successful_adds_still_count_as_refreshed():
    layer = _fake_layer(["SiteID"])
    layer.edit_features.return_value = {
        "addResults": [{"objectId": 1, "success": True}]}
    gis = _fake_gis({"item-1": layer})
    result = refresh_dashboard_data(
        gis, {"Dash_SiteStatus": [{"SiteID": "A"}]}, {"Dash_SiteStatus": "item-1"})
    assert result.failures == []
    assert result.tables_refreshed == 1
    assert result.rows_pushed == {"Dash_SiteStatus": 1}


def test_append_exception_after_truncate_names_the_destructive_state():
    """A raised append leaves the table empty; the report has to say so."""
    layer = _fake_layer(["SiteID"])
    layer.edit_features.side_effect = RuntimeError("service unavailable")
    gis = _fake_gis({"item-1": layer})
    result = refresh_dashboard_data(
        gis, {"Dash_SiteStatus": [{"SiteID": "A"}]}, {"Dash_SiteStatus": "item-1"})
    assert result.failures == ["Dash_SiteStatus"]
    msg = " ".join(r.message for r in result.qa.records)
    assert "EMPTY or PARTIAL" in msg and "Re-run this command" in msg


def test_failure_before_truncate_says_the_table_was_untouched():
    """Distinguish the recoverable-nothing-happened case from the destructive
    one -- an operator reads these to decide whether hosted data is at risk."""
    gis = _fake_gis({"item-1": RuntimeError("item not found")})
    result = refresh_dashboard_data(
        gis, {"Dash_SiteStatus": [{"SiteID": "A"}]}, {"Dash_SiteStatus": "item-1"})
    assert result.failures == ["Dash_SiteStatus"]
    msg = " ".join(r.message for r in result.qa.records)
    assert "was not modified" in msg
    assert "EMPTY" not in msg
