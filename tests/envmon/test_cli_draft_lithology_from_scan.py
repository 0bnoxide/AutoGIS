"""CLI wiring tests for draft-lithology-from-scan — no real OCR models are
invoked; draft_lithology()/write_draft_csv() are monkeypatched so these tests
run with zero OCR dependencies installed."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector, SEV_INFO
from autogis.core.common.schema.boring import LithologyInterval
from autogis.core.envmon.draft_lithology_from_scan import DraftResult


def test_draft_lithology_from_scan_without_ocr_extra_is_clean_error(tmp_path):
    scan = tmp_path / "log.pdf"
    scan.write_bytes(b"%PDF-1.4 fake")
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "draft-lithology-from-scan", str(scan),
        "--out-dir", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0
    assert "pip install autogis[ocr]" in result.output


def test_draft_lithology_from_scan_writes_csv_and_renders_qa(tmp_path, monkeypatch):
    scan = tmp_path / "log.pdf"
    scan.write_bytes(b"%PDF-1.4 fake")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(
        "autogis.adapters.cli._require_ocr_extra", lambda: None)

    def fake_draft_lithology(scan_path, *, handwritten=False):
        qa = QACollector()
        qa.add(SEV_INFO, "draft_lithology_from_scan", "DRAFT output.")
        rows = [LithologyInterval(boring_id="MW-1", top_depth=0.0,
                                   bottom_depth=2.0, uscs="ML",
                                   description="Sandy silt")]
        return DraftResult(rows=rows, qa=qa)

    monkeypatch.setattr(
        "autogis.core.envmon.draft_lithology_from_scan.draft_lithology",
        fake_draft_lithology)

    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "draft-lithology-from-scan", str(scan),
        "--out-dir", str(out_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "DRAFT" in result.output
    assert (out_dir / "lithology.csv").exists()
    content = (out_dir / "lithology.csv").read_text(encoding="utf-8")
    assert "MW-1" in content
