"""Direct YAML CLI inputs reject malformed files without a Python traceback."""

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


@pytest.mark.parametrize("kind", ["malformed", "duplicate", "encoding", "directory"])
def test_generate_job_queue_reports_clean_input_error(tmp_path, kind):
    source = tmp_path / "manifest.yaml"
    if kind == "directory":
        source.mkdir()
    elif kind == "malformed":
        source.write_text("sites: [\n", encoding="utf-8")
    elif kind == "duplicate":
        source.write_text("sites: []\nsites: [S1]\n", encoding="utf-8")
    else:
        source.write_bytes(b"sites: \xff\n")

    result = CliRunner().invoke(autogis, [
        "envmon", "generate-job-queue", "--manifest", str(source),
        "--output", str(tmp_path / "queue.json"),
    ])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert f"cannot read {source}" in result.output
    assert "Traceback" not in result.output
