"""Logging utilities shared by all autogis modules.

Logs go to stderr and (optionally) a file. When running inside ArcGIS Pro,
messages are mirrored to the geoprocessing message window. arcpy is imported
lazily inside ``_ArcpyHandler.emit`` (in a try/except) so this module imports
cleanly with no arcpy present (deltas C1 — the 9th arcpy-edge module, lazy/safe).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

_FMT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class _ArcpyHandler(logging.Handler):
    """Mirror log records to the ArcGIS geoprocessing messages when available."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - arcpy only
        try:
            import arcpy
        except ImportError:
            return
        msg = self.format(record)
        if record.levelno >= logging.ERROR:
            arcpy.AddError(msg)
        elif record.levelno >= logging.WARNING:
            arcpy.AddWarning(msg)
        else:
            arcpy.AddMessage(msg)


def _attach_logfile(logger: logging.Logger, logfile: Path) -> None:
    """Add a file handler for *logfile* unless this logger already has one.

    Compared on the absolute path FileHandler itself stores, so repeat calls
    with the same file stay idempotent while a call naming a *different* file
    still gets its handler -- the old ``_envmon_configured`` short-circuit
    dropped it and the caller's log file stayed empty (issue #433).
    """
    target = os.path.abspath(str(logfile))
    if any(isinstance(h, logging.FileHandler) and h.baseFilename == target
           for h in logger.handlers):
        return
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(target, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FMT))
    logger.addHandler(fh)


def get_logger(name: str, logfile: Optional[Path] = None,
               level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not getattr(logger, "_envmon_configured", False):
        logger.setLevel(level)
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter(_FMT))
        logger.addHandler(sh)
        logger.addHandler(_ArcpyHandler())
        # Our handlers are the delivery path; leaving propagate on emitted
        # every record a second time through any root handler a host app,
        # pytest or ArcGIS Pro had already installed (issue #433).
        logger.propagate = False
        logger._envmon_configured = True  # type: ignore[attr-defined]
    if logfile is not None:
        _attach_logfile(logger, Path(logfile))
    return logger
