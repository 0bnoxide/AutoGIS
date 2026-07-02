import pytest

from autogis.core.agol.dashboard_spec import compile_dashboard_json


def _spec(**overrides):
    base = {
        "title": "H281 Groundwater Status",
        "webmap_item_id": "abc123",
        "cards": [
            {"title": "Active Wells", "layer": "Dash_WellStatus",
             "stat": "count", "field": "LocationID"},
        ],
        "charts": [
            {"title": "GW Level Trend", "layer": "Dash_GWLevelSummary",
             "category_field": "LocationID", "value_fields": ["GWE_ft"]},
        ],
        "selectors": [
            {"type": "category", "layer": "Dash_EventStatus",
             "field": "EventID", "label": "Event"},
            {"type": "date", "layer": "Dash_EventStatus",
             "field": "SampleDate", "label": "Date Range"},
        ],
    }
    base.update(overrides)
    return base


def test_header_has_title_and_webmap_item():
    result = compile_dashboard_json(_spec())
    assert result["header"]["title"] == "H281 Groundwater Status"
    assert result["header"]["webmapItemId"] == "abc123"


def test_indicator_card_appears_in_compiled_json():
    result = compile_dashboard_json(_spec())
    indicators = [w for w in result["widgets"] if w["type"] == "indicatorWidget"]
    assert len(indicators) == 1
    assert indicators[0]["name"] == "Active Wells"
    assert indicators[0]["datasets"][0]["layer"] == "Dash_WellStatus"
    assert indicators[0]["datasets"][0]["statisticDefinition"]["statisticType"] == "count"


def test_serial_chart_references_dash_layer():
    result = compile_dashboard_json(_spec())
    charts = [w for w in result["widgets"] if w["type"] == "serialChartWidget"]
    assert len(charts) == 1
    assert charts[0]["datasets"][0]["layer"] == "Dash_GWLevelSummary"
    assert charts[0]["datasets"][0]["valueFields"] == ["GWE_ft"]


def test_category_and_date_selectors_compile_to_right_types():
    result = compile_dashboard_json(_spec())
    types = [s["type"] for s in result["selectors"]]
    assert types == ["categorySelectorWidget", "dateSelectorWidget"]
    assert result["selectors"][0]["datasets"][0]["layer"] == "Dash_EventStatus"
    assert result["selectors"][0]["datasets"][0]["field"] == "EventID"


def test_lists_embeds_and_filters_compile():
    spec = _spec(
        lists=[{"title": "Open Issues", "layer": "Dash_OpenIssues",
                "fields": ["Category", "Severity"]}],
        embeds=[{"title": "Field Report", "url": "https://example.com/report"}],
        filters=[{"layer": "Dash_EventStatus", "field": "SiteID",
                  "operator": "equals", "value": "H281"}],
    )
    result = compile_dashboard_json(spec)
    lists = [w for w in result["widgets"] if w["type"] == "listWidget"]
    embeds = [w for w in result["widgets"] if w["type"] == "embeddedContentWidget"]
    assert lists[0]["datasets"][0]["fields"] == ["Category", "Severity"]
    assert embeds[0]["url"] == "https://example.com/report"
    assert result["filters"] == [
        {"layer": "Dash_EventStatus", "field": "SiteID",
         "operator": "equals", "value": "H281"},
    ]


def test_theme_and_refresh_interval_default_and_override():
    default = compile_dashboard_json(_spec())
    assert default["theme"] == "light"
    assert default["settings"]["refreshIntervalSeconds"] == 0

    overridden = compile_dashboard_json(_spec(theme="dark", refresh_interval_seconds=900))
    assert overridden["theme"] == "dark"
    assert overridden["settings"]["refreshIntervalSeconds"] == 900


def test_missing_title_raises_value_error():
    with pytest.raises(ValueError):
        compile_dashboard_json({})


def test_unknown_selector_type_raises_value_error():
    spec = _spec(selectors=[{"type": "bogus", "layer": "X", "field": "Y"}])
    with pytest.raises(ValueError):
        compile_dashboard_json(spec)


def test_no_optional_sections_compiles_minimal_dashboard():
    result = compile_dashboard_json({"title": "Minimal"})
    assert result["widgets"] == []
    assert result["selectors"] == []
    assert result["filters"] == []
    assert result["header"]["webmapItemId"] == ""
