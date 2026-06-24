import yaml

from autogis.core.envmon.manage_analyte_dict import (check_analyte_dictionary,
                                                      list_analytes)
from autogis.core.common.qa import SEV_ERROR


def _write(tmp_path, data):
    p = tmp_path / "analytes.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_check_flags_alias_collision(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10},
        "Toluene": {"aliases": ["b"], "abbreviation": "T", "display_order": 20}}})
    qa = check_analyte_dictionary(p)
    assert (SEV_ERROR, "alias_collision") in {(r.severity, r.category)
                                              for r in qa.records}


def test_list_analytes_sorted_by_display_order(tmp_path):
    p = _write(tmp_path, {"analytes": {
        "Toluene": {"aliases": ["toluene"], "abbreviation": "T",
                    "display_order": 20, "analytical_group": "VOC"},
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10, "analytical_group": "VOC"}}})
    rows = list_analytes(p)
    assert [r["canonical"] for r in rows] == ["Benzene", "Toluene"]
    assert rows[0]["alias_count"] == 2
