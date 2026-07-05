"""Sequential multi-step workflow runner for the unified GUI adapter.

Drives an ordered :class:`Workflow` of :class:`~autogis.adapters.gui.executor.Step`
objects through :func:`~autogis.adapters.gui.executor.run_step`, one step at a
time — the generalized ``FullPipeline`` (ADR-0050 decision 4). Pure logic:
no GUI toolkit, no arcpy, same scoping as the ADR-0052 introspector and the
ADR-0053 executor.

``advance()`` is a single blocking call: it runs exactly one step (one child
process) and returns. That is a deliberate scope boundary, not an oversight.
Putting ``advance()`` on a background thread so a real GUI's event loop
doesn't freeze is the caller's job — the right mechanism (``QThread``, a
``concurrent.futures`` pool, an asyncio executor) depends on the toolkit the
caller is written against, a decision this framework-agnostic module
shouldn't make. What this module owns is everything that mechanism needs to
be correct: one call advances exactly one step, state is readable at any
time, and ``cancel()``/``resume()`` are plain thread-safe methods a UI thread
can call while a worker thread is blocked inside ``advance()``.

# ponytail: cancel() cannot force-kill a step already in flight — run_step's
# subprocess.run() owns the child until it exits, so cancellation during a
# running step takes effect only once that step naturally completes.
# Force-kill would need run_step to expose the Popen handle instead of
# blocking on subprocess.run(); add that if a hung LOCAL (arcpy) step turns
# out to need it in practice.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .executor import Decision, Step, StepResult, run_step

__all__ = ["RunState", "Workflow", "WorkflowRunner"]


class RunState(Enum):
    PENDING = "pending"      # advance() not yet called for the next step
    RUNNING = "running"      # a step's subprocess is in flight right now
    PAUSED = "paused"        # last step returned PAUSE_FOR_REVIEW; needs resume()
    DONE = "done"            # every step returned CONTINUE; nothing left to run
    HALTED = "halted"        # a step returned HALT; terminal
    CANCELLED = "cancelled"  # cancel() was called; terminal


_TERMINAL = {RunState.DONE, RunState.HALTED, RunState.CANCELLED}


@dataclass(frozen=True)
class Workflow:
    """An ordered, named sequence of steps."""

    name: str
    steps: tuple[Step, ...]


class WorkflowRunner:
    """Drive one :class:`Workflow` through ``run_step``, one step at a time.

    Every method takes an internal lock, so a UI thread can safely read
    ``.status``/``.results`` or call ``.cancel()``/``.resume()`` while a
    worker thread is blocked inside ``.advance()`` — the anticipated shape
    once a GUI wraps this runner in a background thread.
    """

    def __init__(self, workflow: Workflow, job_root: str | Path, *,
                 local_python: str | Path | None = None,
                 timeout: float | None = None):
        if not workflow.steps:
            raise ValueError("Workflow must have at least one step.")
        self.workflow = workflow
        self._job_root = Path(job_root)
        self._local_python = local_python
        self._timeout = timeout
        self._lock = threading.Lock()
        self._index = 0
        self._results: list[StepResult] = []
        self._state = RunState.PENDING
        self._cancel_requested = False

    @property
    def status(self) -> RunState:
        with self._lock:
            return self._state

    @property
    def results(self) -> tuple[StepResult, ...]:
        with self._lock:
            return tuple(self._results)

    @property
    def next_step(self) -> Step | None:
        """The step ``advance()`` would run next, or the in-flight one
        during RUNNING; ``None`` once terminal."""
        with self._lock:
            if self._state in _TERMINAL or self._index >= len(self.workflow.steps):
                return None
            return self.workflow.steps[self._index]

    def cancel(self) -> None:
        """Stop the workflow. Safe from any thread, at any time.

        If no step is currently running, takes effect immediately. If a
        step's subprocess is in flight, the request is recorded and applied
        as soon as that step completes (see the module docstring — the
        in-flight child process is not force-killed).
        """
        with self._lock:
            if self._state in _TERMINAL:
                return
            self._cancel_requested = True
            if self._state is not RunState.RUNNING:
                self._state = RunState.CANCELLED

    def resume(self) -> None:
        """Clear a PAUSE_FOR_REVIEW checkpoint so the next ``advance()``
        runs the following step. Only valid from PAUSED."""
        with self._lock:
            if self._state is not RunState.PAUSED:
                raise RuntimeError(
                    f"resume() requires state PAUSED, not {self._state.value}")
            self._state = RunState.PENDING

    def advance(self) -> StepResult:
        """Run exactly one step (one child process) and return its result.

        Call this from a background thread in a real GUI — it blocks for as
        long as the step's process runs. Raises ``RuntimeError`` if the
        workflow is already terminal, paused (call ``resume()`` first), or a
        step is already in flight (single-flight: only one ``advance()`` may
        run at a time).
        """
        with self._lock:
            if self._state in _TERMINAL:
                raise RuntimeError(
                    f"Workflow is {self._state.value}; no more steps to run.")
            if self._state is RunState.PAUSED:
                raise RuntimeError("Workflow is paused; call resume() first.")
            if self._state is RunState.RUNNING:
                raise RuntimeError("A step is already in flight.")
            index = self._index
            self._state = RunState.RUNNING

        step = self.workflow.steps[index]
        job_dir = self._job_root / f"step_{index:02d}"
        result = run_step(step, job_dir, local_python=self._local_python,
                          timeout=self._timeout)

        with self._lock:
            self._results.append(result)
            self._index += 1
            if self._cancel_requested:
                self._state = RunState.CANCELLED
            elif result.decision is Decision.HALT:
                self._state = RunState.HALTED
            elif result.decision is Decision.PAUSE_FOR_REVIEW:
                self._state = RunState.PAUSED
            elif self._index >= len(self.workflow.steps):
                self._state = RunState.DONE
            else:
                self._state = RunState.PENDING
        return result
