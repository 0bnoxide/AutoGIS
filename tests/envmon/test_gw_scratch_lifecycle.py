"""#523 — GW model pipeline scratch objects must not persist past a run.

Fixed-name scratch objects (``gwe_pts_<site>``, ``gwe_ebk_<site>``,
``gwm_loo_pts``, ...) survived a completed run in scratch.gdb; an operator
who added one to the map locked it, and the next same-session run died on
the EBK leg with a raw ``ERROR 000210``. Parity with concentration_surface
(#383): per-run tag, reverse-order cleanup after the run, and a lock-held
leftover reported as QA naming the exact path.

arcpy seam, so the real calls stay ``pragma: no cover`` — this drives the
whole pipeline (TIN + IDW + EBK contours, LOO + CrossValidation ranking)
through a fake arcpy that records every scratch object any geoprocessing
call creates, the same way tests/envmon/test_concentration_surface.py does.
"""
from pathlib import Path
from types import SimpleNamespace

from autogis.core.common.qa import QACollector, SEV_ERROR
from autogis.core.envmon import groundwater_contours as gwc
from autogis.core.envmon.gw_model_pipeline import (
    run_field_to_groundwater_model_pipeline,
)

SITE, EVENT = "QASITE", "2026-07-01"
WELLS = [("MW-1", 0.0, 0.0, 10.0), ("MW-2", 100.0, 0.0, 11.0),
         ("MW-3", 0.0, 100.0, 12.0), ("MW-4", 100.0, 100.0, 13.5)]
LAYER_PREFIXES = ("gwe_", "gwm_")   # bare (in-memory GA layer) names


class _Cursor:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __iter__(self):
        return iter(self._rows)

    def insertRow(self, _row):
        pass

    def deleteRow(self):
        pass

    def updateRow(self, _row):
        pass


class _Result:
    def getOutput(self, _i):
        return "10.5"


class _Tools:
    """Any geoprocessing tool. A string argument naming a not-yet-existing
    path under the scratch root, or a bare gwe_/gwm_ layer name, is that
    tool's output and is recorded as created; inputs already exist, so they
    are left alone."""

    def __init__(self, fake):
        self._fake = fake

    def __getattr__(self, _name):
        def tool(*args, **kwargs):
            for a in list(args) + list(kwargs.values()):
                self._fake.note_output(a)
            return _Result()
        return tool


class _Management(_Tools):
    def CreateFeatureclass(self, workspace, name, *_a, **_k):
        self._fake.note_output(str(Path(workspace) / name))

    def AddField(self, *_a, **_k):
        pass

    def Delete(self, path):
        if self._fake.lock and self._fake.lock in str(path):
            raise RuntimeError("ERROR 000464: Cannot get exclusive schema lock")
        self._fake.objects.discard(str(path))

    def CopyRaster(self, _src, dst):
        self._fake.objects.add(str(dst))


class _FakeArcpy:
    def __init__(self, tmp_path, lock=""):
        self.root = tmp_path / "project"          # scratch.gdb + TIN folders
        self.gdb = tmp_path / "site.gdb"
        self.env = SimpleNamespace(scratchGDB=str(self.root / "scratch.gdb"))
        self.lock = lock
        self.objects = {str(self.gdb / t) for t in (
            "MonitoringWells", "Env_WaterLevels", "Env_GWContourPoints",
            "Env_GWContours_Draft", "Env_GWFlowArrow_Draft",
            "Env_SurfaceRegistry", "GW_ModelRun", "GW_ModelCrossValidation")}
        self.created = []
        self.management = _Management(self)
        self.ddd = self.sa = self.ga = self.analysis = _Tools(self)
        self.da = SimpleNamespace(
            SearchCursor=self._search,
            InsertCursor=lambda *_a, **_k: _Cursor(),
            UpdateCursor=lambda *_a, **_k: _Cursor())
        self.Array = self.Point = self.Polyline = lambda *_a, **_k: None

    def is_scratch(self, s):
        return s.startswith(str(self.root)) or s.startswith(LAYER_PREFIXES)

    def note_output(self, a):
        if isinstance(a, str) and self.is_scratch(a) \
                and a not in self.objects:
            self.objects.add(a)
            self.created.append(a)

    def leftovers(self):
        return {o for o in self.objects if self.is_scratch(o)}

    def _search(self, _table, fields, where_clause=None):
        rows = {
            ("LocationID", "SHAPE@XY"):
                [(l, (x, y)) for l, x, y, _z in WELLS],
            ("LocationID", "GroundwaterElevation_ft"):
                [(l, z) for l, _x, _y, z in WELLS],
            ("Contour", "SHAPE@"): [(10.0, "line"), (11.0, "line")],
            ("Z",): [(10.5,)],
            ("OID@", "LocID"): [(i + 1, w[0]) for i, w in enumerate(WELLS)],
            ("Source_ID", "Included", "Predicted"):
                [(i + 1, "Yes", w[3] + 0.1) for i, w in enumerate(WELLS)],
        }
        return _Cursor(rows.get(tuple(fields), ()))

    def Exists(self, path):
        return str(path) in self.objects

    def Describe(self, _path):
        return SimpleNamespace(spatialReference="sr")

    def CheckExtension(self, _name):
        return "Available"

    def CheckOutExtension(self, _name):
        pass

    def CheckInExtension(self, _name):
        pass


def _install(monkeypatch, fake):
    from autogis.runtime import sessions
    monkeypatch.setattr(sessions, "arcpy_env", lambda: fake)
    monkeypatch.setattr(gwc, "_arcpy", lambda: fake)


def _run(fake, qa):
    return run_field_to_groundwater_model_pipeline(
        fake.gdb, SITE, EVENT, qa, methods=("TIN", "IDW", "EBK"))


def test_rerun_in_one_session_leaves_no_scratch_and_reuses_no_name(
        monkeypatch, tmp_path):
    """The #523 reproduction: two full runs, one session, no manual cleanup."""
    fake = _FakeArcpy(tmp_path)
    _install(monkeypatch, fake)
    per_run = []
    for _ in range(2):
        qa = QACollector()
        before = len(fake.created)
        summary = _run(fake, qa)
        assert summary["registry_written"]
        assert not any(summary["contours"][m]["skipped"]
                       for m in ("TIN", "IDW", "EBK"))
        assert not [r for r in qa.records if r.severity == SEV_ERROR]
        assert fake.leftovers() == set()
        per_run.append(set(fake.created[before:]))
    for names in per_run:   # both stages went through scratch, tagged
        assert any("gwe_ebk_" in n for n in names)
        assert any("gwm_loo_" in n for n in names)
        assert any("gwm_ebk_" in n for n in names)
        assert any(n.startswith("gwe_ebk_lyr_") for n in names)
    assert per_run[0].isdisjoint(per_run[1])


def test_lock_held_leftover_is_a_qa_warning_naming_the_path(
        monkeypatch, tmp_path):
    fake = _FakeArcpy(tmp_path, lock="gwe_ebk_")
    _install(monkeypatch, fake)
    qa = QACollector()
    summary = _run(fake, qa)
    # Outputs are already written; a stuck scratch object must not demote
    # the run to an error.
    assert summary["registry_written"]
    assert not summary["contours"]["EBK"]["skipped"]
    assert not [r for r in qa.records if r.severity == SEV_ERROR]
    warns = [r for r in qa.records if r.category == "scratch_cleanup_failed"]
    assert warns and all("gwe_ebk_" in r.message for r in warns)
    assert "delete it from Catalog" in warns[0].recommended_action
