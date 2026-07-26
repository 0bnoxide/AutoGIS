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


# ---------------------------------------------------------- MapType scoping
# Regression: load_overrides keyed its dict by LocationID with NO MapType
# filter, so two rows for one LocationID under different MapTypes collapsed
# (last-read-wins). load_overrides is now scoped to one map_type.

def _where_aware_arcpy(rows):
    """arcpy mock whose SearchCursor honors the MapType constraint in the
    where clause, simulating the GDB's own row filtering. Not a fake of the
    fix — it filters on whatever WHERE the function actually builds, so it
    fails when the WHERE lacks a MapType constraint.

    rows: (LocationID, AnchorX, AnchorY, OffsetX, OffsetY, PrefQuad,
           Locked, MapType) — the 8th field is stripped before the cursor.
    """
    arcpy = MagicMock()
    arcpy.Exists.return_value = True

    def _search(table, fields, where_clause=""):
        def keep(r):
            mt = r[7]
            if "MapType IS NULL" in where_clause:
                return mt in (None, "")
            if "MapType" not in where_clause:
                return True  # unscoped WHERE -> every map type leaks in
            return f"MapType = '{mt}'" in where_clause
        selected = [r[:7] for r in rows if keep(r)]
        cm = MagicMock()
        cm.__enter__ = lambda s: iter(selected)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    arcpy.da.SearchCursor.side_effect = _search
    return arcpy


_TWO_MAP_TYPES = [
    ("MW-1", 100.0, 100.0, 0.0, 0.0, None, 0, "GW"),
    ("MW-1", 900.0, 900.0, 0.0, 0.0, None, 0, "SOIL"),
]


def test_load_overrides_where_includes_map_type(tmp_path):
    mock = _mock_arcpy(exists=True, cursor_rows=[])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import load_overrides
        load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1", "GW")
    where = mock.da.SearchCursor.call_args.kwargs["where_clause"]
    assert "MapType = 'GW'" in where


def test_load_overrides_scopes_to_map_type_no_collapse(tmp_path):
    """The bug: same LocationID under two MapTypes must NOT collapse.

    Each scoped call returns only its own MapType's row. Against the old
    unscoped WHERE the where-aware mock leaks both rows into every call and
    GW's origin gets overwritten by SOIL — this test fails there.
    """
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=_where_aware_arcpy(_TWO_MAP_TYPES)):
        from autogis.core.envmon.manage_callout_overrides import load_overrides
        gw = load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1", "GW")
        soil = load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1", "SOIL")
    assert gw["MW-1"]["origin"] == (100.0, 100.0)
    assert soil["MW-1"]["origin"] == (900.0, 900.0)


def test_load_overrides_blank_map_type_matches_null(tmp_path):
    mock = _mock_arcpy(exists=True, cursor_rows=[])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import load_overrides
        load_overrides(tmp_path / "fake.gdb", "SITE1", "SPEC1")
    where = mock.da.SearchCursor.call_args.kwargs["where_clause"]
    assert "MapType IS NULL" in where


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
        n = clear_unlocked_overrides(
            tmp_path / "fake.gdb", "SITE1", "SPEC1", map_type="GW")
    assert n == 3
    assert len(deleted) == 3
    where = mock.da.UpdateCursor.call_args.kwargs["where_clause"]
    assert "MapType = 'GW'" in where


def test_clear_unlocked_overrides_zero_when_table_missing(tmp_path):
    mock = MagicMock()
    mock.Exists.return_value = False
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import (
            clear_unlocked_overrides,
        )
        assert clear_unlocked_overrides(tmp_path / "fake.gdb", "S", "F") == 0


# ---------------------------------------------------------- get_override
# Full-row read keyed by (SiteID, FigureSpecID, MapType, LocationID) —
# the missing piece for a lossless lock/unlock round-trip (save_override
# rewrites the whole row).

# One row in _WRITE_FIELDS order.
_FULL_ROW = ("SITE1", None, "GW", "SPEC1", "MW-1", "S-9",
             100.0, 200.0, 1.5, 2.5, "NE", 1, "hand placed")


def test_get_override_none_when_table_missing(tmp_path):
    mock = _mock_arcpy(exists=False)
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import get_override
        assert get_override(tmp_path / "fake.gdb", "S", "F", "MW-1") is None


def test_get_override_none_when_no_row(tmp_path):
    mock = _mock_arcpy(exists=True, cursor_rows=[])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import get_override
        assert get_override(tmp_path / "fake.gdb", "S", "F", "MW-1") is None


def test_get_override_returns_full_row(tmp_path):
    mock = _mock_arcpy(exists=True, cursor_rows=[_FULL_ROW])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import get_override
        ov = get_override(tmp_path / "fake.gdb", "SITE1", "SPEC1", "MW-1",
                          map_type="GW")
    assert ov is not None
    assert ov.site_id == "SITE1"
    assert ov.map_type == "GW"
    assert ov.sample_id == "S-9"
    assert ov.anchor_x == 100.0 and ov.anchor_y == 200.0
    assert ov.offset_x == 1.5 and ov.offset_y == 2.5
    assert ov.preferred_quadrant == "NE"
    assert ov.locked is True
    assert ov.notes == "hand placed"


def test_get_override_blank_map_type_matches_null(tmp_path):
    """A blank map_type must match both '' and NULL in the where clause."""
    mock = _mock_arcpy(exists=True, cursor_rows=[])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import get_override
        get_override(tmp_path / "fake.gdb", "S", "F", "MW-1", map_type="")
    where = mock.da.SearchCursor.call_args.kwargs["where_clause"]
    assert "MapType IS NULL" in where


def test_get_override_quotes_apostrophes(tmp_path):
    mock = _mock_arcpy(exists=True, cursor_rows=[])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=mock):
        from autogis.core.envmon.manage_callout_overrides import get_override
        get_override(tmp_path / "fake.gdb", "O'Brien Site", "F", "MW-1")
    where = mock.da.SearchCursor.call_args.kwargs["where_clause"]
    assert "O''Brien Site" in where


def test_get_then_save_round_trips_every_field(tmp_path):
    """unlock's contract: read full row, flip locked, rewrite losslessly."""
    read_mock = _mock_arcpy(exists=True, cursor_rows=[_FULL_ROW])
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=read_mock):
        from autogis.core.envmon.manage_callout_overrides import get_override
        ov = get_override(tmp_path / "fake.gdb", "SITE1", "SPEC1", "MW-1",
                          map_type="GW")

    write_mock = MagicMock()
    write_mock.Exists.return_value = True
    update_cm = MagicMock()
    update_cm.__iter__ = lambda s: iter([])
    write_mock.da.UpdateCursor.return_value.__enter__ = lambda s: update_cm
    write_mock.da.UpdateCursor.return_value.__exit__ = MagicMock(
        return_value=False)
    insert_cm = MagicMock()
    write_mock.da.InsertCursor.return_value.__enter__ = lambda s: insert_cm
    write_mock.da.InsertCursor.return_value.__exit__ = MagicMock(
        return_value=False)
    with patch("autogis.core.envmon.manage_callout_overrides._arcpy",
               return_value=write_mock):
        from autogis.core.envmon.manage_callout_overrides import save_override
        save_override(tmp_path / "fake.gdb", ov)

    row = insert_cm.insertRow.call_args[0][0]
    assert row == list(_FULL_ROW), "get_override -> save_override lost data"
