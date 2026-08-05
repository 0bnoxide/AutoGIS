"""Regression tests for issue #433 — get_logger's configure-once short-circuit.

Two defects: a later call passing a *different* logfile silently dropped that
file handler, and ``propagate`` was never turned off so every record was
emitted a second time through any root handler a host app, pytest or ArcGIS
Pro had already installed.
"""
from __future__ import annotations

import logging
import uuid

from autogis.core.common.logging import get_logger


def _fresh_name() -> str:
    """A logger name no other test has configured (logging.getLogger is a
    process-wide singleton registry)."""
    return f"autogis.test.{uuid.uuid4().hex}"


def test_does_not_propagate_to_root_handlers():
    """A root handler installed by the host must not receive our records too --
    that is how every message ended up printed twice."""
    name = _fresh_name()
    root_records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            root_records.append(record.getMessage())

    handler = _Capture()
    logging.getLogger().addHandler(handler)
    try:
        get_logger(name).info("hello")
        assert root_records == []
    finally:
        logging.getLogger().removeHandler(handler)


def test_later_call_with_a_new_logfile_attaches_it(tmp_path):
    """The short-circuit used to return before touching handlers, so the
    caller's log file stayed empty with no error."""
    name = _fresh_name()
    get_logger(name)                       # configure with no logfile
    logfile = tmp_path / "sub" / "run.log"
    log = get_logger(name, logfile=logfile)
    log.info("second-call message")
    for h in log.handlers:
        h.flush()
    assert logfile.exists()
    assert "second-call message" in logfile.read_text(encoding="utf-8")


def test_repeat_calls_with_the_same_logfile_do_not_stack_handlers(tmp_path):
    """Attaching on every call would duplicate each line once per call."""
    name = _fresh_name()
    logfile = tmp_path / "run.log"
    for _ in range(3):
        log = get_logger(name, logfile=logfile)
    log.info("once")
    for h in log.handlers:
        h.flush()
    assert sum(isinstance(h, logging.FileHandler) for h in log.handlers) == 1
    assert logfile.read_text(encoding="utf-8").count("once") == 1


def test_a_second_distinct_logfile_is_added_alongside_the_first(tmp_path):
    name = _fresh_name()
    first, second = tmp_path / "a.log", tmp_path / "b.log"
    get_logger(name, logfile=first)
    log = get_logger(name, logfile=second)
    log.info("both")
    for h in log.handlers:
        h.flush()
    assert "both" in first.read_text(encoding="utf-8")
    assert "both" in second.read_text(encoding="utf-8")
