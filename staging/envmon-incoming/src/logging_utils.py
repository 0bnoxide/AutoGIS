"""Logging utilities shared by all envmon modules.

Logs go to stderr and (optionally) a file. When running inside ArcGIS Pro,
messages are mirrored to the geoprocessing message window.
"""
from __future__ import annotations

import logging
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


def get_logger(name: str, logfile: Optional[Path] = None,
               level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if getattr(logger, "_envmon_configured", False):
        return logger
    logger.setLevel(level)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter(_FMT))
    logger.addHandler(sh)
    logger.addHandler(_ArcpyHandler())
    if logfile is not None:
        logfile = Path(logfile)
        logfile.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FMT))
        logger.addHandler(fh)
    logger._envmon_configured = True  # type: ignore[attr-defined]
    return logger
