"""Transport evidence at real SQLite, snapshot, and CLI boundaries."""
import csv
import hashlib
import importlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def device(path, rows):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE Surveys (name TEXT, data TEXT, status INTEGER)')
        db.executemany('INSERT INTO Surveys VALUES (?, ?, ?)', [
            ('survey', json.dumps({'inspection': dict(
                record_id=key, __meta__={'editMode': mode})}), status)
            for key, status, mode in rows])
    return path


def snapshot(path, keys, **overrides):
    content = dict(version=1, complete=True, source='fixture:layer/0',
                   observed_at='2026-09-12T10:00:00+00:00',
                   features=[{'attributes': {'record_id': key}} for key in keys])
    content.update(overrides)
    path.write_text(json.dumps(content), encoding='utf-8')
    return path


def invoke(tmp_path, db, hosted, *extra):
    return CliRunner().invoke(autogis, [
        'envmon', 'trace-survey123', '--device', str(db),
        '--device-root', 'inspection', '--device-key', 'record_id',
        '--hosted-json', str(hosted), '--hosted-key', 'record_id',
        '--client-key', 'record_id', '--out', str(tmp_path / 'report'), *extra],
        env={'AUTOGIS_RUN_HISTORY': str(tmp_path / 'history.csv')})


def test_cli_traces_delivery_without_claiming_qa_hold_or_double_billing(tmp_path):
    db = device(tmp_path / 'device.sqlite', [
        ('visible', 2, 0), ('upstream', 2, 0), ('unsent', 1, 0),
        ('downloaded', 4, 0), ('edited', 2, 1), ('draft', 0, 0)])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    hosted = snapshot(tmp_path / 'hosted.json', ['visible', 'upstream', 'edited'])
    client = snapshot(tmp_path / 'client.json', ['visible', 'client-only'])
    result = invoke(tmp_path, db, hosted, '--client-json', str(client))
    assert result.exit_code == 2, result.output
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    by_key = {row['identity']: row for row in report['records']}
    assert by_key['visible']['status'] == 'visible_at_client'
    assert by_key['upstream']['status'] == 'hosted_not_visible_at_client'
    assert by_key['unsent']['status'] == 'device_only'
    assert by_key['client-only']['status'] == 'client_only'
    assert 'downloaded' not in by_key
    assert report['counts']['device_new_ready_unique'] == 3
    assert report['counts']['device_new_ready_hosted_unique'] == 2
    assert report['counts']['device_new_ready_client_unique'] == 1
    assert report['counts']['excluded_inbox_rows'] == 1
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    history = list(csv.DictReader((tmp_path / 'history.csv').open()))
    assert history[-1]['status'] == 'success'


def test_duplicates_and_missing_keys_remain_reviewable_and_not_billable(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('dup', 2, 0), ('dup', 2, 0), (None, 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', ['dup'])
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 2, result.output
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['counts']['device_new_ready_unique'] == 0
    assert report['counts']['needs_review'] == 2
    assert sum(len(row['evidence']['device']) for row in report['records']) == 3


@pytest.mark.parametrize('overrides', [
    {'complete': False}, {'complete': 'true'}, {'features': {}},
    {'features': [{'attributes': []}]}, {'observed_at': 'yesterday'},
    {'exceededTransferLimit': True}, {'version': True}])
def test_malformed_or_incomplete_snapshots_fail_before_report(tmp_path, overrides):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', ['a'], **overrides)
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 1, result.output
    assert not (tmp_path / 'report').exists()


def test_optional_client_is_unobserved_and_report_cannot_overwrite_input(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', ['a'])
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['records'][0]['status'] == 'hosted_client_not_checked'
    assert report['counts']['client_unique'] is None
    assert report['counts']['device_new_ready_client_unique'] is None
    original = (tmp_path / 'report/provenance.json').read_bytes()
    assert invoke(tmp_path, db, hosted).exit_code == 1
    assert (tmp_path / 'report/provenance.json').read_bytes() == original


def test_device_schema_and_wrong_root_fail_closed(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', ['a'])
    result = invoke(tmp_path, db, hosted, '--device-root', 'wrong')
    assert result.exit_code == 1
    assert not (tmp_path / 'report').exists()


def test_live_fetch_rejects_truncated_and_changing_results():
    mod = importlib.import_module('autogis.core.envmon.submission_provenance')
    class Layer:
        properties = {'id': 0, 'name': 'Inspection', 'objectIdField': 'OBJECTID',
                      'fields': [{'name': 'OBJECTID'}, {'name': 'record_id'}]}

        def query(self, **kwargs):
            assert kwargs['where'] == '1=1'
            if kwargs.get('return_ids_only'):
                return {'objectIds': [1, 2]}
            assert kwargs['return_all_records'] is True
            return SimpleNamespace(features=[SimpleNamespace(
                attributes={'OBJECTID': 1, 'record_id': 'a'})])

    with pytest.raises(ValueError, match='incomplete|changed'):
        mod.fetch_snapshot(Layer(), source='https://example.org/FeatureServer/0',
                           key_field='record_id')


@pytest.mark.parametrize('value', [True, 1.5, {}, [], '', ' abc ', '\t=bad'])
def test_invalid_ids_never_match_or_count_as_new_work(tmp_path, value):
    db = device(tmp_path / 'device.sqlite', [(value, 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', [value])
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 2, result.output
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['counts']['needs_review'] == 2
    assert report['counts']['device_new_ready_hosted_unique'] == 0


def test_guid_normalization_and_business_key_case_sensitivity(tmp_path):
    db = device(tmp_path / 'device.sqlite', [
        ('{12345678-1234-1234-ABCD-123456789ABC}', 2, 0), ('CaseSensitive', 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', [
        '12345678-1234-1234-abcd-123456789abc', 'casesensitive'])
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 2, result.output
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['counts']['device_new_ready_hosted_unique'] == 1
    assert report['counts']['record_groups'] == 3


def test_multiple_devices_duplicate_endpoints_and_unknown_edit_mode(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    other = device(tmp_path / 'other.sqlite', [('b', 2, None)])
    hosted = snapshot(tmp_path / 'hosted.json', ['a', 'a', 'b'])
    result = invoke(tmp_path, db, hosted, '--device', str(other))
    assert result.exit_code == 2, result.output
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['counts']['needs_review'] == 2
    assert report['counts']['device_new_ready_unique'] == 0


@pytest.mark.parametrize('change', ['schema', 'json', 'status', 'root', 'wal'])
def test_unrecognized_device_data_fails_without_touching_source(tmp_path, change):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    with sqlite3.connect(db) as conn:
        if change == 'schema':
            conn.execute('DROP TABLE Surveys')
        elif change == 'json':
            conn.execute("UPDATE Surveys SET data='not-json'")
        elif change == 'status':
            conn.execute('UPDATE Surveys SET status=99')
        elif change == 'root':
            conn.execute('UPDATE Surveys SET data=?', ('{"inspection":[]}',))
    if change == 'wal':
        (tmp_path / 'device.sqlite-wal').write_bytes(b'unconsolidated')
    before = db.read_bytes()
    hosted = snapshot(tmp_path / 'hosted.json', ['a'])
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 1, result.output
    assert not (tmp_path / 'report').exists()
    assert db.read_bytes() == before


def test_repeats_and_other_forms_do_not_inflate_parent_counts(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE Surveys SET data=?', (json.dumps({'inspection': {
            'record_id': 'a', '__meta__': {'editMode': 0},
            'repeat': [{'record_id': 'child-a'}, {'record_id': 'child-b'}]}}),))
        conn.execute('INSERT INTO Surveys VALUES (?, ?, ?)',
                     ('other', '{"other_form":{"record_id":"unrelated"}}', 2))
    hosted = snapshot(tmp_path / 'hosted.json', ['a'])
    assert invoke(tmp_path, db, hosted).exit_code == 0
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['counts']['device_new_ready_unique'] == 1
    assert report['sources']['device'][0]['unrelated_rows'] == 1


def test_partial_report_write_failure_leaves_no_final_artifacts(tmp_path, monkeypatch):
    mod = importlib.import_module('autogis.core.envmon.submission_provenance')
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', ['a'])

    def fail_rename(*args):
        raise OSError('injected publish failure')

    monkeypatch.setattr(mod.os, 'rename', fail_rename)
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 1
    assert not (tmp_path / 'report').exists()
    assert not list(tmp_path.glob('.provenance-*'))


def test_live_cli_uses_separate_profiles_and_rejects_partial_results(tmp_path, monkeypatch):
    import sys
    import types
    from autogis.adapters import cli

    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    profiles = []
    monkeypatch.setattr(cli, 'agol_from_profile', lambda p: profiles.append(p) or p)
    original_find = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec',
                        lambda name: True if name == 'arcgis' else original_find(name))
    class Layer:
        properties = {'id': 0, 'name': 'Inspection', 'objectIdField': 'OBJECTID',
                      'fields': [{'name': 'OBJECTID'}, {'name': 'record_id'}]}

        def __init__(self, url, gis):
            self.url = url

        def query(self, **kwargs):
            if kwargs.get('return_ids_only'):
                return {'objectIds': [1]}
            return SimpleNamespace(features=[SimpleNamespace(
                attributes={'OBJECTID': 1, 'record_id': 'a'})])

    module = types.ModuleType('arcgis.features')
    module.FeatureLayer = Layer
    monkeypatch.setitem(sys.modules, 'arcgis.features', module)
    result = CliRunner().invoke(autogis, [
        'envmon', 'trace-survey123', '--device', str(db), '--device-root', 'inspection',
        '--device-key', 'record_id', '--hosted-key', 'record_id', '--client-key', 'record_id',
        '--hosted-url', 'https://host.example/FeatureServer/0', '--profile', 'org',
        '--client-url', 'https://client.example/FeatureServer/0', '--client-profile', 'client',
        '--out', str(tmp_path / 'report')], env={'AUTOGIS_RUN_HISTORY': 'off'})
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['counts']['device_new_ready_client_unique'] == 1
    assert profiles == ['org', 'client']


def test_live_install_hint_and_credential_url_not_recorded(tmp_path, monkeypatch):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: None)
    args = ['envmon', 'trace-survey123', '--device', str(db), '--device-root', 'inspection',
            '--out', str(tmp_path / 'report'), '--hosted-url']
    env = {'AUTOGIS_RUN_HISTORY': str(tmp_path / 'history.csv')}
    result = CliRunner().invoke(autogis, args + ['https://host.example/FeatureServer/0'], env=env)
    assert result.exit_code == 1
    assert 'pip install "autogis[survey123]"' in result.output
    original = (tmp_path / 'history.csv').read_bytes()
    result = CliRunner().invoke(autogis, args + ['https://host.example/FeatureServer/0?token=demo'], env=env)
    assert result.exit_code == 2
    assert 'token=demo' not in result.output
    assert (tmp_path / 'history.csv').read_bytes() == original


def test_formula_like_id_is_preserved_in_json_and_escaped_in_csv(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('=1+1', 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', ['=1+1'])
    assert invoke(tmp_path, db, hosted).exit_code == 0
    report = json.loads((tmp_path / 'report/provenance.json').read_text())
    assert report['records'][0]['identity'] == '=1+1'
    with (tmp_path / 'report/records.csv').open(newline='') as stream:
        assert list(csv.DictReader(stream))[0]['identity'] == "'=1+1"


def test_sqlite_decode_failure_cannot_echo_private_payload(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE Surveys SET data=CAST(? AS TEXT)',
                     (b'PRIVATE_FIELD_MARKER\xff',))
    hosted = snapshot(tmp_path / 'hosted.json', ['a'])
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 1
    assert 'PRIVATE_FIELD_MARKER' not in result.output
    assert 'PRIVATE_FIELD_MARKER' not in (tmp_path / 'history.csv').read_text()
    assert not (tmp_path / 'report').exists()


@pytest.mark.parametrize('prefix', [' ', '\t', '\n'])
def test_whitespace_cannot_hide_a_credential_bearing_snapshot_url(tmp_path, prefix):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    hosted = snapshot(tmp_path / 'hosted.json', ['a'],
                      source=prefix + 'https://example.org/FeatureServer/0?token=demo')
    result = invoke(tmp_path, db, hosted)
    assert result.exit_code == 1
    assert 'token=demo' not in result.output
    assert not (tmp_path / 'report').exists()


def test_url_parser_failure_cannot_echo_credentials(tmp_path):
    db = device(tmp_path / 'device.sqlite', [('a', 2, 0)])
    result = CliRunner().invoke(autogis, [
        'envmon', 'trace-survey123', '--device', str(db), '--device-root', 'inspection',
        '--out', str(tmp_path / 'report'), '--hosted-url',
        'https://user:PRIVATE_PASSWORD_MARKER@example.org\uff1a443/FeatureServer/0'],
        env={'AUTOGIS_RUN_HISTORY': str(tmp_path / 'history.csv')})
    assert result.exit_code == 2
    assert 'PRIVATE_PASSWORD_MARKER' not in result.output
    assert not (tmp_path / 'history.csv').exists()
