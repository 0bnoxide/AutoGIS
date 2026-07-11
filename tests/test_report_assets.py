from importlib.resources import files


def test_report_css_resource_resolves_and_nonempty():
    res = files("autogis.core.common.report_assets").joinpath("report.css")
    text = res.read_text(encoding="utf-8")
    assert ".report" in text and ".kpi" in text and "@media print" in text
    assert len(text) > 500
