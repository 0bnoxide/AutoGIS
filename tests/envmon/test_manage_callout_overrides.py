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


def test_save_override_inserts_row(tmp_path):
    mock = MagicMock()
    mock.Exists.return_value = True
    update_cm = MagicMock()
    update_cm.__iter__ = lambda s: iter([])  # no existing rows to delete
    mock.da.UpdateCursor.return_value.__enter__ = lambda s: update_cm
    mock.da.UpdateCursor.return_value.__exit__ = MagicMock(return_value=False)
    insert_cm = MagicMock()
    mock.da.InsertCursor.return_value.__enter__ = lambda s: insert_cm
    mock.da.InsertCursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import (
            CalloutOverride, save_override,
        )
        ov = CalloutOverride(
            site_id="SITE1", location_id="MW-1", figure_spec_id="SPEC1",
            map_type="GW", anchor_x=100.0, anchor_y=200.0,
            locked=True, notes="manual fix",
        )
        save_override(tmp_path / "fake.gdb", ov)

    insert_cm.insertRow.assert_called_once()
    row = insert_cm.insertRow.call_args[0][0]
    assert row[0] == "SITE1"          # SiteID
    assert row[4] == "MW-1"           # LocationID
    assert row[6] == 100.0            # AnchorX
    assert row[11] == 1               # LockedPlacement (int)
    assert row[12] == "manual fix"    # Notes


def test_save_override_raises_when_table_missing(tmp_path):
    import pytest
    mock = MagicMock()
    mock.Exists.return_value = False
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import (
            CalloutOverride, save_override,
        )
        with pytest.raises(RuntimeError, match="not found"):
            save_override(tmp_path / "fake.gdb",
                          CalloutOverride("S", "MW-1", "F"))


def test_clear_unlocked_overrides_deletes_and_returns_count(tmp_path):
    mock = MagicMock()
    mock.Exists.return_value = True
    deleted = []

    class _FakeCursor:
        def __iter__(self):
            for _ in range(3):
                yield ("OID",)

        def deleteRow(self):
            deleted.append(1)

    cm = _FakeCursor()
    mock.da.UpdateCursor.return_value.__enter__ = lambda s: cm
    mock.da.UpdateCursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import (
            clear_unlocked_overrides,
        )
        n = clear_unlocked_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1")
    assert n == 3
    assert len(deleted) == 3


def test_clear_unlocked_overrides_zero_when_table_missing(tmp_path):
    mock = MagicMock()
    mock.Exists.return_value = False
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import (
            clear_unlocked_overrides,
        )
        assert clear_unlocked_overrides(tmp_path / "fake.gdb", "S", "F") == 0
