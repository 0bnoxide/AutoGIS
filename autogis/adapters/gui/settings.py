"""Persisted GUI settings for the unified GUI adapter (ADR-0062).

Currently one setting: ``local_python`` -- the ``python.exe`` of a cloned
``arcgispro-py3`` environment, needed to run LOCAL (arcpy) tools from the
GUI (the executor already accepts it, ADR-0053; this is where the user's
choice is remembered between launches).

Backed by ``QSettings`` -- Qt's native cross-platform store (registry on
Windows, plist/ini elsewhere), so no new dependency and no hand-rolled
config-file format/location. Every function takes an optional ``store`` so
tests can inject a temp-ini ``QSettings`` and never touch the real registry;
callers in ``app.py`` pass nothing and get the shared per-user store.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

__all__ = ["get_local_python", "set_local_python"]

_ORG = "AutoGIS"
_APP = "gui"
_KEY = "local_python"


def _default_store() -> QSettings:
    return QSettings(_ORG, _APP)


def get_local_python(store: QSettings | None = None) -> str | None:
    """The persisted local_python path, or ``None`` if unset/blank."""
    value = (store or _default_store()).value(_KEY)
    text = str(value).strip() if value is not None else ""
    return text or None


def set_local_python(path: str | None, store: QSettings | None = None) -> None:
    """Persist ``path`` (a blank/``None`` value clears the setting). Syncs so
    a fresh QSettings handle -- e.g. the next launch -- sees it immediately."""
    store = store or _default_store()
    if path and str(path).strip():
        store.setValue(_KEY, str(path).strip())
    else:
        store.remove(_KEY)
    store.sync()
