"""DRAFT: Survey123 transport evidence; real-device/live acceptance pending.

One invocation compares one device payload root with one hosted layer and an
optional client layer. Presence proves observation under that source's access
scope, never the cause of absence or the time of historical delivery. Stdlib
only; the adapter supplies live FeatureLayer objects through the lazy provider.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from .survey_sync import LayerPull, payload_hash

DEVICE_STATES = {0: 'draft', 1: 'outbox', 2: 'sent', 3: 'submission_error', 4: 'inbox'}


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(value) -> str | None:
    # Never stringify null, bool, containers, or lossy floating-point IDs.
    if type(value) not in (str, int):
        return None
    text = str(value)
    if not text or text != text.strip() or any(ord(c) < 32 for c in text):
        return None
    try:
        return str(UUID(text))
    except ValueError:
        return text


def validate_layer_url(value: str) -> str:
    """Require a credential-free HTTPS layer URL, not a service or query URL."""
    if value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError('Layer URL must not contain surrounding whitespace or control characters.')
    try:
        parsed = urlsplit(value)
    except ValueError:
        # urllib errors can echo a credential-bearing authority verbatim.
        raise ValueError('Invalid layer URL; provide a credential-free HTTPS layer URL.') from None
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or not re.search(r'/FeatureServer/\d+/?$', parsed.path, re.I)):
        raise ValueError('Use an HTTPS FeatureServer/<layer-id> URL without '
                         'credentials, query parameters, or fragments; use a profile for login.')
    return value.rstrip('/')


def _utc_time(value) -> str:
    if not isinstance(value, str):
        raise ValueError('Snapshot observed_at must be an ISO timestamp with a timezone.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Snapshot observed_at must be an ISO timestamp with a timezone.') from None
    if parsed.tzinfo is None:
        raise ValueError('Snapshot observed_at must include a timezone.')
    return parsed.astimezone(timezone.utc).isoformat()


def read_device(path: Path, *, root: str, key_field: str) -> tuple[list[dict], dict]:
    """Read the device export without disclosing raw SQLite decoding errors."""
    try:
        return _read_device(path, root=root, key_field=key_field)
    except sqlite3.Error:
        # SQLite's invalid-text errors include the raw cell value.
        raise ValueError('Device SQLite export could not be read; verify its schema '
                         'and UTF-8 data in a closed, consolidated copy.') from None


def _require_consolidated_export(path: Path) -> None:
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError('Device export has an active WAL/journal; supply a closed, consolidated copy.')


def _read_device(path: Path, *, root: str, key_field: str) -> tuple[list[dict], dict]:
    """Read a closed device export's Surveys.data[root]; never mutate the DB.

    Root names are exact and required: a device database may hold many forms.
    Repeats are deliberately not traversed; they are not parent submissions.
    Inbox copies are excluded, edits retained but excluded from new-work counts.
    """
    path = Path(path).resolve(strict=True)
    _require_consolidated_export(path)
    before = _file_hash(path)
    records = []
    stats = dict(source=str(path), sha256=before, root=root, key_field=key_field,
                 read_at=datetime.now(timezone.utc).isoformat(),
                 selected_rows=0, unrelated_rows=0, excluded_inbox_rows=0)
    # Closed/consolidated exports only: immutable also prevents a WAL-mode
    # reader from creating -wal/-shm beside the evidence (mode=ro alone does not).
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('BEGIN')
        table = db.execute("SELECT type FROM sqlite_master WHERE lower(name)='surveys'").fetchone()
        columns = {row[1].lower() for row in db.execute('PRAGMA table_info(Surveys)')}
        if table != ('table',) or not {'name', 'data', 'status'} <= columns:
            raise ValueError('Unsupported device schema: expected a Surveys table with name, data, status.')
        for row_id, data, status in db.execute('SELECT rowid, data, status FROM Surveys ORDER BY rowid'):
            try:
                payload = json.loads(data)
            except (ValueError, TypeError):
                raise ValueError(f'Device row {row_id} has invalid JSON data.') from None
            if not isinstance(payload, dict):
                raise ValueError(f'Device row {row_id} data must be an object.')
            if root not in payload:
                stats['unrelated_rows'] += 1
                continue
            attrs = payload[root]
            if not isinstance(attrs, dict):
                raise ValueError(f'Device row {row_id} selected root must be an object.')
            if type(status) is not int or status not in DEVICE_STATES:
                raise ValueError(f'Device row {row_id} has an unsupported status.')
            stats['selected_rows'] += 1
            if status == 4:
                stats['excluded_inbox_rows'] += 1
                continue
            meta = attrs.get('__meta__', {})
            mode = meta.get('editMode') if isinstance(meta, dict) else None
            valid_mode = type(mode) is int and mode in (0, 1)
            records.append(dict(
                identity=_identity(attrs.get(key_field)), source=str(path),
                row=row_id, state=DEVICE_STATES[status],
                edit_mode=mode if valid_mode else None,
                new_ready=status in (1, 2, 3) and valid_mode and mode == 0,
                issue='' if valid_mode else 'unknown_device_edit_mode',
                payload_hash=payload_hash(attrs, None)))
    if _file_hash(path) != before:
        raise ValueError('Device export changed while being read; retry with a closed copy.')
    # A concurrent writer may commit only to WAL, leaving main-file bytes unchanged.
    _require_consolidated_export(path)
    if not stats['selected_rows']:
        raise ValueError('No device rows match the selected payload root.')
    return records, stats


def validate_snapshot(snapshot: dict, *, key_field: str) -> tuple[list[dict], dict]:
    """Consume an explicitly complete single-layer snapshot, never a sync delta."""
    if (not isinstance(snapshot, dict) or type(snapshot.get('version')) is not int
            or snapshot['version'] != 1 or snapshot.get('complete') is not True
            or snapshot.get('exceededTransferLimit', False) is not False):
        raise ValueError('Expected a version 1 snapshot with complete=true and no transfer-limit flag.')
    source = snapshot.get('source')
    if (not isinstance(source, str) or not source or source != source.strip()
            or any(ord(c) < 32 for c in source)):
        raise ValueError('Snapshot source must be a nonempty identifier without surrounding whitespace or control characters.')
    if source.lower().startswith(('http:', 'https:')):
        validate_layer_url(source)
    observed = _utc_time(snapshot.get('observed_at'))
    features = snapshot.get('features')
    if not isinstance(features, list):
        raise ValueError('Snapshot features must be a list.')
    records = []
    for number, feature in enumerate(features, 1):
        if not isinstance(feature, dict) or not isinstance(feature.get('attributes'), dict):
            raise ValueError(f'Snapshot feature {number} must have an attributes object.')
        attrs = feature['attributes']
        records.append(dict(identity=_identity(attrs.get(key_field)),
                            source=source, row=number, observed_at=observed,
                            payload_hash=payload_hash(attrs, feature.get('geometry'))))
    return records, dict(source=source, observed_at=observed, complete=True,
                        key_field=key_field, feature_count=len(records))


def read_snapshot(path: Path, *, key_field: str) -> tuple[list[dict], dict]:
    path = Path(path)
    raw = path.read_bytes()
    try:
        snapshot = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('Snapshot file must contain valid JSON.') from None
    records, meta = validate_snapshot(snapshot, key_field=key_field)
    meta.update(file=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())
    return records, meta


def fetch_snapshot(layer, *, source: str, key_field: str) -> dict:
    """Full read-only layer pull, checking OBJECTID membership before and after.

    Uses Phase 2's LayerPull shape but never an incremental watermark. Unlike
    sync this supports read-only client views without editor tracking.
    """
    source = validate_layer_url(source)
    props = dict(layer.properties)
    oid = props.get('objectIdField')
    fields = {f['name'] for f in props.get('fields', [])}
    if not oid or key_field not in fields:
        raise ValueError('Layer must expose an objectIdField and the configured identity field.')

    def ids():
        result = layer.query(where='1=1', return_ids_only=True)
        if (not isinstance(result, dict) or not isinstance(result.get('objectIds'), list)
                or result.get('exceededTransferLimit', False) is not False
                or any(type(v) is not int for v in result['objectIds'])):
            raise ValueError('Layer returned an incomplete or invalid OBJECTID inventory.')
        return set(result['objectIds'])

    before = ids()
    result = layer.query(where='1=1', out_fields='*', return_geometry=False,
                         return_all_records=True)
    pull = LayerPull(layer_id=int(props['id']), name=props.get('name', ''),
                     global_id_field=key_field,
                     features=[{'attributes': dict(f.attributes)} for f in result.features])
    observed_ids = [f['attributes'].get(oid) for f in pull.features]
    if (any(type(v) is not int for v in observed_ids)
            or len(observed_ids) != len(before)
            or set(observed_ids) != before or ids() != before):
        raise ValueError('Layer snapshot is incomplete or changed during the pull; retry.')
    return dict(version=1, complete=True, source=source,
                observed_at=datetime.now(timezone.utc).isoformat(), features=pull.features)


def reconcile(device: list[dict], hosted: list[dict], client: list[dict] | None,
              *, sources: dict) -> dict:
    """Count distinct unambiguous identities, preserving every duplicate's evidence."""
    indexed = defaultdict(lambda: {'device': [], 'hosted': [], 'client': []})
    for leg, observations in (('device', device), ('hosted', hosted), ('client', client or [])):
        for number, observation in enumerate(observations):
            identity = observation['identity']
            # Separate namespace for missing identities; never match nulls together.
            group = ('key', identity) if identity is not None else (leg, number)
            indexed[group][leg].append(observation)
    rows = []
    for group, evidence in sorted(indexed.items(), key=lambda item: str(item[0])):
        d, h, c = (evidence[leg] for leg in ('device', 'hosted', 'client'))
        problems = [f'duplicate_{leg}' for leg, values in evidence.items() if len(values) > 1]
        if group[0] != 'key':
            problems.append('missing_or_invalid_identity')
        problems.extend(o['issue'] for o in d if o.get('issue'))
        if problems:
            status = 'needs_review'
        elif c:
            status = 'visible_at_client' if h else 'client_only'
        elif h:
            status = 'hosted_client_not_checked' if client is None else 'hosted_not_visible_at_client'
        else:
            status = 'device_only'
        rows.append(dict(identity=group[1] if group[0] == 'key' else None,
                         status=status, issues=sorted(set(problems)), evidence=evidence,
                         new_ready=bool(d and d[0]['new_ready'] and not problems)))
    counts = dict(Counter(row['status'] for row in rows))
    counts.update(record_groups=len(rows), needs_review=counts.get('needs_review', 0),
                  excluded_inbox_rows=sum(m['excluded_inbox_rows'] for m in sources['device']))
    for leg, observations in (('device', device), ('hosted', hosted), ('client', client)):
        counts[f'{leg}_rows'] = None if observations is None else len(observations)
        counts[f'{leg}_unique'] = (None if observations is None else
                                  len({o['identity'] for o in observations if o['identity'] is not None}))
    candidates = [row for row in rows if row['new_ready']]
    counts['device_new_ready_unique'] = len(candidates)
    counts['device_new_ready_hosted_unique'] = sum(bool(r['evidence']['hosted']) for r in candidates)
    counts['device_new_ready_client_unique'] = (None if client is None else
                                               sum(bool(r['evidence']['client']) for r in candidates))
    return dict(version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                sources=sources, counts=counts, records=rows,
                limitations=[
                    'DRAFT: real-device and live non-production acceptance pending.',
                    'Presence is observation under the source access scope, not historical delivery proof.',
                    'Endpoint absence does not prove a QA hold, deletion, or failed submission.',
                    'Sources are observed at different times; field edits during a live pull are not frozen.',
                    'Counts cover parent submissions only. Drafts, inbox copies, edits, and ambiguous IDs are not new-ready work.',
                    'New-ready counts support review; they are not an approved invoice.'])


def write_report(report: dict, directory: Path) -> None:
    """Publish both evidence artifacts together into a new directory."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError('Report directory already exists; choose a new --out directory.')
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.provenance-', dir=directory.parent) as temporary:
        staged = Path(temporary) / 'report'
        staged.mkdir()
        (staged / 'provenance.json').write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
        with (staged / 'records.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['identity', 'status', 'device_rows', 'hosted_rows', 'client_rows', 'new_ready', 'issues'])
            for row in report['records']:
                identity = row['identity'] or ''
                # Spreadsheet formula protection; the JSON retains exact IDs.
                if identity.startswith(('=', '+', '-', '@')):
                    identity = "'" + identity
                writer.writerow([identity, row['status'],
                                 *[len(row['evidence'][leg]) for leg in ('device', 'hosted', 'client')],
                                 row['new_ready'], ';'.join(row['issues'])])
        with (staged / 'counts.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['metric', 'count'])
            writer.writerows(sorted(report['counts'].items()))
        os.rename(staged, directory)
