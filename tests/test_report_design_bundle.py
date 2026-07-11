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
