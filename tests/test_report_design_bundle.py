import importlib.util
from pathlib import Path

# Anchor to the repo, not the pytest cwd.
BUNDLE = Path(__file__).resolve().parents[1] / "docs" / "design" / "report-templates"


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_bundle", BUNDLE / "build_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bundle_generates_self_contained_previews(tmp_path):
    mod = _load_builder()
    written = mod.build(tmp_path)
    assert written, "generator produced no files"
    for p in written:
        text = Path(p).read_text(encoding="utf-8")
        assert text.lstrip().startswith("<!-- @dsCard")
        assert "http://" not in text and "https://" not in text


def test_committed_previews_match_fresh_regeneration(tmp_path):
    # Guards against editing report.css (or any bundle input) without
    # re-running the generator: the committed docs/design previews must be
    # byte-for-byte (text-compared to dodge CRLF/LF noise) what build()
    # produces right now.
    mod = _load_builder()
    written = mod.build(tmp_path)
    assert written, "generator produced no files"
    for p in written:
        p = Path(p)
        committed = BUNDLE / p.name
        assert committed.exists(), f"{p.name} generated but missing from {BUNDLE}"
        fresh_text = p.read_text(encoding="utf-8")
        committed_text = committed.read_text(encoding="utf-8")
        assert fresh_text == committed_text, (
            f"{committed} is stale relative to the generator output. "
            "Re-run: python docs/design/report-templates/build_bundle.py"
        )
