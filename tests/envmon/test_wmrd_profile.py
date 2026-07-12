"""Shipped WMRD (EQuIS v1) profile loads, validates, and maps the synthesized
__equis_* keys the reader actually writes."""
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_profile import LabEDDProfile, validate_edd_profile

PROFILE = (Path(autogis.__file__).parent / "config" / "lab_profiles"
           / "wmrd.yaml")


def test_profile_loads_and_validates():
    prof = LabEDDProfile.load(PROFILE)
    qa = QACollector()
    validate_edd_profile(prof, qa)
    assert not qa.has_blocking()
    assert prof.format == "equis_xls"
    assert prof.sample_sheet == "Sample_v1"
    assert prof.result_sheet == "TestResultQC_v1"
    assert prof.batch_sheet == "Batch_v1"


def test_synthesized_columns_wired():
    prof = LabEDDProfile.load(PROFILE)
    assert prof.columns["result"] == "__equis_result"
    assert prof.columns["units"] == "__equis_units"
    assert prof.columns["qualifier"] == "__equis_qualifier"
    assert prof.columns["qc_type"] == "__equis_qc_type"
    assert prof.columns["dilution_factor"] == "__equis_method_dilution_key"
    assert prof.columns["is_reportable"] == "__equis_is_reportable"
    assert prof.columns["reporting_limit"] == "__equis_reporting_limit"
    assert prof.columns["detection_limit"] == "__equis_detection_limit"
    assert prof.columns["quantitation_limit"] == "__equis_quantitation_limit"


def test_qc_sample_type_vocabulary():
    prof = LabEDDProfile.load(PROFILE)
    m = prof.value_maps["qc_sample_type"]
    assert m["N"] == ""
    assert m["QC-LCS"] == "LCS"
    assert m["QC-LMSD"] == "MSD"
    assert m["QC-LB"] == "LAB_BLANK"
    assert m["SRM"] == "SRM"
