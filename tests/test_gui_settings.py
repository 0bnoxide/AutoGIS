"""GUI settings persistence (ADR-0062): the local_python (arcgispro-py3
python.exe) path survives across launches via QSettings. Tests inject a
temp-ini QSettings store so they never touch the real registry."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from autogis.adapters.gui import settings as settings_mod


def _store(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)


def test_local_python_persists_across_handles(tmp_path):
    """set through one QSettings handle, read through a fresh one on the same
    file -- proves it is actually persisted, not just cached in one instance."""
    path = str(tmp_path / "s.ini")
    assert settings_mod.get_local_python(_store(tmp_path)) is None
    settings_mod.set_local_python(
        "C:/pro/arcgispro-py3/python.exe",
        QSettings(path, QSettings.Format.IniFormat))
    reopened = QSettings(path, QSettings.Format.IniFormat)
    assert settings_mod.get_local_python(reopened) == "C:/pro/arcgispro-py3/python.exe"


def test_empty_or_none_clears_the_setting(tmp_path):
    store = _store(tmp_path)
    settings_mod.set_local_python("C:/pro/python.exe", store)
    settings_mod.set_local_python("", store)      # blank -> cleared
    assert settings_mod.get_local_python(store) is None
    settings_mod.set_local_python("C:/pro/python.exe", store)
    settings_mod.set_local_python(None, store)    # None -> cleared
    assert settings_mod.get_local_python(store) is None
