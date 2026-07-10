"""Per-step QA-signal executor for the unified GUI adapter.

Given one workflow step — a leaf ``autogis`` CLI command plus user-supplied
values, or a bare review checkpoint — launch it as a child CLI process and
decide from its exit code plus an executor-injected ``qa.csv`` whether the
run HALTs, CONTINUEs, or PAUSEs for human review (ADR-0053). Pure logic +
``subprocess``: no GUI toolkit, no arcpy — same scoping as the ADR-0052
introspector. This module deliberately writes NO run-history records: the
child process goes through the CLI seam, which is the recording hook
(ADR-0050 decision 6).

Why the exit code alone can't gate:

- ``0`` = QA PASS *or* warnings-under-threshold (``_render_qa`` only raises
  on FAIL, via ``qa.status(allow_warnings=(fail_on != "warning"))``).
- ``1`` = QA FAIL, *or* a guard refusal (``ClickException``), *or* a
  business-logic failure, *or* an unhandled crash — indistinguishable.
- ``2`` = Click ``UsageError``: bad arguments, a pre-flight/config problem.

So the executor injects ``--report <job_dir>/qa.csv`` on every command that
declares the shared ``--report`` option and reads the CSV back: exit != 0
with blocking-capable rows is a QA-FAIL halt (the rows are the reason);
exit != 0 without them is a usage/crash/refusal halt (stderr is the reason);
exit 0 with WARNING+ rows can pause for review when the step asks for it.

The QA **JSON summary's ``"status"`` field is banned as a gating signal**:
``QACollector.write_json_summary`` computes it via ``self.status()`` with
*default* thresholds (``allow_warnings=True``), while the process exit code
comes from ``_render_qa``'s ``status(allow_warnings=(fail_on !=
"warning"))`` — under ``--fail-on warning`` the JSON says ``PASS`` while the
process exits 1. It also carries only counts, no per-record detail. stdout
is likewise never parsed (fragile, human-facing); the CSV report is the one
per-record detail source.
"""
from __future__ import annotations

import csv
import dataclasses
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

import click

from autogis.runtime.capabilities import TOOLS, requires_arcpy

__all__ = [
    "Decision", "Step", "StepResult",
    "needs_arcpy_env", "build_argv", "decide", "run_step",
]

_SEV_ORDER = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}
_BLOCKING = ("WARNING", "ERROR", "CRITICAL")
_MAX_REASON_ROWS = 5


class Decision(Enum):
    CONTINUE = "continue"
    PAUSE_FOR_REVIEW = "pause_for_review"
    HALT = "halt"


@dataclass(frozen=True)
class Step:
    """One workflow step.

    ``command=None`` declares a bare review checkpoint: no child process,
    always PAUSE_FOR_REVIEW — the FullPipeline precedent (``toolbox.pyt``
    deliberately stops before export, telling the user to review layouts and
    run Tool 6 themselves).
    """

    command: tuple[str, ...] | None = None  # e.g. ("envmon", "reconcile-locations")
    values: Mapping[str, object] = field(default_factory=dict)  # param name -> value
    fail_on: str | None = None      # "error"|"warning"; passed through if the command has --fail-on
    pause_on_warning: bool = False  # exit-0 WARNING+ rows -> PAUSE_FOR_REVIEW
    message: str = ""               # checkpoint text / step annotation


@dataclass(frozen=True)
class StepResult:
    decision: Decision
    reason: str
    exit_code: int | None = None    # None for checkpoint steps
    qa_rows: tuple[dict, ...] = ()  # parsed qa.csv rows; () when no report
    stdout: str = ""
    stderr: str = ""
    report_out: str = ""    # where the qa.csv was copied for the user (#205)
    report_error: str = ""  # copy-out failure message; kept distinct from success


def _resolve_command(path: Sequence[str]) -> click.Command:
    from autogis.adapters.cli import autogis as node  # lazy: keeps import cheap
    for i, name in enumerate(path):
        if not isinstance(node, click.Group) or name not in node.commands:
            raise ValueError(
                f"Unknown CLI command path: {' '.join(path[:i + 1])!r}")
        node = node.commands[name]
    return node


def needs_arcpy_env(path: Sequence[str]) -> bool:
    """True when the tool is LOCAL (arcpy) per the capability registry.

    Leaf-first lookup so sub-subcommands resolve through their group entry
    (e.g. ``envmon manage-callout-overrides lock`` -> "manage-callout-overrides").
    Unknown names default to the headless env — the CLI's own runtime guard
    is the backstop and refuses cleanly (exit 1, no qa.csv -> HALT).
    """
    for name in reversed(tuple(path)):
        if name in TOOLS:
            return requires_arcpy(name)
    return False


def _opt_string(strings: Sequence[str]) -> str:
    longs = [s for s in strings if s.startswith("--")]
    return longs[0] if longs else strings[0]


def build_argv(path: Sequence[str], values: Mapping[str, object], *,
               python: str | Path | None = None,
               report_path: str | Path | None = None,
               fail_on: str | None = None) -> list[str]:
    """Assemble the child-process argv for one leaf CLI command.

    Invokes ``<python> -m autogis.adapters.cli`` — the same click group the
    ``autogis`` console script targets (pyproject ``[project.scripts]``) —
    so the interpreter, and therefore the environment (headless vs an
    arcgispro-py3 clone), is an explicit choice rather than a PATH lookup.

    ``values`` keys are click param names (``FormField.name``); the actual
    option strings come from the command's own ``param.opts``, never
    reconstructed from the name (``--config`` is named ``config_path``).
    ``report_path``/``fail_on`` are injected only when the command declares
    the shared ``--report``/``--fail-on`` options. ``report_path`` overrides
    any caller-supplied ``report`` value: the executor owns the QA channel
    during a workflow run (copy qa.csv out of the job dir if it is wanted
    elsewhere); a step-config ``fail_on`` never overrides an explicit value.
    """
    cmd = _resolve_command(path)
    params = {p.name: p for p in cmd.params}
    unknown = set(values) - set(params)
    if unknown:
        raise ValueError(
            f"{' '.join(path)}: unknown parameter(s) {sorted(unknown)}")

    vals = dict(values)
    if report_path is not None and "report" in params:
        vals["report"] = str(report_path)
    if fail_on is not None and "fail_on" in params and "fail_on" not in values:
        vals["fail_on"] = fail_on

    positional: list[str] = []
    options: list[str] = []
    for p in cmd.params:
        if p.name not in vals or vals[p.name] is None:
            continue
        v = vals[p.name]
        if isinstance(p, click.Argument):
            if isinstance(v, (list, tuple)):
                positional.extend(str(x) for x in v)
            else:
                positional.append(str(v))
        elif getattr(p, "is_flag", False):
            if v:
                options.append(_opt_string(p.opts))
            elif p.secondary_opts:  # --flag/--no-flag pair
                options.append(_opt_string(p.secondary_opts))
        elif getattr(p, "multiple", False):
            for item in (v if isinstance(v, (list, tuple)) else (v,)):
                options += [_opt_string(p.opts), str(item)]
        else:
            options += [_opt_string(p.opts), str(v)]

    exe = str(python) if python is not None else sys.executable
    return [exe, "-m", "autogis.adapters.cli", *path, *positional, *options]


def _read_qa_rows(qa_csv: str | Path | None) -> tuple[dict, ...]:
    if qa_csv is None or not Path(qa_csv).exists():
        return ()
    with Path(qa_csv).open(newline="", encoding="utf-8") as fh:
        return tuple(csv.DictReader(fh))


def _export_report(qa_csv: str | Path, dest: object) -> tuple[str, str]:
    """Copy the executor-owned ``qa.csv`` out to a user-requested ``--report``
    path. Returns ``(destination, "")`` on success, ``("", error)`` on failure,
    and ``("", "")`` when no export was asked for or there is nothing to copy.

    ``build_argv`` redirects the child's ``--report`` to the job-dir qa.csv for
    gating, discarding the user's value (#205); this restores the user's intent
    by copying that qa.csv to the path they typed. Parents are created to match
    ``QACollector.write_csv`` (so the GUI path behaves like the CLI's own
    ``--report``). A failed copy never changes the QA verdict -- it is surfaced,
    not raised.
    """
    if not dest:
        return "", ""
    src, dest = Path(qa_csv), Path(str(dest))
    if dest == src or not src.exists():
        return "", ""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    except OSError as exc:
        return "", f"could not write report to {dest}: {exc}"
    return str(dest), ""


def _row_lines(rows: Sequence[dict]) -> list[str]:
    ordered = sorted(rows, key=lambda r: _SEV_ORDER.get(r.get("severity", ""), 9))
    lines = [f"[{r.get('severity', '?')}] {r.get('category', '')}: "
             f"{r.get('message', '')}" for r in ordered[:_MAX_REASON_ROWS]]
    if len(ordered) > _MAX_REASON_ROWS:
        lines.append(f"... and {len(ordered) - _MAX_REASON_ROWS} more")
    return lines


def _stderr_tail(stderr: str, n: int = 3) -> str:
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:]) if lines else "(no stderr)"


def decide(exit_code: int, qa_csv: str | Path | None = None, *,
           pause_on_warning: bool = False,
           stdout: str = "", stderr: str = "") -> StepResult:
    """Map (exit code, qa.csv-if-present) to HALT / PAUSE_FOR_REVIEW / CONTINUE.

    The QA-FAIL branch requires *blocking-capable* rows (WARNING+), not just
    a non-empty file: ``_render_qa`` writes the report immediately before
    computing status, and only WARNING+ rows can flip it to FAIL, so an
    exit != 0 with INFO-only rows is some other failure — stderr is the
    truthful reason there.
    """
    rows = _read_qa_rows(qa_csv)
    flagged = [r for r in rows if r.get("severity", "") in _BLOCKING]
    common = dict(exit_code=exit_code, qa_rows=rows,
                  stdout=stdout, stderr=stderr)
    if exit_code != 0:
        if flagged:
            reason = "QA FAIL: " + "; ".join(_row_lines(flagged))
        elif exit_code == 2:
            reason = f"Bad arguments (usage error): {_stderr_tail(stderr)}"
        else:
            reason = (f"Crashed or refused (exit {exit_code}): "
                      f"{_stderr_tail(stderr)}")
        return StepResult(Decision.HALT, reason, **common)
    if flagged and pause_on_warning:
        return StepResult(
            Decision.PAUSE_FOR_REVIEW,
            "QA warnings need review: " + "; ".join(_row_lines(flagged)),
            **common)
    if flagged:
        reason = f"exit 0; {len(flagged)} QA warning(s) noted (pause_on_warning off)"
    elif qa_csv is not None and Path(qa_csv).exists():
        reason = "exit 0, QA clean"
    else:
        reason = "exit 0 (no QA report)"
    return StepResult(Decision.CONTINUE, reason, **common)


def run_step(step: Step, job_dir: str | Path, *,
             local_python: str | Path | None = None,
             timeout: float | None = None) -> StepResult:
    """Run one workflow step and decide its outcome.

    ``command=None`` -> checkpoint: no child process, PAUSE_FOR_REVIEW.
    LOCAL (arcpy) tools require ``local_python`` — the ``python.exe`` of an
    arcgispro-py3 clone, always caller-supplied, never hardcoded here.
    ``timeout`` (seconds) is forwarded to ``subprocess.run``; a
    ``TimeoutExpired`` propagates — hung-child policy belongs to the caller.
    """
    if step.command is None:
        return StepResult(
            Decision.PAUSE_FOR_REVIEW,
            step.message or "Checkpoint: review before continuing.")
    command = tuple(step.command)
    python: str | Path | None = None
    if needs_arcpy_env(command):
        if local_python is None:
            raise ValueError(
                f"{' '.join(command)} is a LOCAL (arcpy) tool: pass "
                "local_python (python.exe of an arcgispro-py3 clone).")
        python = local_python
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    qa_csv = job_dir / "qa.csv"
    # A reused job_dir (retry-in-place) can leave a prior step's qa.csv on
    # disk. If the child dies before writing a fresh report (or never
    # declares --report at all), decide() would otherwise read the stale
    # file and misattribute the verdict to the wrong run.
    qa_csv.unlink(missing_ok=True)
    argv = build_argv(command, step.values, python=python,
                      report_path=qa_csv, fail_on=step.fail_on)
    # PYTHONIOENCODING: without it a Windows child encodes stdout as cp1252
    # and any non-ASCII character in a report (e.g. the '->' arrow in
    # upgrade-schema's) raises UnicodeEncodeError -> spurious HALT.
    proc = subprocess.run(argv, capture_output=True, encoding="utf-8",
                          errors="replace", timeout=timeout,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    result = decide(proc.returncode, qa_csv,
                    pause_on_warning=step.pause_on_warning,
                    stdout=proc.stdout, stderr=proc.stderr)
    # Honor a user-supplied --report: copy the gating qa.csv out to their path
    # before the caller removes the job dir (#205). Export failure is surfaced,
    # not raised -- it must not change the QA verdict just decided.
    report_out, report_error = _export_report(qa_csv, step.values.get("report"))
    if report_out or report_error:
        result = dataclasses.replace(
            result, report_out=report_out, report_error=report_error)
    return result
