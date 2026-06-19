from autogis.core.templates import sanitize, render, render_path_component


def test_sanitize_strips_illegal_chars():
    assert sanitize('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"


def test_sanitize_collapses_whitespace():
    assert sanitize("a   b\tc") == "a_b_c"


def test_sanitize_strips_edge_dots_and_spaces():
    assert sanitize("  .name.  ") == "name"


def test_sanitize_blank_becomes_unknown():
    assert sanitize("   ") == "_unknown"
    assert sanitize("") == "_unknown"


def test_render_substitutes_fields():
    out = render("{InspectionID}_{OBJECTID}_{name}",
                 {"InspectionID": "INS5", "OBJECTID": 12, "name": "photo.jpg"})
    assert out == "INS5_12_photo.jpg"


def test_render_missing_field_is_unknown():
    assert render("{Status}", {}) == "_unknown"


def test_render_none_value_is_unknown():
    assert render("{Status}", {"Status": None}) == "_unknown"


def test_render_path_component_sanitizes():
    out = render_path_component("{Status}", {"Status": "In/Progress"})
    assert out == "InProgress"
