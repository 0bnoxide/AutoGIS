"""Unit tests for manage_callout_overrides — all arcpy-free via mocks."""
from pathlib import Path
from unittest.mock import MagicMock, patch


def _mock_arcpy(exists=True, cursor_rows=None):
    """Return a pre-wired arcpy mock."""
    arcpy = MagicMock()
    arcpy.Exists.return_value = exists
    if cursor_rows is not None:
        cm = MagicMock()
        cm.__iter__ = lambda s: iter(cursor_rows)
        arcpy.da.SearchCursor.return_value.__enter__ = lambda s: cm
        arcpy.da.SearchCursor.return_value.__exit__ = MagicMock(return_value=False)
    return arcpy


def test_load_overrides_returns_empty_when_table_missing(tmp_path):
    mock = _mock_arcpy(exists=False)
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import load_overrides
        result = load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1")
    assert result == {}


def test_load_overrides_maps_anchor_plus_offset(tmp_path):
    # Row: loc, AnchorX, AnchorY, OffsetX, OffsetY, PreferredQuadrant, LockedPlacement
    row = ("MW-1", 100.0, 200.0, 1.5, 2.5, None, 0)
    mock = _mock_arcpy(exists=True, cursor_rows=[row])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import load_overrides
        result = load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1")
    assert "MW-1" in result
    assert result["MW-1"]["origin"] == (101.5, 202.5)
    assert result["MW-1"]["locked"] is False
    assert result["MW-1"]["preferred_quadrant"] is None


def test_load_overrides_preferred_quadrant_no_anchor(tmp_path):
    row = ("MW-2", None, None, None, None, "NE", 0)
    mock = _mock_arcpy(exists=True, cursor_rows=[row])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import load_overrides
        result = load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1")
    assert result["MW-2"]["origin"] is None
    assert result["MW-2"]["preferred_quadrant"] == "NE"


def test_load_overrides_upcases_location_id(tmp_path):
    row = ("mw-3", 10.0, 20.0, 0.0, 0.0, None, 1)
    mock = _mock_arcpy(exists=True, cursor_rows=[row])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import load_overrides
        result = load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1")
    assert "MW-3" in result
    assert result["MW-3"]["locked"] is True


def test_callout_override_dataclass_fields():
    from autogis.core.envmon.manage_callout_overrides import CalloutOverride
    ov = CalloutOverride(site_id="S", location_id="MW-1", figure_spec_id="F")
    assert ov.anchor_x is None
    assert ov.offset_x == 0.0
    assert ov.locked is False
    assert ov.notes == ""
