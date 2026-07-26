"""GUI executor QA-signal logic (ADR-0053): exit code + injected qa.csv
decide HALT / PAUSE_FOR_REVIEW / CONTINUE.

Deterministic via a stub child script (which writes its qa.csv through the
real ``QACollector.write_csv``, so the CSV shape can't drift from
production) — no arcpy, no Pro environment, no real ``autogis`` command.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from autogis.adapters.gui.executor import (
    Decision, Step, build_argv, decide, needs_arcpy_env, run_step,
)

# argv: exit_code [csv_path [comma,separated,severities]]
STUB = """\
import sys
from pathlib import Path
from autogis.core.common.qa import QACollector

qa = QACollector()
if len(sys.argv) > 3:
    for sev in sys.argv[3].split(","):
        qa.add(sev, "stub", f"{sev} from stub")
if len(sys.argv) > 2:
    qa.write_csv(Path(sys.argv[2]))
print("stub stdout")
if int(sys.argv[1]) != 0:
    print("stub failure detail", file=sys.stderr)
sys.exit(int(sys.argv[1]))
"""


def _run_stub(tmp_path, exit_code, severities=None, write_csv=True):
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    qa_csv = tmp_path / "qa.csv"
    argv = [sys.executable, str(stub), str(exit_code)]
    if write_csv:
        argv.append(str(qa_csv))
        if severities:
            argv.append(",".join(severities))
    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode == exit_code, proc.stderr
    return proc, qa_csv


# ---- decide(): the six required scenarios --------------------------------

def test_exit0_clean_continue(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 0)  # header-only qa.csv
    res = decide(proc.returncode, qa_csv, pause_on_warning=True)
    assert res.decision is Decision.CONTINUE
    assert res.qa_rows == ()
    assert "QA clean" in res.reason


def test_exit0_no_report_continue(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 0, write_csv=False)
    res = decide(proc.returncode, qa_csv)
    assert res.decision is Decision.CONTINUE
    assert "no QA report" in res.reason
    # qa_csv=None (command without --report) is the same outcome
    assert decide(0, None).decision is Decision.CONTINUE


def test_exit0_warning_pause_on_warning_pauses(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 0, ["WARNING"])
    res = decide(proc.returncode, qa_csv, pause_on_warning=True)
    assert res.decision is Decision.PAUSE_FOR_REVIEW
    assert "WARNING from stub" in res.reason


def test_exit0_warning_without_pause_flag_continues(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 0, ["WARNING"])
    res = decide(proc.returncode, qa_csv, pause_on_warning=False)
    assert res.decision is Decision.CONTINUE
    assert "warning" in res.reason.lower()  # noted, not silent


def test_exit0_info_rows_never_pause(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 0, ["INFO", "INFO"])
    res = decide(proc.returncode, qa_csv, pause_on_warning=True)
    assert res.decision is Decision.CONTINUE


def test_exit1_with_qa_csv_is_qa_fail_halt(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 1, ["ERROR", "WARNING"])
    res = decide(proc.returncode, qa_csv, stderr=proc.stderr)
    assert res.decision is Decision.HALT
    assert res.reason.startswith("QA FAIL")
    assert "ERROR from stub" in res.reason
    assert len(res.qa_rows) == 2


def test_exit1_without_qa_csv_is_crash_halt(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 1, write_csv=False)
    res = decide(proc.returncode, qa_csv, stderr=proc.stderr)
    assert res.decision is Decision.HALT
    assert "stub failure detail" in res.reason  # stderr surfaced


def test_exit2_is_usage_halt(tmp_path):
    proc, qa_csv = _run_stub(tmp_path, 2, write_csv=False)
    res = decide(proc.returncode, qa_csv, stderr=proc.stderr)
    assert res.decision is Decision.HALT
    assert "usage" in res.reason.lower()


def test_standalone_pause_step_runs_no_command(tmp_path):
    # FullPipeline's stop-before-export as a first-class step type.
    res = run_step(Step(message="Review layouts before export."),
                   job_dir=tmp_path)
    assert res.decision is Decision.PAUSE_FOR_REVIEW
    assert res.exit_code is None
    assert "Review layouts" in res.reason
    assert not (tmp_path / "qa.csv").exists()  # no child process ran


# ---- build_argv(): assembly + QA injection -------------------------------

def test_build_argv_positional_renamed_and_repeatable_options():
    argv = build_argv(
        ("envmon", "validate-config"),
        {"site_config": "site.yaml", "profiles": ["p1.yaml", "p2.yaml"]},
        report_path="job/qa.csv", fail_on="warning")
    assert argv[0] == sys.executable
    assert argv[1:6] == ["-m", "autogis.adapters.cli", "envmon",
                         "validate-config", "site.yaml"]
    # renamed option: emitted as --profile (param.opts), never "--profiles"
    assert argv.count("--profile") == 2 and "--profiles" not in argv
    assert argv[argv.index("--report") + 1] == "job/qa.csv"
    assert argv[argv.index("--fail-on") + 1] == "warning"


def test_build_argv_skips_injection_when_command_has_no_report():
    argv = build_argv(("envmon", "inspect"), {"workbook": "wb.xlsx"},
                      report_path="job/qa.csv", fail_on="warning")
    assert "--report" not in argv and "--fail-on" not in argv
    assert argv[-1] == "wb.xlsx"


def test_build_argv_flags_and_boolean_pairs():
    argv = build_argv(("harvest",),
                      {"config_path": "c.yaml", "incremental": False})
    assert "--config" in argv          # renamed: not "--config-path"
    assert "--no-incremental" in argv  # secondary opt for False
    argv2 = build_argv(("harvest",),
                       {"config_path": "c.yaml", "incremental": True})
    assert "--incremental" in argv2


def test_build_argv_nargs_option_emits_separate_tokens():
    """#351: a nargs>1 option (download-dem's --bbox) must reach argv as
    the option flag followed by N separate value tokens, not one repr'd
    tuple -- Click's own nargs parser expects exactly that shape."""
    argv = build_argv(("envmon", "download-dem"),
                      {"bbox": ("-105", "39", "-104", "40")})
    i = argv.index("--bbox")
    assert argv[i + 1:i + 5] == ["-105", "39", "-104", "40"]


def test_build_argv_nargs_option_on_argument_style_list_also_works():
    """--start/--end (generate-subsurface-profile) is the other nargs>1
    shape (nargs=2 float); same separate-tokens contract."""
    argv = build_argv(("envmon", "generate-subsurface-profile"),
                      {"db_path": "db.sqlite", "out_path": "p.png",
                       "start": ("39.0", "-105.0"), "end": ("39.1", "-105.1")})
    i = argv.index("--start")
    assert argv[i + 1:i + 3] == ["39.0", "-105.0"]
    j = argv.index("--end")
    assert argv[j + 1:j + 3] == ["39.1", "-105.1"]


def test_build_argv_unknown_param_and_unknown_command_raise():
    with pytest.raises(ValueError, match="unknown parameter"):
        build_argv(("envmon", "inspect"), {"nope": 1})
    with pytest.raises(ValueError, match="Unknown CLI command path"):
        build_argv(("envmon", "no-such-tool"), {})


def test_build_argv_python_override():
    argv = build_argv(("envmon", "inspect"), {"workbook": "wb.xlsx"},
                      python=r"C:\pro-clone\python.exe")
    assert argv[0] == r"C:\pro-clone\python.exe"


# ---- environment selection ------------------------------------------------

def test_needs_arcpy_env_lookup():
    assert needs_arcpy_env(("envmon", "import-gdb")) is True
    assert needs_arcpy_env(("envmon", "inspect")) is False
    # sub-subcommand resolves through its group's registry entry
    assert needs_arcpy_env(("envmon", "manage-callout-overrides", "lock")) is True
    # unknown leaf defaults headless; the CLI guard is the backstop
    assert needs_arcpy_env(("envmon", "not-registered")) is False


def test_run_step_local_tool_requires_local_python(tmp_path):
    with pytest.raises(ValueError, match="local_python"):
        run_step(Step(command=("envmon", "import-gdb")), job_dir=tmp_path)


# ---- run_step composition --------------------------------------------------

def test_run_step_end_to_end_with_stub(tmp_path, monkeypatch):
    import autogis.adapters.gui.executor as ex
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")

    def stub_argv(path, values, *, python=None, report_path=None, fail_on=None):
        return [sys.executable, str(stub), "0", str(report_path), "WARNING"]

    monkeypatch.setattr(ex, "build_argv", stub_argv)
    res = ex.run_step(
        Step(command=("envmon", "reconcile-locations"), pause_on_warning=True),
        job_dir=tmp_path / "job")
    assert res.decision is Decision.PAUSE_FOR_REVIEW
    assert res.qa_rows and res.qa_rows[0]["severity"] == "WARNING"
    assert "stub stdout" in res.stdout


def test_export_report_copies_qa_csv_to_user_path(tmp_path):
    from autogis.adapters.gui.executor import _export_report
    src = tmp_path / "job" / "qa.csv"
    src.parent.mkdir()
    src.write_text("run_id,severity\nr,INFO\n", encoding="utf-8")
    dest = tmp_path / "out" / "REPORT_CLEAN"  # parent dir does not exist yet
    out, err = _export_report(src, str(dest))
    assert err == ""
    assert out == str(dest)
    # copied verbatim, and the parent dir was created (matches QACollector.write_csv)
    assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_export_report_returns_error_when_dest_unwritable(tmp_path):
    from autogis.adapters.gui.executor import _export_report
    src = tmp_path / "qa.csv"
    src.write_text("run_id,severity\n", encoding="utf-8")
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")   # a FILE where a dir is needed
    dest = blocker / "sub" / "qa.csv"            # mkdir(parents=True) must fail
    out, err = _export_report(src, str(dest))
    assert out == ""                             # distinguishable from success
    assert "could not write report" in err


def test_export_report_noop_when_no_dest_or_no_source(tmp_path):
    from autogis.adapters.gui.executor import _export_report
    src = tmp_path / "qa.csv"
    src.write_text("h\n", encoding="utf-8")
    assert _export_report(src, None) == ("", "")          # no export requested
    assert _export_report(src, "") == ("", "")            # blank field
    missing = tmp_path / "missing.csv"
    assert _export_report(missing, str(tmp_path / "d.csv")) == ("", "")  # nothing to copy


def test_run_step_exports_report_to_user_path(tmp_path, monkeypatch):
    """End-to-end: a user-supplied --report value survives as a copy at that
    path even though the executor injects its own qa.csv for gating."""
    import autogis.adapters.gui.executor as ex
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    dest = tmp_path / "exports" / "REPORT_CLEAN"

    def stub_argv(path, values, *, python=None, report_path=None, fail_on=None):
        return [sys.executable, str(stub), "0", str(report_path), "INFO"]

    monkeypatch.setattr(ex, "build_argv", stub_argv)
    res = ex.run_step(
        Step(command=("envmon", "validate-rtk-survey"),
             values={"report": str(dest)}),
        job_dir=tmp_path / "job")
    assert res.report_out == str(dest)
    assert res.report_error == ""
    assert dest.exists()


def test_run_step_exports_report_even_on_halt(tmp_path, monkeypatch):
    """The report is the user's regardless of QA verdict: a HALT (blocking rows,
    exit 1) must still copy the report out (ADR-0073) -- pins the documented
    'export even on HALT' behavior against a future CONTINUE-only guard."""
    import autogis.adapters.gui.executor as ex
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    dest = tmp_path / "exports" / "REPORT_FAIL"

    def stub_argv(path, values, *, python=None, report_path=None, fail_on=None):
        return [sys.executable, str(stub), "1", str(report_path), "ERROR"]

    monkeypatch.setattr(ex, "build_argv", stub_argv)
    res = ex.run_step(
        Step(command=("envmon", "validate-rtk-survey"),
             values={"report": str(dest)}),
        job_dir=tmp_path / "job")
    assert res.decision is Decision.HALT     # blocking row + exit 1
    assert res.report_out == str(dest)       # exported anyway
    assert dest.exists()


def test_form_report_field_reaches_exported_file(tmp_path, monkeypatch):
    """End-to-end guard for the whole form -> build_step -> run_step -> export
    chain (#205): a typed `report` field on a real command's form must survive
    build_step and land as a file. Guards against a future report-filter in
    forms.py/introspect.py leaving every stubbed test green while silently
    killing the feature (the coverage seam the review flagged)."""
    import autogis.adapters.gui.executor as ex
    from autogis.adapters.gui.forms import build_step
    from autogis.adapters.gui.introspect import introspect_cli

    form = {f.label: f for f in introspect_cli()}["envmon validate-rtk-survey"]
    dest = tmp_path / "out" / "REPORT"
    step = build_step(form, {"csv_path": "x.csv", "report": str(dest)})
    assert step.values.get("report") == str(dest)   # survived introspect+build_step

    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")

    def stub_argv(path, values, *, python=None, report_path=None, fail_on=None):
        return [sys.executable, str(stub), "0", str(report_path), "INFO"]

    monkeypatch.setattr(ex, "build_argv", stub_argv)
    res = ex.run_step(step, job_dir=tmp_path / "job")
    assert res.report_out == str(dest)
    assert dest.exists()


def test_run_step_ignores_stale_qa_csv_from_reused_job_dir(tmp_path, monkeypatch):
    """A prior step's qa.csv left in a reused job_dir must not leak into
    this step's verdict (a job_dir isn't guaranteed fresh on retry)."""
    import autogis.adapters.gui.executor as ex
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    stale = job_dir / "qa.csv"
    stale.write_text(
        "run_id,severity,category,message\nold,ERROR,stale,should not surface\n",
        encoding="utf-8")

    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")

    def stub_argv(path, values, *, python=None, report_path=None, fail_on=None):
        # Exits clean and writes NO report -- e.g. a command without
        # --report, or one that crashed before ever calling _render_qa.
        return [sys.executable, str(stub), "0"]

    monkeypatch.setattr(ex, "build_argv", stub_argv)
    res = ex.run_step(Step(command=("envmon", "inspect")), job_dir=job_dir)
    assert res.decision is Decision.CONTINUE
    assert res.qa_rows == ()
    assert "stale" not in res.reason


def test_run_step_child_env_forces_utf8(tmp_path, monkeypatch):
    """Without PYTHONIOENCODING a Windows child encodes stdout as cp1252, so
    a non-ASCII report character raised UnicodeEncodeError -> spurious HALT
    (2026-07-10: upgrade-schema's '→' arrow)."""
    import autogis.adapters.gui.executor as ex
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    res = ex.run_step(Step(command=("envmon", "reconcile-locations")),
                      job_dir=tmp_path / "job")
    assert res.decision is Decision.CONTINUE
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8"
    # the parent environment is inherited, not replaced
    import os
    assert len(seen["env"]) > 1 and all(k in seen["env"] for k in os.environ)
