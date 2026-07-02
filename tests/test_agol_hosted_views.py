import sys
from unittest.mock import MagicMock, patch

import pytest

from autogis.core.agol.hosted_views import (
    ViewSpec, create_stakeholder_view, load_view_specs, resolve_fields)
from autogis.core.common.qa import SEV_ERROR, SEV_INFO, SEV_WARNING


@pytest.fixture(autouse=True)
def mock_arcgis_modules():
    mocks = {"arcgis": MagicMock(), "arcgis.features": MagicMock()}
    with patch.dict(sys.modules, mocks):
        yield mocks


def _spec(**kw):
    base = dict(name="Client_View", source_layer="MonitoringWells",
                allow_fields=["SiteID", "WellID"], sensitive_fields=["OwnerPhone"])
    base.update(kw)
    return ViewSpec(**base)


def _item(title, field_names, visible=None):
    item = MagicMock()
    item.title = title
    fields = []
    for n in field_names:
        f = {"name": n}
        if visible is not None:
            f["visible"] = visible.get(n, True)
        fields.append(f)
    item.layers = [MagicMock()]
    item.layers[0].properties = {"fields": fields}
    return item


def _gis(*items):
    gis = MagicMock()

    def search(query, item_type=None):
        return [it for it in items if it.title in query]

    gis.content.search.side_effect = search
    return gis


def test_resolve_fields_allow_list_returns_only_allowed():
    spec = _spec(allow_fields=["SiteID", "WellID"])
    assert resolve_fields(["SiteID", "WellID", "OwnerPhone"], spec) == ["SiteID", "WellID"]


def test_resolve_fields_deny_list_drops_denied():
    spec = _spec(allow_fields=None, deny_fields=["OwnerPhone"])
    assert resolve_fields(["SiteID", "WellID", "OwnerPhone"], spec) == ["SiteID", "WellID"]


def test_resolve_fields_allow_list_excludes_new_source_field():
    spec = _spec(allow_fields=["SiteID", "WellID"])
    assert resolve_fields(["SiteID", "WellID", "NewSecretCol"], spec) == ["SiteID", "WellID"]


def test_resolve_fields_both_lists_raise():
    spec = _spec(allow_fields=["SiteID"], deny_fields=["OwnerPhone"])
    with pytest.raises(ValueError):
        resolve_fields(["SiteID", "OwnerPhone"], spec)


def test_resolve_fields_empty_allow_list_exposes_nothing():
    """An explicit allow_fields=[] fails closed -- not treated as 'no allow-list'."""
    spec = _spec(allow_fields=[])
    assert resolve_fields(["SiteID", "WellID", "OwnerPhone"], spec) == []


def test_load_view_specs_parses_yaml_shape():
    data = {"views": [
        {"name": "Client_View", "source_layer": "MonitoringWells",
         "allow_fields": ["SiteID", "WellID"], "sensitive_fields": ["OwnerPhone"]},
    ]}
    specs = load_view_specs(data)
    assert len(specs) == 1
    assert specs[0].name == "Client_View"
    assert specs[0].source_layer == "MonitoringWells"
    assert specs[0].sensitive_fields == ["OwnerPhone"]


def test_load_view_specs_missing_source_layer_raises():
    with pytest.raises(ValueError):
        load_view_specs({"views": [{"name": "X"}]})


def test_load_view_specs_non_dict_raises():
    """An empty or malformed YAML file (None, list, string) must raise ValueError,
    not AttributeError/TypeError -- the CLI relies on ValueError to produce a
    clean click.UsageError instead of a traceback."""
    for bad in (None, [], "not a mapping"):
        with pytest.raises(ValueError):
            load_view_specs(bad)


def test_load_view_specs_null_views_key_is_empty():
    """views: with no value parses as YAML null, not omitted -- must not
    raise iterating None, and must be treated as an empty list."""
    assert load_view_specs({"views": None}) == []


def test_load_view_specs_non_list_views_raises():
    with pytest.raises(ValueError):
        load_view_specs({"views": "not a list"})


def test_load_view_specs_non_dict_entry_raises():
    with pytest.raises(ValueError):
        load_view_specs({"views": ["not a mapping"]})


def test_create_new_view_when_no_existing(mock_arcgis_modules):
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    gis = _gis(source)
    flc_cls = mock_arcgis_modules["arcgis.features"].FeatureLayerCollection
    view_item = flc_cls.fromitem.return_value.manager.create_view.return_value
    view_item.layers = [MagicMock()]
    view_item.layers[0].properties = {"fields": [
        {"name": "SiteID", "visible": True}, {"name": "WellID", "visible": True},
        {"name": "OwnerPhone", "visible": False},
    ]}

    result = create_stakeholder_view(gis, _spec())

    flc_cls.fromitem.assert_called_once_with(source)
    flc_cls.fromitem.return_value.manager.create_view.assert_called_once()
    assert result.created is True
    assert any(r.severity == SEV_INFO and r.category == "view_created"
               for r in result.qa.records)


def test_existing_view_updates_not_creates(mock_arcgis_modules):
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": False})
    gis = _gis(source, existing_view)
    flc_cls = mock_arcgis_modules["arcgis.features"].FeatureLayerCollection

    result = create_stakeholder_view(gis, _spec())

    assert result.created is False
    flc_cls.fromitem.assert_not_called()
    assert any(r.category == "view_updated" for r in result.qa.records)


def test_definition_query_passed_through(mock_arcgis_modules):
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": False})
    gis = _gis(source, existing_view)
    spec = _spec(definition_query="SiteID = 'H281'")

    create_stakeholder_view(gis, spec)

    existing_view.layers[0].manager.update_definition.assert_called_once()
    call = existing_view.layers[0].manager.update_definition.call_args[0][0]
    assert call["viewDefinitionQuery"] == "SiteID = 'H281'"
    by_name = {f["name"]: f["visible"] for f in call["fields"]}
    assert by_name["OwnerPhone"] is False
    assert by_name["SiteID"] is True


def test_sensitive_field_leak_is_blocking_error(mock_arcgis_modules):
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": True})
    gis = _gis(source, existing_view)

    result = create_stakeholder_view(gis, _spec())

    assert result.leaked_fields == ["OwnerPhone"]
    assert any(r.severity == SEV_ERROR and r.category == "view_sensitive_leak"
               for r in result.qa.records)


def test_verified_view_reports_exposed_fields(mock_arcgis_modules):
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": False})
    gis = _gis(source, existing_view)

    result = create_stakeholder_view(gis, _spec())

    assert result.leaked_fields == []
    assert sorted(result.exposed_fields) == ["SiteID", "WellID"]
    assert any(r.category == "view_verified" for r in result.qa.records)


def test_source_missing_emits_error(mock_arcgis_modules):
    gis = _gis()
    result = create_stakeholder_view(gis, _spec())
    assert any(r.severity == SEV_ERROR and r.category == "view_source_missing"
               for r in result.qa.records)


def test_create_failure_emits_qa_error(mock_arcgis_modules):
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    gis = _gis(source)
    flc_cls = mock_arcgis_modules["arcgis.features"].FeatureLayerCollection
    flc_cls.fromitem.return_value.manager.create_view.side_effect = RuntimeError("boom")

    result = create_stakeholder_view(gis, _spec())

    assert any(r.severity == SEV_ERROR and r.category == "view_create_failed"
               for r in result.qa.records)


def test_verification_readback_failure_is_blocking_not_silent_pass(mock_arcgis_modules):
    """If the post-write read-back itself can't be read (unexpected AGOL
    response shape), that must be treated as unverified/unsafe, not as a
    silent pass -- never trust the create call, and a failed verification
    is not proof of safety either."""
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": False})
    existing_view.layers[0].properties = {}  # missing "fields" -> KeyError on read-back
    gis = _gis(source, existing_view)

    result = create_stakeholder_view(gis, _spec())

    assert any(r.severity == SEV_ERROR and r.category == "view_verification_failed"
               for r in result.qa.records)
    assert result.leaked_fields == []
    assert result.exposed_fields == []


def test_multi_layer_source_emits_unverified_warning(mock_arcgis_modules):
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    source.layers = [source.layers[0], MagicMock()]
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": False})
    gis = _gis(source, existing_view)

    result = create_stakeholder_view(gis, _spec())

    assert any(r.severity == SEV_WARNING and r.category == "view_unverified_layers"
               for r in result.qa.records)


def test_source_search_failure_emits_error(mock_arcgis_modules):
    gis = MagicMock()
    gis.content.search.side_effect = RuntimeError("network down")
    result = create_stakeholder_view(gis, _spec())
    assert any(r.severity == SEV_ERROR and r.category == "view_source_search_failed"
               for r in result.qa.records)


def test_existing_view_search_failure_aborts_without_creating(mock_arcgis_modules):
    """A search failure on the existing-view lookup must not fall through to
    create_view -- that would risk a duplicate view during an outage."""
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    gis = MagicMock()

    def search(query, item_type=None):
        if "MonitoringWells" in query:
            return [source]
        raise RuntimeError("network down")

    gis.content.search.side_effect = search
    flc_cls = mock_arcgis_modules["arcgis.features"].FeatureLayerCollection

    result = create_stakeholder_view(gis, _spec())

    flc_cls.fromitem.assert_not_called()
    assert any(r.severity == SEV_ERROR and r.category == "view_existing_search_failed"
               for r in result.qa.records)


def test_source_unreadable_fields_emits_error(mock_arcgis_modules):
    source = MagicMock()
    source.title = "MonitoringWells"
    source.layers = []  # layers[0] raises IndexError
    gis = _gis(source)
    result = create_stakeholder_view(gis, _spec())
    assert any(r.severity == SEV_ERROR and r.category == "view_source_unreadable"
               for r in result.qa.records)


def test_load_view_specs_string_field_list_raises():
    """deny_fields: OwnerPhone (a bare string, not a list) becomes
    set("OwnerPhone") -- a set of CHARACTERS -- so it denies nothing; a string
    sensitive_fields likewise makes the leak check iterate characters and
    silently pass. All three list-valued keys must be rejected at parse time,
    including non-string items."""
    for key in ("allow_fields", "deny_fields", "sensitive_fields"):
        for bad in ("OwnerPhone", [123]):
            with pytest.raises(ValueError):
                load_view_specs({"views": [
                    {"name": "X", "source_layer": "Y", key: bad}]})


def test_source_properties_network_failure_emits_error(mock_arcgis_modules):
    """.layers/.properties lazily fetch service metadata over the network --
    a RuntimeError (auth/network), not just a shape error, must produce
    view_source_unreadable instead of aborting the batch."""
    source = MagicMock()
    source.title = "MonitoringWells"
    source.layers[0].properties.__getitem__.side_effect = RuntimeError("network down")
    gis = _gis(source)
    result = create_stakeholder_view(gis, _spec())
    assert any(r.severity == SEV_ERROR and r.category == "view_source_unreadable"
               for r in result.qa.records)


def test_verification_readback_network_failure_is_blocking(mock_arcgis_modules):
    """Same for the post-write read-back: a network failure mid-verification
    must degrade to view_verification_failed (unverified, unsafe), not raise."""
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": False})
    existing_view.layers[0].properties = MagicMock()
    existing_view.layers[0].properties.__getitem__.side_effect = RuntimeError("network down")
    gis = _gis(source, existing_view)

    result = create_stakeholder_view(gis, _spec())

    assert any(r.severity == SEV_ERROR and r.category == "view_verification_failed"
               for r in result.qa.records)
    assert result.exposed_fields == []
    assert result.leaked_fields == []


def test_unknown_spec_field_names_warn(mock_arcgis_modules):
    """A deny/sensitive field name absent from the source (typo or schema
    drift) protects nothing -- must emit view_unknown_fields, not stay silent."""
    source = _item("MonitoringWells", ["SiteID", "WellID", "OwnerPhone"])
    existing_view = _item("Client_View", ["SiteID", "WellID", "OwnerPhone"],
                          visible={"OwnerPhone": False})
    gis = _gis(source, existing_view)
    spec = _spec(allow_fields=None, deny_fields=["OwnerPhon"],
                 sensitive_fields=["OwnerFax"])

    result = create_stakeholder_view(gis, spec)

    assert any(r.severity == SEV_WARNING and r.category == "view_unknown_fields"
               and "OwnerPhon" in r.message and "OwnerFax" in r.message
               for r in result.qa.records)
