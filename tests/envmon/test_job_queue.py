"""Unit + CLI tests for job_queue (Tool 10.4)."""
import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.job_queue import generate_job_queue


def test_basic_queue():
    qa = QACollector()
    entries = generate_job_queue(["H281"], ["inspect", "import-gdb"], None, qa=qa)
    assert entries[0].tool == "inspect"
    assert entries[1].tool == "import-gdb"
    assert entries[0].runtime == "cloud"
    assert entries[1].runtime == "local"


def test_unknown_tool_warns():
    qa = QACollector()
    entries = generate_job_queue(["H281"], ["no-such-tool"], None, qa=qa)
    assert len(entries) == 0
    assert any(r.category == "unknown_tool" for r in qa.records)


def test_multi_site():
    qa = QACollector()
    entries = generate_job_queue(["H281", "H282"], ["inspect"], None, qa=qa)
    assert len(entries) == 2
    site_ids = [e.site_id for e in entries]
    assert "H281" in site_ids and "H282" in site_ids


def test_extra_args_merged():
    qa = QACollector()
    extra = {"inspect": {"format": "json"}}
    entries = generate_job_queue(["H281"], ["inspect"], extra, qa=qa)
    assert entries[0].args == {"format": "json"}


def test_per_site_args_override():
    qa = QACollector()
    extra = {"inspect": {"format": "json"}, "inspect:H282": {"format": "csv"}}
    entries = generate_job_queue(["H281", "H282"], ["inspect"], extra, qa=qa)
    by_site = {e.site_id: e.args for e in entries}
    assert by_site["H281"] == {"format": "json"}
    assert by_site["H282"] == {"format": "csv"}


def test_order_field_sequential():
    qa = QACollector()
    entries = generate_job_queue(["S1", "S2"], ["inspect", "import-gdb"], None, qa=qa)
    assert [e.order for e in entries] == list(range(len(entries)))


# --- CLI --------------------------------------------------------------------

def test_generate_job_queue_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "generate-job-queue" in result.output


def test_cli_generate_job_queue_end_to_end(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({
        "sites": ["H281", "H282"],
        "tools": ["inspect", "import-gdb"],
        "args": {"inspect": {"format": "json"}},
    }), encoding="utf-8")
    out = tmp_path / "queue.json"
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-job-queue",
        "--manifest", str(manifest), "--output", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    queue = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(queue, list)
    assert len(queue) == 4  # 2 tools x 2 sites
    # CLOUD inspect jobs ordered before LOCAL import-gdb jobs
    assert queue[0]["tool"] == "inspect"
    assert queue[0]["args"] == {"format": "json"}
    assert all(set(j) == {"tool", "site_id", "runtime", "args", "order"} for j in queue)


def test_cli_generate_job_queue_report_and_fail_on(tmp_path):
    """--report must be written and --fail-on must gate exit code (regression:
    the command built a QACollector but never called _render_qa)."""
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({
        "sites": ["H281"],
        "tools": ["no-such-tool"],
    }), encoding="utf-8")
    out = tmp_path / "queue.json"
    report = tmp_path / "report.json"
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-job-queue",
        "--manifest", str(manifest), "--output", str(out),
        "--report", str(report), "--fail-on", "warning",
    ])
    assert result.exit_code != 0, result.output
    assert report.exists()
    assert "unknown_tool" in report.read_text(encoding="utf-8")


def test_cli_manifest_non_dict_errors(tmp_path):
    """A non-mapping --manifest YAML must fail cleanly, not traceback."""
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("- just\n- a\n- list\n", encoding="utf-8")
    out = tmp_path / "queue.json"
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-job-queue",
        "--manifest", str(manifest), "--output", str(out),
    ])
    assert result.exit_code != 0
    assert "must be a YAML mapping" in result.output
