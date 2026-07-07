"""Site Config Builder dialog tests (ADR-0065).

Offscreen Qt, real widgets/threads -- same technique as test_gui_app.py.
The two untestable seams are stubbed: ``config_builder.fetch_sublayers``
(network + arcgis) and ``config_builder_dialog._pick_path`` (native modal
dialogs). MainWindow instantiations use the same real-QSettings isolation
guard as test_gui_app.py.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

import autogis.adapters.gui.config_builder as builder_mod
import autogis.adapters.gui.config_builder_dialog as dialog_mod
from autogis.adapters.gui import settings as settings_mod
from autogis.adapters.gui.app import MainWindow
from autogis.adapters.gui.config_builder import SublayerEntry
from autogis.adapters.gui.config_builder_dialog import ConfigBuilderDialog
from autogis.core.common.config import HarvestConfig


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path, monkeypatch):
    """Same guard as test_gui_app.py: no test may touch the real per-user
    QSettings (MainWindow reads local_python at construction)."""
    store = QSettings(str(tmp_path / "qsettings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings_mod, "_default_store", lambda: store)


def _pump_until(condition, timeout_ms=5000, step_ms=10):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
    assert condition(), "timed out waiting for condition"


ENTRIES = [
    SublayerEntry(label="5 — Daily_Diary_Photos (Table, has attachments)",
                  url="https://x/FeatureServer/5", has_attachments=True),
    SublayerEntry(label="0 — Boundaries (Layer, no attachments)",
                  url="https://x/FeatureServer/0", has_attachments=False),
]


def _fill_valid(dlg, tmp_path):
    dlg._item_id.setText("abc123")
    dlg._directory.setText(str(tmp_path / "out"))
    dlg._group_template.setText("{OBJECTID}")
    dlg._filename_template.setText("{OBJECTID}_{name}")


# --- defaults ----------------------------------------------------------------

def test_defaults_match_schema(qapp):
    dlg = ConfigBuilderDialog()
    assert dlg._incremental.isChecked() is False
    assert dlg._skip_existing.isChecked() is True
    assert dlg._retries.value() == 3
    assert dlg._backoff.value() == 2.0
    assert dlg._where.text() == ""


# --- item_id XOR url ----------------------------------------------------------

def test_filling_item_id_disables_url_and_back(qapp):
    dlg = ConfigBuilderDialog()
    assert dlg._item_id.isEnabled() and dlg._url.isEnabled()
    dlg._item_id.setText("abc123")
    assert not dlg._url.isEnabled()
    dlg._item_id.clear()
    assert dlg._url.isEnabled()
    dlg._url.setText("https://x/FeatureServer/5")
    assert not dlg._item_id.isEnabled()


# --- fetch gating + worker ------------------------------------------------------

def test_fetch_disabled_until_profile_and_item_id(qapp):
    dlg = ConfigBuilderDialog()
    assert not dlg._fetch_button.isEnabled()
    dlg._profile.setText("corp")
    dlg._profile.textChanged.emit(dlg._profile.text())  # setText fires it; be explicit
    dlg._item_id.setText("abc123")
    assert dlg._fetch_button.isEnabled()
    dlg._item_id.clear()
    assert not dlg._fetch_button.isEnabled()


def test_fetch_populates_combo_off_the_ui_thread(qapp, monkeypatch):
    seen = {}

    def fake_fetch(profile, item_id):
        seen["args"] = (profile, item_id)
        return list(ENTRIES)

    monkeypatch.setattr(builder_mod, "fetch_sublayers", fake_fetch)
    dlg = ConfigBuilderDialog()
    dlg._profile.setText("corp")
    dlg._item_id.setText("abc123")
    dlg._on_fetch()
    _pump_until(lambda: dlg._worker is None)
    assert seen["args"] == ("corp", "abc123")
    # row 0 stays the blank "nothing picked" item
    assert [dlg._sublayer_box.itemText(i)
            for i in range(dlg._sublayer_box.count())] == \
        ["", ENTRIES[0].label, ENTRIES[1].label]
    assert "Found 2" in dlg._status.text()
    assert dlg._fetch_button.isEnabled()  # re-enabled for a re-fetch


def test_fetch_failure_reported_inline_and_button_reenabled(qapp, monkeypatch):
    def boom(profile, item_id):
        raise LookupError("No AGOL item found with ID 'abc123'")

    monkeypatch.setattr(builder_mod, "fetch_sublayers", boom)
    dlg = ConfigBuilderDialog()
    dlg._profile.setText("corp")
    dlg._item_id.setText("abc123")
    dlg._on_fetch()
    _pump_until(lambda: dlg._worker is None)
    assert "Fetch failed" in dlg._status.text()
    assert "No AGOL item found" in dlg._status.text()
    assert dlg._fetch_button.isEnabled()


def test_picking_sublayer_writes_url_and_clears_item_id(qapp, monkeypatch):
    monkeypatch.setattr(builder_mod, "fetch_sublayers",
                        lambda profile, item_id: list(ENTRIES))
    dlg = ConfigBuilderDialog()
    dlg._profile.setText("corp")
    dlg._item_id.setText("abc123")
    dlg._on_fetch()
    _pump_until(lambda: dlg._worker is None)
    dlg._sublayer_box.setCurrentIndex(1)  # first real entry
    # the decided design: resolved URL into layer.url, NOT item_id + index
    assert dlg._url.text() == "https://x/FeatureServer/5"
    assert dlg._item_id.text() == ""
    assert not dlg._item_id.isEnabled()   # xor now favors the URL side


def test_reselecting_blank_row_changes_nothing(qapp, monkeypatch):
    monkeypatch.setattr(builder_mod, "fetch_sublayers",
                        lambda profile, item_id: list(ENTRIES))
    dlg = ConfigBuilderDialog()
    dlg._profile.setText("corp")
    dlg._item_id.setText("abc123")
    dlg._on_fetch()
    _pump_until(lambda: dlg._worker is None)
    dlg._sublayer_box.setCurrentIndex(1)
    dlg._sublayer_box.setCurrentIndex(0)  # back to blank
    assert dlg._url.text() == "https://x/FeatureServer/5"  # kept, not wiped


# --- browse ---------------------------------------------------------------------

def test_browse_directory_uses_dir_dialog_and_fills_field(qapp, monkeypatch):
    seen = {}

    def fake_pick(kind, parent, title, start):
        seen["kind"], seen["start"] = kind, start
        return "C:/picked/folder"

    monkeypatch.setattr(dialog_mod, "_pick_path", fake_pick)
    dlg = ConfigBuilderDialog()
    dlg._directory.setText("prev")
    dlg.findChild(QPushButton, "dir-browse").click()
    assert seen["kind"] == "dir"
    assert seen["start"] == "prev"
    assert dlg._directory.text() == "C:/picked/folder"


def test_browse_directory_cancel_leaves_field(qapp, monkeypatch):
    monkeypatch.setattr(dialog_mod, "_pick_path", lambda *a: "")
    dlg = ConfigBuilderDialog()
    dlg._directory.setText("orig")
    dlg._on_browse_directory()
    assert dlg._directory.text() == "orig"


# --- save -------------------------------------------------------------------------

def test_save_writes_yaml_harvestconfig_can_load(qapp, monkeypatch, tmp_path):
    dest = tmp_path / "config.yaml"
    monkeypatch.setattr(dialog_mod, "_pick_path", lambda *a: str(dest))
    dlg = ConfigBuilderDialog()
    _fill_valid(dlg, tmp_path)
    dlg._profile.setText("corp")
    dlg._where.setText("Status = 'Open'")
    dlg._incremental.setChecked(True)
    dlg._retries.setValue(5)
    dlg._backoff.setValue(1.5)
    dlg._on_save()
    assert "Saved" in dlg._status.text()
    loaded = HarvestConfig.load(dest)  # validated by the harvester itself
    assert loaded.item_id == "abc123"
    assert loaded.where == "Status = 'Open'"
    assert loaded.incremental is True
    assert loaded.retries == 5
    assert loaded.backoff_seconds == 1.5


def test_save_validation_error_shown_before_file_dialog(qapp, monkeypatch, tmp_path):
    picked = {"n": 0}

    def fake_pick(*a):
        picked["n"] += 1
        return str(tmp_path / "config.yaml")

    monkeypatch.setattr(dialog_mod, "_pick_path", fake_pick)
    dlg = ConfigBuilderDialog()
    _fill_valid(dlg, tmp_path)
    dlg._directory.clear()             # invalid: required output key missing
    dlg._on_save()
    assert "Fix before saving" in dlg._status.text()
    assert "directory" in dlg._status.text()
    assert picked["n"] == 0            # never opened the save dialog
    assert not (tmp_path / "config.yaml").exists()


def test_save_both_item_id_and_url_rejected_via_load_xor(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_mod, "_pick_path",
                        lambda *a: str(tmp_path / "config.yaml"))
    dlg = ConfigBuilderDialog()
    _fill_valid(dlg, tmp_path)
    # bypass the widget-level xor (defense in depth: load() is the real rule)
    dlg._url.setText("https://x/FeatureServer/5")
    dlg._on_save()
    assert "Fix before saving" in dlg._status.text()
    assert "exactly one" in dlg._status.text()
    assert not (tmp_path / "config.yaml").exists()


def test_save_cancel_writes_nothing(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(dialog_mod, "_pick_path", lambda *a: "")
    dlg = ConfigBuilderDialog()
    _fill_valid(dlg, tmp_path)
    dlg._on_save()
    assert list(tmp_path.glob("*.yaml")) == []


# --- MainWindow entry point ---------------------------------------------------------

def test_main_window_button_opens_dialog(qapp, tmp_path):
    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings_store=store)
    btn = next(b for b in win.findChildren(QPushButton)
               if b.text() == "Build Site Config…")
    btn.click()
    assert isinstance(win._config_dialog, ConfigBuilderDialog)
    assert win._config_dialog.isVisible()
    win._config_dialog.close()
    assert win.close()
