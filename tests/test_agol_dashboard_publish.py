import sys
import pytest
from unittest.mock import MagicMock, patch

from autogis.core.agol.dashboard_publish import (
    PublishDashboardResult,
    publish_dashboard,
)
from autogis.core.common.qa import QACollector


@pytest.fixture(autouse=True)
def mock_arcgis_modules():
    """Stub arcgis so dashboard_publish.py runs without the cloud extra
    installed -- mirrors test_agol_publish.py even though this module never
    imports arcgis directly (gis is injected)."""
    mocks = {"arcgis": MagicMock()}
    with patch.dict(sys.modules, mocks):
        yield mocks


def _spec(**overrides):
    base = {
        "title": "H281 Groundwater Status",
        "webmap_item_id": "abc123",
        "tags": ["autogis", "dashboard"],
        "cards": [
            {"title": "Active Wells", "layer": "Dash_WellStatus"},
        ],
    }
    base.update(overrides)
    return base


def test_publish_creates_new_item_when_no_match():
    gis = MagicMock()
    gis.content.search.return_value = []
    created_item = MagicMock()
    created_item.id = "new-item-id"
    gis.content.add.return_value = created_item

    result = publish_dashboard(gis, _spec())

    assert isinstance(result, PublishDashboardResult)
    assert result.created is True
    assert result.item_id == "new-item-id"
    gis.content.add.assert_called_once()
    gis.content.get.assert_not_called()
    assert any(r.category == "dashboard_created" for r in result.qa.records)


def test_publish_updates_existing_item_matched_by_item_id():
    gis = MagicMock()
    existing = MagicMock()
    existing.id = "existing-item-id"
    gis.content.get.return_value = existing

    result = publish_dashboard(gis, _spec(item_id="existing-item-id"))

    assert result.created is False
    assert result.item_id == "existing-item-id"
    gis.content.get.assert_called_once_with("existing-item-id")
    existing.update.assert_called_once()
    gis.content.add.assert_not_called()
    assert any(r.category == "dashboard_updated" for r in result.qa.records)


def test_publish_updates_existing_item_matched_by_title():
    gis = MagicMock()
    existing = MagicMock()
    existing.id = "existing-item-id"
    existing.title = "H281 Groundwater Status"
    gis.content.search.return_value = [existing]

    result = publish_dashboard(gis, _spec())

    assert result.created is False
    assert result.item_id == "existing-item-id"
    existing.update.assert_called_once()
    gis.content.add.assert_not_called()


def test_dry_run_returns_without_publish_call():
    gis = MagicMock()

    result = publish_dashboard(gis, _spec(), dry_run=True)

    assert result.created is False
    gis.content.add.assert_not_called()
    gis.content.search.assert_not_called()
    gis.content.get.assert_not_called()
    assert any(r.category == "dashboard_dry_run" for r in result.qa.records)
    assert result.dashboard_json["header"]["title"] == "H281 Groundwater Status"
    assert result.dashboard_json["widgets"][0]["datasets"][0]["layer"] == "Dash_WellStatus"


def test_create_failure_emits_qa_error():
    gis = MagicMock()
    gis.content.search.return_value = []
    gis.content.add.side_effect = RuntimeError("boom")

    result = publish_dashboard(gis, _spec())

    assert result.created is False
    assert result.item_id == ""
    assert any(r.category == "dashboard_create_failed" for r in result.qa.records)


def test_update_failure_emits_qa_error():
    gis = MagicMock()
    existing = MagicMock()
    existing.id = "existing-item-id"
    existing.update.side_effect = RuntimeError("boom")
    gis.content.get.return_value = existing

    result = publish_dashboard(gis, _spec(item_id="existing-item-id"))

    assert result.created is False
    assert result.item_id == "existing-item-id"
    assert any(r.category == "dashboard_update_failed" for r in result.qa.records)
