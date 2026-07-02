import sys
import json
from unittest.mock import MagicMock, patch

import pytest

from autogis.core.agol.webmap import apply_spec_to_webmap_json, update_webmap_from_spec
from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


@pytest.fixture(autouse=True)
def mock_arcgis_modules():
    """Mirrors test_agol_publish.py even though this module never imports arcgis."""
    mocks = {"arcgis": MagicMock()}
    with patch.dict(sys.modules, mocks):
        yield mocks


def _spec(**overrides):
    base = {
        "figure_spec_id": "CKG_GW_Analytical",
        "site_id": "H281",
        "map_type": "GW_ANALYTICAL",
        "visible_layers": ["MonitoringWells"],
        "hidden_layers": ["SoilBorings"],
        "layer_definition_queries": {
            "Env_CalloutBoxes": "SiteID = '{site_id}' AND FigureSpecID = '{figure_spec_id}'"},
    }
    base.update(overrides)
    return base


def _webmap():
    return {"operationalLayers": [
        {"title": "MonitoringWells", "visibility": False},
        {"title": "SoilBorings", "visibility": True},
        {"title": "Env_CalloutBoxes", "visibility": True},
    ]}


def _gis(webmap_json):
    gis = MagicMock()
    item = MagicMock()
    item.get_data.return_value = webmap_json
    gis.content.get.return_value = item
    return gis, item


def test_apply_spec_sets_visibility():
    qa = QACollector()
    new_json, updated, missing = apply_spec_to_webmap_json(_webmap(), _spec(), qa)
    by_title = {lyr["title"]: lyr for lyr in new_json["operationalLayers"]}
    assert by_title["MonitoringWells"]["visibility"] is True
    assert by_title["SoilBorings"]["visibility"] is False
    assert updated >= 2


def test_apply_spec_sets_definition_query():
    qa = QACollector()
    new_json, updated, missing = apply_spec_to_webmap_json(_webmap(), _spec(), qa)
    by_title = {lyr["title"]: lyr for lyr in new_json["operationalLayers"]}
    assert (by_title["Env_CalloutBoxes"]["layerDefinition"]["definitionExpression"]
            == "SiteID = 'H281' AND FigureSpecID = 'CKG_GW_Analytical'")


def test_apply_spec_missing_layer_warns():
    qa = QACollector()
    spec = _spec(visible_layers=["MonitoringWells", "Env_GWContours_Draft"])
    new_json, updated, missing = apply_spec_to_webmap_json(_webmap(), spec, qa)
    assert "Env_GWContours_Draft" in missing
    assert any(r.severity == SEV_WARNING and r.category == "webmap_layer_missing"
               for r in qa.records)


def test_apply_spec_counts_only_changed_layers():
    webmap = {"operationalLayers": [
        {"title": "MonitoringWells", "visibility": True},
        {"title": "SoilBorings", "visibility": False},
        {"title": "Env_CalloutBoxes", "visibility": True,
         "layerDefinition": {"definitionExpression":
                              "SiteID = 'H281' AND FigureSpecID = 'CKG_GW_Analytical'"}},
    ]}
    qa = QACollector()
    new_json, updated, missing = apply_spec_to_webmap_json(webmap, _spec(), qa)
    assert updated == 0
    assert missing == []


def test_null_visible_hidden_layers_do_not_crash():
    """visible_layers/hidden_layers present-but-null (YAML `key:` with no
    value) must not raise TypeError iterating None, and apply no visibility
    change (only layer_definition_queries, left at its default, still fires)."""
    qa = QACollector()
    spec = _spec(visible_layers=None, hidden_layers=None)
    new_json, updated, missing = apply_spec_to_webmap_json(_webmap(), spec, qa)
    by_title = {lyr["title"]: lyr for lyr in new_json["operationalLayers"]}
    assert by_title["MonitoringWells"]["visibility"] is False  # unchanged
    assert by_title["SoilBorings"]["visibility"] is True  # unchanged
    assert missing == []


def test_null_layer_definition_queries_does_not_crash():
    """layer_definition_queries present-but-null must not raise iterating
    None.items(), and apply no definition-query change (visibility from
    visible_layers/hidden_layers, left at their defaults, still fires)."""
    qa = QACollector()
    spec = _spec(layer_definition_queries=None)
    new_json, updated, missing = apply_spec_to_webmap_json(_webmap(), spec, qa)
    by_title = {lyr["title"]: lyr for lyr in new_json["operationalLayers"]}
    assert "layerDefinition" not in by_title["Env_CalloutBoxes"]
    assert missing == []


def test_null_operational_layers_does_not_crash():
    """operationalLayers present-but-null in the web map JSON must not raise
    TypeError; every spec-named layer is then reported missing."""
    qa = QACollector()
    new_json, updated, missing = apply_spec_to_webmap_json(
        {"operationalLayers": None}, _spec(), qa)
    assert updated == 0
    assert set(missing) == {"MonitoringWells", "SoilBorings", "Env_CalloutBoxes"}


def test_null_defquery_template_warns_not_raises():
    """A present-but-null template value (YAML `Env_CalloutBoxes:` with no
    value) has no .format -- must degrade to defquery_render_failed, not
    crash with AttributeError."""
    qa = QACollector()
    spec = _spec(layer_definition_queries={"Env_CalloutBoxes": None})
    new_json, updated, missing = apply_spec_to_webmap_json(_webmap(), spec, qa)
    assert any(r.severity == SEV_WARNING and r.category == "defquery_render_failed"
               for r in qa.records)


def test_malformed_defquery_template_warns_not_raises():
    """A stray '{' in a definition-query template raises ValueError from
    str.format(), not just KeyError/IndexError -- must be caught, not crash."""
    qa = QACollector()
    spec = _spec(layer_definition_queries={"Env_CalloutBoxes": "SiteID = '{site_id'"})
    new_json, updated, missing = apply_spec_to_webmap_json(_webmap(), spec, qa)
    assert any(r.severity == SEV_WARNING and r.category == "defquery_render_failed"
               for r in qa.records)


def test_update_webmap_writes_item():
    gis, item = _gis(_webmap())
    result = update_webmap_from_spec(gis, webmap_item_id="abc123", figure_spec=_spec())
    item.update.assert_called_once()
    written = json.loads(item.update.call_args.kwargs["item_properties"]["text"])
    by_title = {lyr["title"]: lyr for lyr in written["operationalLayers"]}
    assert by_title["MonitoringWells"]["visibility"] is True
    assert any(r.severity == SEV_INFO and r.category == "webmap_updated"
               for r in result.qa.records)
    assert result.layers_updated >= 2


def test_dry_run_makes_no_update_call():
    gis, item = _gis(_webmap())
    result = update_webmap_from_spec(gis, webmap_item_id="abc123", figure_spec=_spec(),
                                     dry_run=True)
    item.update.assert_not_called()
    by_title = {lyr["title"]: lyr for lyr in result.webmap_json["operationalLayers"]}
    assert by_title["MonitoringWells"]["visibility"] is True
    assert any(r.category == "webmap_dry_run" for r in result.qa.records)
    assert any(r.category == "webmap_change" for r in result.qa.records)


def test_no_changes_skips_update():
    webmap = {"operationalLayers": [
        {"title": "MonitoringWells", "visibility": True},
        {"title": "SoilBorings", "visibility": False},
        {"title": "Env_CalloutBoxes", "visibility": True,
         "layerDefinition": {"definitionExpression":
                              "SiteID = 'H281' AND FigureSpecID = 'CKG_GW_Analytical'"}},
    ]}
    gis, item = _gis(webmap)
    result = update_webmap_from_spec(gis, webmap_item_id="abc123", figure_spec=_spec())
    item.update.assert_not_called()
    assert any(r.category == "webmap_no_changes" for r in result.qa.records)


def test_missing_item_emits_error():
    gis = MagicMock()
    gis.content.get.return_value = None
    result = update_webmap_from_spec(gis, webmap_item_id="abc123", figure_spec=_spec())
    assert any(r.severity == SEV_ERROR and r.category == "webmap_item_missing"
               for r in result.qa.records)
    assert result.layers_updated == 0


def test_item_fetch_failure_is_distinct_from_missing():
    """gis.content.get raising (auth/network) must not be conflated with a
    clean "item not found" result -- the QA category and message differ."""
    gis = MagicMock()
    gis.content.get.side_effect = RuntimeError("network down")
    result = update_webmap_from_spec(gis, webmap_item_id="abc123", figure_spec=_spec())
    assert any(r.severity == SEV_ERROR and r.category == "webmap_item_fetch_failed"
               for r in result.qa.records)
    assert not any(r.category == "webmap_item_missing" for r in result.qa.records)


def test_update_failure_emits_qa_error():
    gis, item = _gis(_webmap())
    item.update.side_effect = RuntimeError("boom")
    result = update_webmap_from_spec(gis, webmap_item_id="abc123", figure_spec=_spec())
    assert any(r.severity == SEV_ERROR and r.category == "webmap_update_failed"
               for r in result.qa.records)


def test_webmap_data_unreadable_emits_error():
    gis, item = _gis(_webmap())
    item.get_data.side_effect = RuntimeError("boom")
    result = update_webmap_from_spec(gis, webmap_item_id="abc123", figure_spec=_spec())
    assert any(r.severity == SEV_ERROR and r.category == "webmap_data_unreadable"
               for r in result.qa.records)
    item.update.assert_not_called()
