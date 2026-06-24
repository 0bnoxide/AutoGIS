import sys
import pytest
from unittest.mock import MagicMock, patch

from autogis.core.agol.publish import PublishConfig, publish_or_overwrite_layer
from autogis.core.common.qa import QACollector


@pytest.fixture(autouse=True)
def mock_arcgis_modules():
    """Stub arcgis so publish.py runs without the cloud extra installed."""
    mocks = {
        "arcgis": MagicMock(),
        "arcgis.features": MagicMock(),
        "arcgis.features.managers": MagicMock(),
    }
    with patch.dict(sys.modules, mocks):
        yield mocks


def _cfg(**kw):
    return PublishConfig(title="Test Layer", tags=["autogis"], **kw)


def test_publish_creates_new_item(tmp_path):
    src = tmp_path / "data.zip"
    src.write_bytes(b"fake")
    gis = MagicMock()
    gis.content.search.return_value = []
    published = MagicMock()
    gis.content.add.return_value.publish.return_value = published
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is published
    gis.content.add.assert_called_once()
    gis.content.add.return_value.publish.assert_called_once()


def test_publish_overwrites_existing(tmp_path, mock_arcgis_modules):
    src = tmp_path / "data.zip"
    src.write_bytes(b"fake")
    existing = MagicMock()
    existing.title = "Test Layer"
    mock_mgr = MagicMock()
    mock_arcgis_modules["arcgis.features.managers"].FeatureLayerManager.return_value = mock_mgr
    gis = MagicMock()
    gis.content.search.return_value = [existing]
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is existing
    mock_mgr.overwrite.assert_called_once_with(str(src))
    assert any("overwritten" in r.category for r in qa.records)


def test_publish_missing_source_emits_qa_error(tmp_path):
    gis = MagicMock()
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(tmp_path / "no.zip"), qa)

    assert result is None
    assert any(r.category == "publish_source_missing" for r in qa.records)
    assert any(r.severity == "ERROR" for r in qa.records)


def test_publish_overwrite_failure_emits_qa_error(tmp_path, mock_arcgis_modules):
    src = tmp_path / "data.zip"
    src.write_bytes(b"fake")
    existing = MagicMock()
    existing.title = "Test Layer"
    mock_mgr = MagicMock()
    mock_mgr.overwrite.side_effect = RuntimeError("boom")
    mock_arcgis_modules["arcgis.features.managers"].FeatureLayerManager.return_value = mock_mgr
    gis = MagicMock()
    gis.content.search.return_value = [existing]
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is None
    assert any(r.category == "publish_overwrite_failed" for r in qa.records)


def test_publish_qa_info_on_success(tmp_path):
    src = tmp_path / "data.zip"
    src.write_bytes(b"fake")
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is not None
    assert any(r.severity == "INFO" for r in qa.records)
