"""Reporter — emit channel over the thread-safe QA substrate.

Routes issue records into a (thread-safe) ``QACollector`` and exposes
cancel/progress hooks for long-running, cancellable, possibly parallel work
(deltas C6).

Not currently wired into any production tool: its only caller is
``tests/test_reporting.py``. Future-use abstraction, not dead code — keep it
until a tool is migrated to it, or it is deliberately removed (#450).
"""
from __future__ import annotations


class Reporter:
    def __init__(self, qa, *, cancel=None, progress=None):
        self._qa = qa
        self._cancel = cancel
        self._progress = progress
        self.results = []

    def record_qa(self, record):
        self._qa.add(record)

    def record_result(self, result):
        self.results.append(result)
        return result

    def cancelled(self) -> bool:
        return bool(self._cancel and self._cancel())

    def emit_progress(self, done, total):
        if self._progress:
            self._progress(done, total)
