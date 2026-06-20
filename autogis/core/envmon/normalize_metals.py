"""Metals normalization."""
from __future__ import annotations

from typing import List, Tuple

from ..common.config import ParserProfile
from .excel_profile_reader import ProfileWorkbookReader
from .gdb_schema import AnalyticalResultRecord, SampleRecord
from ..common.qa import QACollector
from .table_normalizer import normalize_matrix_table


def normalize_metals_table(workbook_path, profile: ParserProfile,
                           site_id: str, batch_id: str,
                           analyte_dictionary: dict, screening_levels: dict,
                           qa: QACollector,
                           reader: ProfileWorkbookReader | None = None
                           ) -> Tuple[List[SampleRecord],
                                      List[AnalyticalResultRecord]]:
    reader = reader or ProfileWorkbookReader(workbook_path, profile, qa)
    samples, results = [], []
    for sheet in profile.sheets_of_type("METALS"):
        s, r = normalize_matrix_table(
            reader, sheet, matrix="GW", analytical_group="METALS",
            site_id=site_id, batch_id=batch_id,
            analyte_dictionary=analyte_dictionary,
            screening_levels=screening_levels, qa=qa)
        samples.extend(s)
        results.extend(r)
    return samples, results
