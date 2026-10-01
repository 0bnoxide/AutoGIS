"""CLI YAML inputs are read-and-closed, not left to the garbage collector.

A bare ``open()`` inside ``yaml.safe_load(...)`` leaks the handle until GC:
a ResourceWarning in the suite, and a lingering lock on Windows for as long
as the process lives. ``build-survey-form`` is the command the suite flagged.
"""
import gc
import warnings

from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_build_survey_form_closes_its_yaml_inputs(tmp_path):
    cfg = tmp_path / "site.yaml"
    cfg.write_text("site_id: S1\n", encoding="utf-8")
    empty = tmp_path / "empty.yaml"
    empty.write_text("{}\n", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        CliRunner().invoke(autogis, [
            "envmon", "build-survey-form",
            "--site", str(cfg), "--analytes", str(empty),
            "--event", str(empty), "--out", str(tmp_path / "form.xlsx"),
        ])
        gc.collect()

    leaked = [w for w in caught if issubclass(w.category, ResourceWarning)]
    assert not leaked, [str(w.message) for w in leaked]


def _bad_inputs(tmp_path):
    """Malformed YAML and a directory: both pass ``click.Path(exists=True)``."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("site_id: [unclosed\n", encoding="utf-8")
    a_dir = tmp_path / "a dir é"
    a_dir.mkdir()
    return bad, a_dir


def test_build_survey_form_bad_yaml_is_a_clean_error(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("{}\n", encoding="utf-8")
    for bad in _bad_inputs(tmp_path):
        result = CliRunner().invoke(autogis, [
            "envmon", "build-survey-form",
            "--site", str(bad), "--analytes", str(empty),
            "--event", str(empty), "--out", str(tmp_path / "form.xlsx"),
        ])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert "cannot read" in result.output and str(bad) in result.output


def test_validate_survey_form_bad_yaml_is_a_clean_error(tmp_path):
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    form = tmp_path / "form.xlsx"
    build_xlsform({"site_id": "S1"}, {}, {}).save(form)
    for bad in _bad_inputs(tmp_path):
        result = CliRunner().invoke(autogis, [
            "envmon", "validate-survey-form", str(form),
            "--site-config", str(bad),
        ])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert "cannot read" in result.output and str(bad) in result.output
