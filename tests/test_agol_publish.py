import sys
import zipfile
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


def _zip_with(tmp_path, *entries):
    """Write a real zip whose members are the given entry names."""
    p = tmp_path / "data.zip"
    with zipfile.ZipFile(p, "w") as zf:
        for name in entries:
            zf.writestr(name, b"")
    return p


def _fgdb_zip(tmp_path):
    return _zip_with(tmp_path, "data.gdb/a00000001.gdbtable")


def test_publish_creates_new_item(tmp_path):
    src = _fgdb_zip(tmp_path)
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
    src = _fgdb_zip(tmp_path)
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is not None
    assert any(r.severity == "INFO" for r in qa.records)


def test_publish_failure_keeps_traceback(tmp_path):
    src = _fgdb_zip(tmp_path)
    gis = MagicMock()
    gis.content.search.return_value = []
    gis.content.add.return_value.publish.side_effect = TypeError(
        'can only concatenate str (not "NoneType") to str')
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is None
    msg = next(r.message for r in qa.records if r.category == "publish_failed")
    assert "TypeError" in msg
    assert "Traceback (most recent call last)" in msg


def test_overwrite_failure_keeps_traceback(tmp_path, mock_arcgis_modules):
    src = _fgdb_zip(tmp_path)
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
    msg = next(r.message for r in qa.records
               if r.category == "publish_overwrite_failed")
    assert "Traceback (most recent call last)" in msg


def test_publish_name_taken_precheck(tmp_path):
    src = _fgdb_zip(tmp_path)
    gis = MagicMock()
    gis.content.search.return_value = []
    gis.content.is_service_name_available.return_value = False
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is None
    assert any(r.category == "publish_name_taken" for r in qa.records)
    gis.content.add.assert_not_called()


def test_publish_passes_explicit_service_name(tmp_path):
    src = _fgdb_zip(tmp_path)
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    gis.content.is_service_name_available.assert_called_once_with(
        "Test_Layer", "featureService")
    gis.content.add.return_value.publish.assert_called_once_with(
        publish_parameters={"name": "Test_Layer"})


def test_shapefile_zip_sets_shapefile_type(tmp_path):
    src = _zip_with(tmp_path, "roads.shp", "roads.shx", "roads.dbf")
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is not None
    item_props = gis.content.add.call_args[0][0]
    assert item_props["type"] == "Shapefile"


def test_fgdb_zip_sets_fgdb_type(tmp_path):
    src = _fgdb_zip(tmp_path)
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    item_props = gis.content.add.call_args[0][0]
    assert item_props["type"] == "File Geodatabase"


def test_geojson_source_sets_geojson_type(tmp_path):
    src = tmp_path / "data.geojson"
    src.write_text('{"type": "FeatureCollection", "features": []}')
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    item_props = gis.content.add.call_args[0][0]
    assert item_props["type"] == "GeoJson"


def test_unrecognized_zip_rejected(tmp_path):
    src = _zip_with(tmp_path, "readme.txt")
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is None
    assert any(r.category == "publish_source_unsupported" for r in qa.records)
    gis.content.add.assert_not_called()


def test_invalid_zip_rejected(tmp_path):
    src = tmp_path / "data.zip"
    src.write_bytes(b"not a zip")
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is None
    assert any(r.category == "publish_source_unsupported" for r in qa.records)
    gis.content.add.assert_not_called()


def test_unsupported_extension_rejected(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("a,b\n1,2\n")
    gis = MagicMock()
    gis.content.search.return_value = []
    qa = QACollector()

    result = publish_or_overwrite_layer(gis, _cfg(), str(src), qa)

    assert result is None
    assert any(r.category == "publish_source_unsupported" for r in qa.records)
    gis.content.add.assert_not_called()
