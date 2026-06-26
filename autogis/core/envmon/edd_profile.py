# autogis/core/envmon/edd_profile.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from autogis.core.common.config import load_config
from autogis.core.common.qa import QACollector, SEV_ERROR

_REQUIRED_COLUMNS = {
    "sample_id", "location_id", "event_date", "matrix",
    "analyte", "result", "units", "qualifier", "reporting_limit",
}
_VALID_FORMATS = {"flat_csv", "two_tab_xlsx"}


@dataclass
class LabEDDProfile:
    profile_id: str
    lab_name: str
    format: str                              # "flat_csv" | "two_tab_xlsx"
    date_format: str
    encoding: str
    columns: dict[str, str | list[str]]     # field_name -> col_name(s)
    matrix_map: dict[str, str]
    nondetect_qualifiers: list[str]
    sample_sheet: str = "Samples"            # two_tab_xlsx only
    result_sheet: str = "Results"            # two_tab_xlsx only
    path: Optional[Path] = field(default=None, compare=False)

    @classmethod
    def load(cls, path: Path) -> "LabEDDProfile":
        path = Path(path)
        data = load_config(path)
        return cls(
            profile_id=data["profile_id"],
            lab_name=data.get("lab_name", data["profile_id"]),
            format=data.get("format", "flat_csv"),
            date_format=data.get("date_format", "%m/%d/%Y"),
            encoding=data.get("encoding", "utf-8"),
            columns=data.get("columns", {}),
            matrix_map=data.get("matrix_map", {}),
            nondetect_qualifiers=data.get("nondetect_qualifiers", ["U", "UJ"]),
            sample_sheet=data.get("sample_sheet", "Samples"),
            result_sheet=data.get("result_sheet", "Results"),
            path=path,
        )

    def resolve_column(self, row: dict, field: str) -> str | None:
        """Return the row value for a canonical field, or None if not found.

        Tries each alternate column name in order. Caller emits QA on None."""
        spec = self.columns.get(field)
        if spec is None:
            return None
        names = [spec] if isinstance(spec, str) else spec
        for name in names:
            val = row.get(name)
            if val is not None:
                return str(val) if val != "" else None
        return None


def validate_edd_profile(profile: LabEDDProfile, qa: QACollector) -> None:
    if profile.format not in _VALID_FORMATS:
        qa.add(SEV_ERROR, "edd_profile_bad_format",
               f"Unknown format '{profile.format}'; expected one of "
               f"{sorted(_VALID_FORMATS)}")
    for req in sorted(_REQUIRED_COLUMNS):
        if req not in profile.columns:
            qa.add(SEV_ERROR, "edd_profile_missing_column",
                   f"Required column mapping '{req}' not defined in profile "
                   f"'{profile.profile_id}'")
