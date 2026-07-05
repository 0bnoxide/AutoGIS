"""Workflow runner state machine (ADR-0055): advance/pause/resume/cancel.

`run_step` itself (subprocess assembly, QA-signal decisions) is already
covered by test_gui_executor.py -- this suite monkeypatches it with canned
`StepResult`s and is about the runner's state machine and thread-safety, not
child-process mechanics. Real ``Step(message=...)`` checkpoints are used
where that gives genuine integration for free (no subprocess launched).
"""
import threading

import pytest

from autogis.adapters.gui.executor import Decision, Step, StepResult
from autogis.adapters.gui.runner import RunState, Workflow, WorkflowRunner
import autogis.adapters.gui.runner as runner_mod


def _result(decision, reason="stub"):
    return StepResult(decision=decision, reason=reason, exit_code=0)


def test_all_continue_reaches_done(tmp_path, monkeypatch):
    job_dirs = []

    def fake_run_step(step, job_dir, *, local_python=None, timeout=None):
        job_dirs.append(job_dir)
        return _result(Decision.CONTINUE)

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    wf = Workflow("two-step", (Step(command=("a",)), Step(command=("b",))))
    r = WorkflowRunner(wf, tmp_path)
    assert r.status is RunState.PENDING
    r.advance()
    assert r.status is RunState.PENDING
    r.advance()
    assert r.status is RunState.DONE
    assert len(r.results) == 2
    assert job_dirs[0] != job_dirs[1]  # each step gets its own job_dir
    with pytest.raises(RuntimeError, match="done"):
        r.advance()


def test_halt_stops_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: _result(Decision.HALT, "boom"))
    wf = Workflow("one-step", (Step(command=("a",)), Step(command=("b",))))
    r = WorkflowRunner(wf, tmp_path)
    res = r.advance()
    assert res.decision is Decision.HALT
    assert r.status is RunState.HALTED
    with pytest.raises(RuntimeError, match="halted"):
        r.advance()


def test_pause_requires_resume_before_advancing(tmp_path, monkeypatch):
    decisions = iter([Decision.PAUSE_FOR_REVIEW, Decision.CONTINUE])
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: _result(next(decisions)))
    wf = Workflow("pause", (Step(command=("a",)), Step(command=("b",))))
    r = WorkflowRunner(wf, tmp_path)
    r.advance()
    assert r.status is RunState.PAUSED
    with pytest.raises(RuntimeError, match="paused"):
        r.advance()
    r.resume()
    assert r.status is RunState.PENDING
    r.advance()
    assert r.status is RunState.DONE


def test_resume_requires_paused_state(tmp_path):
    wf = Workflow("solo", (Step(message="review me"),))
    r = WorkflowRunner(wf, tmp_path)
    with pytest.raises(RuntimeError, match="PAUSED"):
        r.resume()  # still PENDING -- nothing to resume from


def test_checkpoint_step_pauses_without_subprocess(tmp_path):
    wf = Workflow("checkpoint", (Step(message="Review layouts before export."),))
    r = WorkflowRunner(wf, tmp_path)
    res = r.advance()
    assert res.decision is Decision.PAUSE_FOR_REVIEW
    assert r.status is RunState.PAUSED
    assert not (tmp_path / "step_00" / "qa.csv").exists()


def test_cancel_before_advance_is_immediate(tmp_path):
    wf = Workflow("cancel-early", (Step(message="x"),))
    r = WorkflowRunner(wf, tmp_path)
    r.cancel()
    assert r.status is RunState.CANCELLED
    with pytest.raises(RuntimeError, match="cancelled"):
        r.advance()


def test_cancel_while_paused_is_immediate(tmp_path):
    wf = Workflow("cancel-paused", (Step(message="x"), Step(message="y")))
    r = WorkflowRunner(wf, tmp_path)
    r.advance()
    assert r.status is RunState.PAUSED
    r.cancel()
    assert r.status is RunState.CANCELLED


def test_cancel_is_idempotent_and_noop_when_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: _result(Decision.CONTINUE))
    wf = Workflow("one", (Step(command=("a",)),))
    r = WorkflowRunner(wf, tmp_path)
    r.advance()
    assert r.status is RunState.DONE
    r.cancel()  # must not clobber a terminal DONE with CANCELLED
    assert r.status is RunState.DONE


def test_cancel_during_in_flight_step_applies_after_it_completes(tmp_path, monkeypatch):
    """Simulates a UI thread calling cancel() while a worker thread is
    blocked inside advance() running the current step's subprocess: the
    in-flight step still completes and its result is recorded, but
    cancellation wins over whatever decision that step reached."""
    holder = {}

    def fake_run_step(step, job_dir, *, local_python=None, timeout=None):
        holder["r"].cancel()
        return _result(Decision.CONTINUE)

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    wf = Workflow("mid-cancel", (Step(command=("a",)), Step(command=("b",))))
    r = WorkflowRunner(wf, tmp_path)
    holder["r"] = r

    res = r.advance()
    assert res.decision is Decision.CONTINUE
    assert r.status is RunState.CANCELLED
    assert len(r.results) == 1
    with pytest.raises(RuntimeError, match="cancelled"):
        r.advance()


def test_single_flight_guard_rejects_reentrant_advance(tmp_path, monkeypatch):
    holder = {}

    def fake_run_step(step, job_dir, **kw):
        with pytest.raises(RuntimeError, match="already in flight"):
            holder["r"].advance()
        return _result(Decision.CONTINUE)

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    wf = Workflow("reentrant", (Step(command=("a",)),))
    r = WorkflowRunner(wf, tmp_path)
    holder["r"] = r
    r.advance()
    assert r.status is RunState.DONE


def test_next_step_reflects_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: _result(Decision.CONTINUE))
    s1, s2 = Step(command=("a",)), Step(command=("b",))
    wf = Workflow("progress", (s1, s2))
    r = WorkflowRunner(wf, tmp_path)
    assert r.next_step is s1
    r.advance()
    assert r.next_step is s2
    r.advance()
    assert r.next_step is None


def test_empty_workflow_rejected(tmp_path):
    with pytest.raises(ValueError, match="at least one step"):
        WorkflowRunner(Workflow("empty", ()), tmp_path)


def test_real_background_thread_cancel(tmp_path, monkeypatch):
    """A genuine threading test: advance() runs on a worker thread while the
    main thread calls cancel() mid-step, proving the lock-guarded control
    surface is actually safe from a second thread -- the anticipated shape
    once a GUI drives this from a QThread/executor pool."""
    started = threading.Event()
    release = threading.Event()

    def fake_run_step(step, job_dir, **kw):
        started.set()
        release.wait(timeout=5)
        return _result(Decision.CONTINUE)

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    wf = Workflow("threaded", (Step(command=("a",)), Step(command=("b",))))
    r = WorkflowRunner(wf, tmp_path)

    worker = threading.Thread(target=r.advance)
    worker.start()
    assert started.wait(timeout=5)
    assert r.status is RunState.RUNNING
    r.cancel()
    release.set()
    worker.join(timeout=5)

    assert r.status is RunState.CANCELLED
    with pytest.raises(RuntimeError, match="cancelled"):
        r.advance()


def test_run_step_exception_leaves_halted_not_wedged_in_running(tmp_path, monkeypatch):
    """A run_step crash (TimeoutExpired, a LOCAL step missing local_python,
    an unknown command/param ValueError, ...) must not leave the runner
    permanently RUNNING: nothing could ever advance/cancel/resume it out."""
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: (_ for _ in ()).throw(ValueError("boom")))
    wf = Workflow("crash", (Step(command=("a",)), Step(command=("b",))))
    r = WorkflowRunner(wf, tmp_path)

    with pytest.raises(ValueError, match="boom"):
        r.advance()
    assert r.status is RunState.HALTED
    assert r.results == ()  # the crashed step produced no StepResult
    with pytest.raises(RuntimeError, match="halted"):
        r.advance()


def test_run_step_exception_while_cancel_requested_yields_cancelled(tmp_path, monkeypatch):
    holder = {}

    def fake_run_step(step, job_dir, **kw):
        holder["r"].cancel()  # recorded, since state is RUNNING mid-call
        raise ValueError("boom")

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    wf = Workflow("crash-cancel", (Step(command=("a",)),))
    r = WorkflowRunner(wf, tmp_path)
    holder["r"] = r

    with pytest.raises(ValueError, match="boom"):
        r.advance()
    assert r.status is RunState.CANCELLED


def test_pause_on_last_step_resumes_to_done_not_index_error(tmp_path):
    """PAUSE_FOR_REVIEW on the final step (a trailing checkpoint) leaves
    _index == len(steps); resume() must land on DONE, not PENDING, or the
    next advance() indexes past the end of workflow.steps."""
    wf = Workflow("trailing-checkpoint",
                 (Step(message="review before finishing"),))
    r = WorkflowRunner(wf, tmp_path)
    r.advance()
    assert r.status is RunState.PAUSED
    r.resume()
    assert r.status is RunState.DONE
    with pytest.raises(RuntimeError, match="done"):
        r.advance()
