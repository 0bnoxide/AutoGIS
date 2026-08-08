"""#445 — `plausible_gwe_range_ft` is owned by the site config, not the profile.

It was *required and type-checked* on the site config, documented there with a
"rows outside this range are excluded from contouring with a QA ERROR" comment,
and read only from the parser profile — which `init-site`'s parser-profile
template does not even contain. So a freshly initialized site had no GWE range
filtering at all while its site.yaml claimed otherwise, and the shipped H281
pair could drift with the profile copy silently winning.
"""
from pathlib import Path

import pytest
import yaml

import autogis
from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader
from autogis.core.envmon.normalize_groundwater import normalize_gw_table_2

CONFIG = Path(autogis.__file__).parent / "config"
BATCH = "TESTBATCH"


def _normalize(workbook, profile, adict, slevels, qa, **kwargs):
    reader = ProfileWorkbookReader(workbook, profile, qa)
    return normalize_gw_table_2(workbook, profile, "H281", BATCH, adict,
                                slevels, qa, reader=reader, **kwargs)


def test_site_range_excludes_out_of_range_elevations(
        workbook, profile, adict, slevels, qa):
    """The synthetic wells sit near 2090 ft; a narrow site window must exclude
    them with a QA ERROR — the behavior site.yaml's comment promises."""
    wl, _s, _r = _normalize(workbook, profile, adict, slevels, qa,
                            plausible_gwe_range_ft=[0, 100])

    errors = [r for r in qa.records
              if r.category == "groundwater_elevation_out_of_range"]
    assert errors, "an out-of-range GWE must raise a QA ERROR"
    measured = [w for w in wl if w.GroundwaterElevation_ft is not None]
    assert measured and all(w.UseForContour == 0 for w in measured)
    assert all("outside configured range" in (w.ExclusionReason or "")
               for w in measured)


def test_a_profile_only_range_no_longer_takes_effect(
        workbook, profile, adict, slevels, qa):
    """The defect: the profile copy was the one that won. Injecting an absurd
    range into the profile alone must now change nothing."""
    profile.data["plausible_gwe_range_ft"] = [0, 100]
    try:
        wl, _s, _r = _normalize(workbook, profile, adict, slevels, qa)
    finally:
        profile.data.pop("plausible_gwe_range_ft", None)

    assert not [r for r in qa.records
                if r.category == "groundwater_elevation_out_of_range"]
    assert [w for w in wl if w.UseForContour == 1], (
        "no site range supplied, so nothing may be excluded on range grounds")


def test_import_passes_the_site_configs_range():
    """`run_import` is the only caller and it holds the SiteConfig. Asserted on
    its source because the call sits past `create_or_update_gdb_schema`, so
    reaching it needs arcpy (ADR-0077 / `pragma: no cover`)."""
    import inspect

    from autogis.core.envmon.import_to_gdb import run_import

    assert 'plausible_gwe_range_ft=site_config.get("plausible_gwe_range_ft")' \
        in inspect.getsource(run_import), \
        "run_import must source the range from the site config, not the profile"


@pytest.mark.parametrize("profile_path", sorted(
    (CONFIG / "parser_profiles").glob("*.yaml")))
def test_no_shipped_parser_profile_claims_the_key(profile_path):
    """Two files claiming one setting is what let them drift. The site config
    is the only owner now, so a profile carrying it would be inert config —
    the exact class this fix removes."""
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    assert "plausible_gwe_range_ft" not in data, (
        f"{profile_path.name} sets plausible_gwe_range_ft, which nothing "
        f"reads; the site config owns it (#445)")


def test_the_site_skeleton_still_ships_the_key():
    """init-site's site.yaml is now the file that actually drives the filter,
    so losing the key there would silently disable it for every new site."""
    skeleton = yaml.safe_load(
        (CONFIG / "_templates" / "site_skeleton" / "site.yaml")
        .read_text(encoding="utf-8"))
    rng = skeleton.get("plausible_gwe_range_ft")
    assert isinstance(rng, list) and len(rng) == 2, rng
