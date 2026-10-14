"""Synthetic R9 imports reject ambiguous/lossy timestamps before any append."""
import dataclasses
import datetime as dt
import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
import xlrd

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon import edd_importer as importer
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.equis_reader import read_equis_xls
from autogis.core.envmon.gdb_schema import compute_unique_key


PROFILE = Path(autogis.__file__).parent / "config/lab_profiles/epar4.yaml"


def _sheets(date="03/17/2025", time="09:14", *, qc=True):
    sample = dict(sys_sample_code="S1", sys_loc_code="MW1",
                  sample_matrix_code="GW", sample_date="03/11/2025",
                  sample_source="Lab" if qc else "Field",
                  sample_type_code="LCS" if qc else "N")
    test = dict(sys_sample_code="S1", lab_anl_method_name="E200.8",
                analysis_date=date, analysis_time=time,
                total_or_dissolved="T", column_number="NA",
                test_type="INITIAL", dilution_factor="1", basis="NA")
    result = {k: v for k, v in test.items()
              if k not in {"dilution_factor", "basis"}}
    result.update(chemical_name="Lead", result_value="1", result_unit="mg/L",
                  result_type_code="TRG", reportable_result="Yes",
                  test_batch_type="Analysis", test_batch_id="AB1")
    return {"EPAR4_FSample_v1": [sample], "EPAR4_TST_v1": [test],
            "EPAR4_RES_v1": [result]}


def _workbook(tmp_path, sheets, *, name="export", headers=None, iso=False):
    wb = openpyxl.Workbook()
    wb.iso_dates = iso
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        columns = list(dict.fromkeys(k for row in rows for k in row))
        ws.append([(headers or {}).get(k, k) for k in columns])
        for row in rows:
            ws.append([row.get(k) for k in columns])
    path = tmp_path / f"{name}.xlsx"
    wb.save(path)
    wb.close()
    return path


def _writer(monkeypatch):
    """Only replace the unavailable GDB effects; readers/normalizers/keys run."""
    stored = {}
    batches = []
    monkeypatch.setattr(importer, "create_or_update_gdb_schema", lambda *a: None)
    monkeypatch.setattr(importer, "create_edd_import_batch", lambda *a: "B1")

    def append(gdb, table, records, qa, batch):
        keys = stored.setdefault(table, set())
        before = len(keys)
        keys.update(compute_unique_key(dataclasses.asdict(r), table)
                    for r in records)
        return len(keys) - before, len(records) - (len(keys) - before)

    monkeypatch.setattr(importer, "append_records_idempotent", append)
    monkeypatch.setattr(importer, "finalize_batch",
                        lambda gdb, batch, qa, counts, status:
                        batches.append((status, counts)))
    monkeypatch.setattr(importer, "write_qa_to_gdb", lambda *a: None)
    return stored, batches


def _import(path, profile, qa):
    return importer.run_edd_import(path, profile, path.parent / "synthetic.gdb",
                                   "SITE", {}, {}, qa=qa)


def _keys(path, profile):
    qa = QACollector()
    rows = importer.read_edd_file(path, profile, qa)
    qc = [r for r in rows if r.get("__equis_stream") == "qc"]
    data = [r for r in rows if r.get("__equis_stream") != "qc"]
    _, results = importer.normalize_edd_rows(data, profile, "SITE", "B1", {}, {}, qa)
    results_qc = importer.normalize_qc_rows(qc, profile, "SITE", "B1", {}, qa)
    table, records = (("Env_QCResults", results_qc) if qc
                      else ("Env_AnalyticalResults", results))
    return [compute_unique_key(dataclasses.asdict(r), table) for r in records], qa


@pytest.mark.parametrize("qc", [True, False])
@pytest.mark.parametrize("date,time", [
    ("3/17/2025", "09:14"), ("03/17/2025", "9:14"),
    ("2025-03-17", "09:14"), ("02/30/2025", "09:14"),
    ("03/17/2025 09:14", ""), ("03/17/2025T09:14:00Z", ""),
    ("03/17/2025", "09:14:00"), ("03/17/2025", "09:14:17"),
    ("03/17/2025", "09:14:00.125"), ("03/17/2025", "09:14+00:00"),
    ("03/17/2025", "24:00"),
    (dt.datetime(2025, 3, 17, 0, 0, 17), "09:14"),
    (dt.date(2025, 3, 17), dt.time(9, 14, 17)),
    (dt.date(2025, 3, 17), dt.time(9, 14, 0, 125000)),
])
@pytest.mark.parametrize("side", ["EPAR4_TST_v1", "EPAR4_RES_v1"])
def test_invalid_timestamp_aborts_valid_siblings_before_any_append(
        tmp_path, monkeypatch, qc, date, time, side):
    sheets = _sheets(qc=qc)
    bad = dict(sheets[side][0], analysis_date=date, analysis_time=time)
    # The invalid TST is unmatched, and an invalid RES may lose its sample.
    # Validation must run before either join filters it away.
    bad["sys_sample_code"] = "MISSING"
    sheets[side].append(bad)
    path = _workbook(tmp_path, sheets)
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(path, LabEDDProfile.load(PROFILE), qa)
    assert not stored
    assert batches[0][0] == "ERROR"
    assert all(n == 0 for n in batches[0][1].values())
    errors = [r for r in qa.records if r.category == "equis_invalid_run_timestamp"]
    assert errors and errors[0].source_sheet == side
    assert errors[0].source_row == 3


@pytest.mark.parametrize("qc", [True, False])
@pytest.mark.parametrize("time,native_time", [("09:14", dt.time(9, 14)),
                                              ("00:00", dt.time())])
def test_canonical_native_and_text_exports_keep_frozen_keys_and_reimport(
        tmp_path, monkeypatch, qc, time, native_time):
    profile = LabEDDProfile.load(PROFILE)
    text = _workbook(tmp_path, _sheets(time=time, qc=qc), name="text")
    native = _workbook(tmp_path, _sheets(dt.datetime(2025, 3, 17), native_time,
                                        qc=qc), name="native")
    keys_text, qa_text = _keys(text, profile)
    keys_native, qa_native = _keys(native, profile)
    token = f"1|INITIAL|{'' if qc else 'E200.8|'}03/17/2025@{time}"
    expected = (("SITE", "GW", "AB1", "S1", "LCS", "LEAD", "T",
                 "E200.8", token) if qc else
                ("SITE", "GW", "MW1", "S1", "2025-03-11", "LEAD", "",
                 "EQUIS_XLS", "", "T", "", token))
    assert keys_text == keys_native == [expected]
    assert not qa_text.has_blocking() and not qa_native.has_blocking()
    stored, batches = _writer(monkeypatch)
    _import(text, profile, QACollector())
    _import(native, profile, QACollector())
    table = "Env_QCResults" if qc else "Env_AnalyticalResults"
    assert stored[table] == {expected}
    assert batches[1][1]["qc_results" if qc else "analytical_results"] == 0
    assert batches[1][1]["qc_skipped" if qc else "analytical_skipped"] == 1


@pytest.mark.parametrize("date,time,token", [("", "", "1|INITIAL"),
    ("03/17/2025", "", "1|INITIAL|03/17/2025@"),
    ("", "09:14", "1|INITIAL|@09:14")])
def test_blank_discriminators_preserve_existing_degradation(tmp_path, date, time, token):
    path = _workbook(tmp_path, _sheets(date, time))
    keys, qa = _keys(path, LabEDDProfile.load(PROFILE))
    assert keys[0][-1] == token
    assert not qa.has_blocking()


@pytest.mark.parametrize("serial", [0.0, 0.5, 30.0,
    45733 + (9 * 3600 + 14 * 60 + 17) / 86400, 45733 + 0.0000000011574074])
def test_xls_loader_preserves_loss_evidence_before_legacy_conversion(
        tmp_path, monkeypatch, serial):
    sheets = _sheets()
    field = "analysis_time" if serial < 1 else "analysis_date"
    for name in ("EPAR4_TST_v1", "EPAR4_RES_v1"):
        sheets[name][0][field] = SimpleNamespace(ctype=xlrd.XL_CELL_DATE, value=serial)

    class Sheet:
        def __init__(self, rows):
            cols = list(rows[0])
            self.cells = [[SimpleNamespace(ctype=xlrd.XL_CELL_TEXT, value=c)
                           for c in cols]]
            self.cells.extend([[v if hasattr(v, "ctype") else
                                SimpleNamespace(ctype=xlrd.XL_CELL_TEXT, value=v)
                                for v in row.values()] for row in rows])
            self.nrows = len(self.cells)

        def row(self, index):
            return self.cells[index]

    book = SimpleNamespace(datemode=0, sheet_by_name=lambda n: Sheet(sheets[n]))
    monkeypatch.setattr(xlrd, "open_workbook", lambda path: book)
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(tmp_path / "codec.xls", LabEDDProfile.load(PROFILE), qa)
    assert not stored
    assert batches[0][0] == "ERROR"
    assert [r for r in qa.records if r.category == "equis_invalid_run_timestamp"]


def test_header_and_source_aliases_cannot_hide_native_precision_loss(tmp_path, monkeypatch):
    sheets = _sheets(time=dt.time(9, 14, 17))
    for name in ("EPAR4_TST_v1", "EPAR4_RES_v1"):
        row = sheets[name][0]
        row["run_time"] = row.pop("analysis_time")
    path = _workbook(tmp_path, sheets, headers={"run_time": "#RUN_TIME"})
    profile = LabEDDProfile.load(PROFILE)
    profile.source_aliases["run_time"] = "analysis_time"
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(path, profile, qa)
    assert not stored and batches[0][0] == "ERROR"
    assert [r for r in qa.records if r.category == "equis_invalid_run_timestamp"]


@pytest.mark.parametrize("column,native", [("analysis_date", dt.datetime(2025, 3, 17)),
                                           ("analysis_time", dt.time(9, 14))])
def test_raw_xlsx_submillisecond_precision_cannot_round_into_valid_run(
        tmp_path, monkeypatch, column, native):
    import xml.etree.ElementTree as ET
    sheets = _sheets()
    for name in ("EPAR4_TST_v1", "EPAR4_RES_v1"):
        sheets[name][0][column] = native
    path = _workbook(tmp_path, sheets)
    with zipfile.ZipFile(path) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    # Inject0.1ms into actual numeric timestamp source; decoder drops it.
    for member in ("xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml"):
        root = ET.fromstring(members[member])
        row = root.find(f"{ns}sheetData/{ns}row[@r='2']")
        index = list(sheets["EPAR4_TST_v1" if member.endswith("sheet2.xml")
                            else "EPAR4_RES_v1"][0]).index(column)
        value = list(row)[index].find(f"{ns}v")
        value.text = str(Decimal(value.text) + Decimal("0.0000000011574074"))
        members[member] = ET.tostring(root)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(path, LabEDDProfile.load(PROFILE), qa)
    assert not stored and batches[0][0] == "ERROR"
    assert [r for r in qa.records if r.category == "equis_invalid_run_timestamp"]


@pytest.mark.parametrize("raw", ["2025-03-17T00:00:00.0004",
    "2025-03-17T00:00:00.0000000001", "2025-03-17T00:00:00Z",
    "2025-03-17T00:00:00+00:00", "2025-03-17T00:00:00trailing"])
def test_iso_source_suffixes_cannot_escape_decoder_precision_checks(
        tmp_path, monkeypatch, raw):
    import xml.etree.ElementTree as ET
    sheets = _sheets(dt.datetime(2025, 3, 17), dt.time(9, 14))
    path = _workbook(tmp_path, sheets, iso=True)
    with zipfile.ZipFile(path) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    for member in ("xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml"):
        root = ET.fromstring(members[member])
        row = root.find(f"{ns}sheetData/{ns}row[@r='2']")
        # Date is third column in the independent synthetic workbook.
        cell = list(row)[2]
        assert cell.attrib["t"] == "d"
        cell.find(f"{ns}v").text = raw
        members[member] = ET.tostring(root)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(path, LabEDDProfile.load(PROFILE), qa)
    assert not stored and batches[0][0] == "ERROR"
    assert [r for r in qa.records if r.category == "equis_invalid_run_timestamp"]


def test_canonical_iso_native_cells_keep_existing_text_keys(tmp_path):
    profile = LabEDDProfile.load(PROFILE)
    path = _workbook(tmp_path, _sheets(dt.date(2025, 3, 17), dt.time(9, 14)), iso=True)
    keys, qa = _keys(path, profile)
    assert keys == [("SITE", "GW", "AB1", "S1", "LCS", "LEAD", "T",
                     "E200.8", "1|INITIAL|03/17/2025@09:14")]
    assert not qa.has_blocking()


def test_matched_bad_test_precision_cannot_be_overwritten_by_valid_result(
        tmp_path, monkeypatch):
    sheets = _sheets()
    sheets["EPAR4_TST_v1"][0]["analysis_time"] = dt.time(9, 14, 17)
    path = _workbook(tmp_path, sheets)
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(path, LabEDDProfile.load(PROFILE), qa)
    assert not stored and batches[0][0] == "ERROR"
    errors = [r for r in qa.records if r.category == "equis_invalid_run_timestamp"]
    assert errors and errors[0].source_sheet == "EPAR4_TST_v1"


def test_multi_step_source_aliases_cannot_hide_precision(tmp_path, monkeypatch):
    sheets = _sheets(time=dt.time(9, 14, 17))
    for name in ("EPAR4_TST_v1", "EPAR4_RES_v1"):
        row = sheets[name][0]
        row["run_time"] = row.pop("analysis_time")
    path = _workbook(tmp_path, sheets)
    profile = LabEDDProfile.load(PROFILE)
    profile.source_aliases.update(run_time="intermediate_time", intermediate_time="analysis_time")
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(path, profile, qa)
    assert not stored and batches[0][0] == "ERROR"


@pytest.mark.parametrize("qc", [True, False])
def test_canonical_runs_keep_keys_when_alone_reordered_or_subset(tmp_path, qc):
    profile = LabEDDProfile.load(PROFILE)
    first, second = _sheets(time="09:14", qc=qc), _sheets(time="16:47", qc=qc)
    together = {n: first[n] + second[n] for n in first}
    alone = _keys(_workbook(tmp_path, first, name="alone"), profile)[0][0]
    combined = _keys(_workbook(tmp_path, together, name="both"), profile)[0]
    reversed_rows = {n: list(reversed(rows)) for n, rows in together.items()}
    reverse = _keys(_workbook(tmp_path, reversed_rows, name="reverse"), profile)[0]
    assert alone == combined[0] == reverse[1]
    assert set(combined) == set(reverse) and len(set(combined)) == 2


@pytest.mark.parametrize("qc", [True, False])
def test_indistinguishable_results_and_overlength_remain_batch_blocking(tmp_path, monkeypatch, qc):
    profile = LabEDDProfile.load(PROFILE)
    sheets = _sheets(qc=qc)
    sheets["EPAR4_RES_v1"].append(dict(sheets["EPAR4_RES_v1"][0]))
    stored, batches = _writer(monkeypatch)
    qa = QACollector()
    _import(_workbook(tmp_path, sheets, name="duplicate"), profile, qa)
    assert not stored and batches[0][0] == "ERROR"
    assert [r for r in qa.records if r.category == "edd_key_collision"]
    sheets = _sheets(qc=qc)
    sheets["EPAR4_TST_v1"][0]["dilution_factor"] = "1" * 64
    qa = QACollector()
    _import(_workbook(tmp_path, sheets, name="long"), profile, qa)
    assert not stored and batches[1][0] == "ERROR"
    assert [r for r in qa.records if r.category == "edd_key_too_long"]


@pytest.mark.parametrize("datemode", [0, 1])
def test_xls_native_date_with_canonical_text_time_keeps_frozen_key(
        tmp_path, monkeypatch, datemode):
    sheets = _sheets()
    serial = xlrd.xldate.xldate_from_date_tuple((2025, 3, 17), datemode)
    for name in ("EPAR4_TST_v1", "EPAR4_RES_v1"):
        sheets[name][0]["analysis_date"] = SimpleNamespace(ctype=xlrd.XL_CELL_DATE, value=serial)

    class Sheet:
        def __init__(self, rows):
            self.headers = list(rows[0])
            self.rows = rows
            self.nrows = len(rows) + 1

        def row(self, index):
            values = self.headers if index == 0 else self.rows[index - 1].values()
            return [v if hasattr(v, "ctype") else
                    SimpleNamespace(ctype=xlrd.XL_CELL_TEXT, value=v) for v in values]

    book = SimpleNamespace(datemode=datemode, sheet_by_name=lambda n: Sheet(sheets[n]))
    monkeypatch.setattr(xlrd, "open_workbook", lambda path: book)
    keys, qa = _keys(tmp_path / "native-date.xls", LabEDDProfile.load(PROFILE))
    assert keys == [("SITE", "GW", "AB1", "S1", "LCS", "LEAD", "T",
                     "E200.8", "1|INITIAL|03/17/2025@09:14")]
    assert not qa.has_blocking()
