"""#444 — a missing Env_GWContourPoints must be reported, not swallowed.

`_write_contour_points` accepted a QACollector and never touched it, and
returned silently when the feature class was absent (a geodatabase predating
the schema version that added it). The contour run then reported clean while
the potentiometric figure's points layer rendered empty.

arcpy seam, so the real arcpy calls stay `pragma: no cover` — this pins the
branch that decides whether QA hears about it, using a fake arcpy the same way
tests/test_qualification.py does.
"""
from pathlib import Path
from types import SimpleNamespace

from autogis.core.envmon import groundwater_contours as gwc
from autogis.core.common.qa import QACollector, SEV_WARNING


class _FakeArcPy:
    """Only the surface `_write_contour_points` touches."""

    def __init__(self, exists: bool):
        self._exists = exists
        self.inserted = []

    def Exists(self, _path):
        return self._exists

    @property
    def da(self):
        outer = self

        class _Cursor:
            def __init__(self, *_a, **_kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def __iter__(self):
                return iter(())

            def insertRow(self, row):
                outer.inserted.append(row)

        return SimpleNamespace(UpdateCursor=_Cursor, InsertCursor=_Cursor)


_PTS = [("MW-01", 1.0, 2.0, 10.0), ("MW-02", 3.0, 4.0, 11.0)]


def _call(arcpy, monkeypatch, qa):
    monkeypatch.setattr(gwc, "_arcpy", lambda: arcpy)
    gwc._write_contour_points(
        Path("C:/x/site.gdb"), "S1", "2026-01-02", "2026-01-02", _PTS, qa)


def test_missing_contour_points_fc_is_reported_not_swallowed(monkeypatch):
    qa = QACollector()
    _call(_FakeArcPy(exists=False), monkeypatch, qa)

    warned = [r for r in qa.records
              if r.category == "contour_points_layer_missing"]
    assert len(warned) == 1, "a skipped persist step must reach QA"
    assert warned[0].severity == SEV_WARNING
    assert "Env_GWContourPoints" in warned[0].message
    # An operator needs to know how to fix it, not just that it happened.
    assert "upgrade-schema" in (warned[0].recommended_action or "")


def test_present_contour_points_fc_writes_rows_and_stays_quiet(monkeypatch):
    qa = QACollector()
    arcpy = _FakeArcPy(exists=True)
    _call(arcpy, monkeypatch, qa)

    assert len(arcpy.inserted) == len(_PTS)
    assert not [r for r in qa.records
                if r.category == "contour_points_layer_missing"]


def test_upgrade_schema_command_named_in_the_warning_exists():
    """The recommended action names a CLI command; a rename would leave the
    operator chasing a command that no longer exists."""
    from autogis.adapters import cli

    assert "upgrade-schema" in cli.envmon.commands
