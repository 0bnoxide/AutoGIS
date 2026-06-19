import pytest
from autogis.core import gis_session


def fake_factory(*args, **kwargs):
    return ("GIS", args, kwargs)


def test_build_gis_with_profile():
    out = gis_session.build_gis(profile="myprof", gis_factory=fake_factory)
    assert out == ("GIS", (), {"profile": "myprof"})


def test_build_gis_with_userpass():
    out = gis_session.build_gis(username="u", password="p",
                                gis_factory=fake_factory)
    assert out == ("GIS", ("https://www.arcgis.com", "u", "p"), {})


def test_build_gis_profile_wins_over_userpass():
    out = gis_session.build_gis(profile="myprof", username="u", password="p",
                                gis_factory=fake_factory)
    assert out == ("GIS", (), {"profile": "myprof"})


def test_build_gis_no_creds_raises():
    with pytest.raises(ValueError):
        gis_session.build_gis(gis_factory=fake_factory)


def test_build_gis_from_env(monkeypatch):
    monkeypatch.setenv("AGOL_USER", "envu")
    monkeypatch.setenv("AGOL_PASS", "envp")
    out = gis_session.build_gis_from_env(profile=None, gis_factory=fake_factory)
    assert out == ("GIS", ("https://www.arcgis.com", "envu", "envp"), {})
