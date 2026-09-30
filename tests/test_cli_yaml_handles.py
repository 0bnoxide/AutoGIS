"""CLI YAML inputs are read-and-closed, not left to the garbage collector.

A bare ``open()`` inside ``yaml.safe_load(...)`` leaks the handle; under the
long-lived ``.pyt`` interpreter that holds the file open until GC (a lock on
Windows). ``build-survey-form`` is the command the suite flagged.
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
