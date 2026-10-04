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


def _build(tmp_path, site, analytes, event, out=None):
    return CliRunner().invoke(autogis, [
        "envmon", "build-survey-form",
        "--site", str(site), "--analytes", str(analytes),
        "--event", str(event), "--out", str(out or tmp_path / "form.xlsx"),
    ])


def test_build_survey_form_rejects_empty_and_non_mapping_yaml(tmp_path):
    """#549: an empty or list-shaped required input must fail loudly. Treating
    an empty file as {} would write a form with no site, wells or analytes
    and exit 0."""
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    a_list = tmp_path / "list.yaml"
    a_list.write_text("- 1\n- 2\n", encoding="utf-8")
    for args, bad in [((empty, obj, obj), empty), ((a_list, obj, obj), a_list),
                      ((obj, a_list, obj), a_list), ((obj, obj, empty), empty)]:
        result = _build(tmp_path, *args)
        assert result.exit_code == 1, result.output
        assert isinstance(result.exception, SystemExit), result.exception
        assert "expected a YAML mapping" in result.output
        assert str(bad) in result.output
        assert not (tmp_path / "form.xlsx").exists()


def test_build_survey_form_out_directory_is_a_usage_error(tmp_path):
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out_dir = tmp_path / "out dir"
    out_dir.mkdir()
    result = _build(tmp_path, obj, obj, obj, out=out_dir)
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert "is a directory" in result.output


def test_validate_survey_form_empty_config_still_means_not_supplied(tmp_path):
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    form = tmp_path / "form.xlsx"
    build_xlsform({"site_id": "S1"}, {}, {}).save(form)
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    a_list = tmp_path / "list.yaml"
    a_list.write_text("- 1\n", encoding="utf-8")

    ok = CliRunner().invoke(autogis, [
        "envmon", "validate-survey-form", str(form), "--event-config", str(empty)])
    assert not isinstance(ok.exception, AttributeError), ok.exception

    for opt in ("--site-config", "--event-config", "--analyte-dict"):
        result = CliRunner().invoke(autogis, [
            "envmon", "validate-survey-form", str(form), opt, str(a_list)])
        assert result.exit_code == 1, result.output
        assert isinstance(result.exception, SystemExit), result.exception
        assert "expected a YAML mapping" in result.output


def test_build_survey_form_creates_missing_out_directory(tmp_path):
    """#550 (owner decision: option B): an --out in a missing directory
    creates that directory instead of escaping as a raw FileNotFoundError."""
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "new dir é" / "nested" / "form.xlsx"
    result = _build(tmp_path, obj, obj, obj, out=out)
    assert result.exit_code == 0, result.output
    assert out.is_file()


def test_build_survey_form_unwritable_out_is_a_clean_error(tmp_path):
    """Other write failures (here: a parent that is a regular file) still
    surface as a clean error, not a traceback."""
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    a_file = tmp_path / "a_file"
    a_file.write_text("", encoding="utf-8")
    out = a_file / "form.xlsx"
    result = _build(tmp_path, obj, obj, obj, out=out)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert "cannot write" in result.output and str(out) in result.output


def test_build_survey_form_failed_save_keeps_existing_form(tmp_path, monkeypatch):
    """#551: a save that dies partway (e.g. disk full) must not truncate an
    existing --out form or leave a partial file behind."""
    from openpyxl import Workbook

    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "form.xlsx"
    out.write_bytes(b"previous form")

    def partial_save(self, filename):
        with open(filename, "wb") as fh:
            fh.write(b"PK\x03\x04trunc")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Workbook, "save", partial_save)
    result = _build(tmp_path, obj, obj, obj, out=out)
    assert result.exit_code == 1, result.output
    assert "cannot write" in result.output
    assert out.read_bytes() == b"previous form"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["form.xlsx", "obj.yaml"]


def test_build_survey_form_failed_save_reports_real_error(tmp_path, monkeypatch):
    """#551, real openpyxl seam: save_workbook leaves its ZipFile open when
    writing fails, so on Windows unlinking the temp raises PermissionError.
    That cleanup failure must not mask the real save error."""
    import pathlib
    from openpyxl.writer.excel import ExcelWriter

    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "form.xlsx"
    out.write_bytes(b"previous form")

    def partial_write(self):
        self._archive.writestr("partial", b"x" * 64)
        raise OSError(28, "No space left on device")

    real_unlink = pathlib.Path.unlink

    def windows_locked_unlink(self, missing_ok=False):
        if self.name.endswith(".tmp"):  # handle still open, as on Windows
            raise PermissionError(32, "file in use by another process")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(ExcelWriter, "write_data", partial_write)
    monkeypatch.setattr(pathlib.Path, "unlink", windows_locked_unlink)
    result = _build(tmp_path, obj, obj, obj, out=out)
    assert result.exit_code == 1, result.output
    assert "No space left on device" in result.output
    assert out.read_bytes() == b"previous form"
