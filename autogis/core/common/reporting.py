"""Reporter — the single emit channel over the thread-safe QA substrate.

The Reporter routes issue records into a (thread-safe) ``QACollector`` and
exposes cancel/progress hooks for long-running, cancellable, possibly parallel
work (deltas C6). Result records live on the manifest; the reporter is the one
channel through which they are emitted, so callers do not touch shared state
directly.
"""
from __future__ import annotations


class Reporter:
    def __init__(self, qa, *, cancel=None, progress=None):
        self._qa = qa
        self._cancel = cancel
        self._progress = progress

    def record_qa(self, record):
        self._qa.add(record)

    def record_result(self, result):
        # results live on the manifest; reporter is the single emit channel
        return result

    def cancelled(self) -> bool:
        return bool(self._cancel and self._cancel())

    def emit_progress(self, done, total):
        if self._progress:
            self._progress(done, total)
