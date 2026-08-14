"""``list_connection_profiles`` powers the AGOL ``--profile`` dropdown: it must
return only *complete* profiles from ``~/.arcgisprofile`` -- url plus one of the
authentication modes ``GIS(profile=...)`` accepts -- and fail open on a
missing/corrupt file, since it runs at CLI import time."""

from autogis.runtime.sessions import list_connection_profiles

COMPLETE = """\
[Greg_Work]
url = https://tt-mmi.maps.arcgis.com/
username = greg.brownell_ECS

[Greg_Personal]
url = https://grew.maps.arcgis.com
username = gregbrownell

[ half_written]
date_modified = 2026-07-05 22:23:16

[YOUR_PROFILE]
date_modified = 2026-07-06 18:38:22

[url_only]
url = https://example.maps.arcgis.com
"""


def _write(tmp_path, text):
    p = tmp_path / ".arcgisprofile"
    p.write_text(text, encoding="utf-8")
    return p


def test_returns_only_complete_profiles_sorted(tmp_path):
    got = list_connection_profiles(_write(tmp_path, COMPLETE))
    # incomplete sections (no url and/or no username) are dropped; result sorted
    assert got == ["Greg_Personal", "Greg_Work"]


def test_missing_file_yields_empty(tmp_path):
    assert list_connection_profiles(tmp_path / "nope") == []


def test_corrupt_file_fails_open(tmp_path):
    # no section header -> ConfigParser raises; helper must swallow, not crash
    assert list_connection_profiles(_write(tmp_path, "garbage without header\n")) == []


def test_non_utf8_file_fails_open(tmp_path):
    # a mis-encoded dotfile raises UnicodeDecodeError (a ValueError) on read;
    # must fail open, not crash the CLI at import
    p = tmp_path / ".arcgisprofile"
    p.write_bytes(b"[Greg]\nurl = https://x\nusername = \xff\xfe not utf-8\n")
    assert list_connection_profiles(p) == []


def test_percent_encoded_url_does_not_crash(tmp_path):
    # ArcGIS profile URLs can contain '%' (percent-encoding); ConfigParser
    # interpolation would raise InterpolationSyntaxError at .get() time
    text = "[Greg]\nurl = https://portal.example/a%20b\nusername = greg\n"
    assert list_connection_profiles(_write(tmp_path, text)) == ["Greg"]


def test_unresolvable_home_fails_open(monkeypatch):
    # Path.home() raises RuntimeError under a service/container account with no
    # resolvable home dir; with path=None the helper must fail open, not crash
    import pathlib

    def _boom():
        raise RuntimeError("no home")

    monkeypatch.setattr(pathlib.Path, "home", staticmethod(_boom))
    assert list_connection_profiles() == []


def test_pki_profile_without_username_is_complete(tmp_path):
    # key_file + cert_file is a supported GIS(profile=...) mode and carries no
    # username; requiring one hid these from the dropdown entirely (#493)
    text = ("[pki]\nurl = https://portal.example\n"
            "key_file = key.pem\ncert_file = cert.pem\n")
    assert list_connection_profiles(_write(tmp_path, text)) == ["pki"]


def test_oauth_client_id_profile_without_username_is_complete(tmp_path):
    text = "[oauth]\nurl = https://portal.example\nclient_id = abc123\n"
    assert list_connection_profiles(_write(tmp_path, text)) == ["oauth"]


def test_half_written_auth_modes_stay_excluded(tmp_path):
    # url alone, or a PKI pair missing its other half, is still the
    # half-written section a failed store_credential leaves behind
    text = ("[url_only]\nurl = https://portal.example\n"
            "[key_no_cert]\nurl = https://portal.example\nkey_file = key.pem\n"
            "[cert_no_key]\nurl = https://portal.example\ncert_file = c.pem\n"
            "[no_url]\nusername = greg\n")
    assert list_connection_profiles(_write(tmp_path, text)) == []


def test_duplicate_stripped_names_deduped(tmp_path):
    # a leading-space variant of an existing name collapses after strip()
    text = COMPLETE + "\n[ Greg_Work]\nurl = https://x\nusername = y\n"
    got = list_connection_profiles(_write(tmp_path, text))
    assert got.count("Greg_Work") == 1


if __name__ == "__main__":  # ponytail self-check
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / ".arcgisprofile"
        f.write_text(COMPLETE, encoding="utf-8")
        assert list_connection_profiles(f) == ["Greg_Personal", "Greg_Work"]
        assert list_connection_profiles(Path(d) / "missing") == []
    print("ok")
