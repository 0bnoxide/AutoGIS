"""#608: Excel "CSV UTF-8" adds a BOM; read-side CSV opens must strip it."""
import re
from pathlib import Path

import autogis
from autogis.adapters.cli import _read_csv_rows, _read_id_list
from autogis.core.envmon.batch_workbook_importer import read_manifest_csv
from autogis.core.envmon.import_boring_logs import parse_boring_locations_csv

_BOM = "﻿"


def _write(p: Path, text: str) -> Path:
    p.write_text(_BOM + text, encoding="utf-8")
    return p


def test_manifest_with_bom(tmp_path):
    p = _write(tmp_path / "m.csv", "workbook_path,profile_path,site_id\na.csv,p.yaml,S1\n")
    assert read_manifest_csv(p)[0]["workbook_path"] == "a.csv"


def test_cli_csv_helper_with_bom(tmp_path):
    p = _write(tmp_path / "r.csv", "LocationID,Value\nMW-01,1\n")
    assert _read_csv_rows(p)[0]["LocationID"] == "MW-01"


def test_boring_locations_with_bom(tmp_path):
    p = _write(tmp_path / "b.csv", "BoringID,SiteID\nB-1,S1\n")
    assert parse_boring_locations_csv(p)[0].boring_id == "B-1"


def test_id_list_with_bom(tmp_path):
    assert _read_id_list(_write(tmp_path / "ids.txt", "MW-01\nMW-02\n")) == {"MW-01", "MW-02"}


def test_no_csv_reader_opens_plain_utf8():
    """Guard: any read-mode open(newline="") in a csv-reading module uses utf-8-sig."""
    root = Path(autogis.__file__).parent
    bad = []
    for f in root.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        if not re.search(r"csv\.(Dict)?[Rr]eader", src):
            continue
        for n, line in enumerate(src.splitlines(), 1):
            if ('newline="", encoding="utf-8")' in line
                    and not re.search(r'"[wax]\+?"|mode', line)):
                bad.append(f"{f.relative_to(root)}:{n}")
    assert not bad, bad
