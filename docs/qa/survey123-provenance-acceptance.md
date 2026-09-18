# Acceptance run — Survey123 submission provenance tracer (#414)

The one remaining leg of issue #414 (ADR-0136, **Proposed**): prove the
shipped `envmon trace-survey123` against a real device export and real
non-production services, then lift DRAFT. Legs 1–2 run from the base
install (leg 3 needs the `survey123` extra); legs 2–3 are owner-gated
(physical device, live credentials).

Sign-off policy (owner decision, 2026-09-17): **explained-not-zero** —
`needs_review` rows do not block acceptance provided each one is traced to a
known cause and written into the run record. `needs_review` is a retention
bucket, not an error.

## Legs

| Leg | Needs | Proves | Budget |
|---|---|---|---|
| 1 rehearsal | nothing | command shape, PASS rows, guardrails | ~10 min |
| 2 real device | sanitized device export | real schema is readable; box states / editMode / keys | ~30 min |
| 3 live services | `autogis[survey123]`, non-prod hosted + client | inventory check, pagination, sharing-scope vs absence | ~30 min |

Do leg 2 first and alone: an unrecognized schema fails closed and would mean
a reader revision, which invalidates the other legs.

## 1. Rehearsal on synthetic truth (no owner dependency)

```bat
:: any Python with autogis installed — writes to Desktop\AutoGIS-QA\survey123\
python docs\qa\make_survey123_provenance_qa_data.py --check
python docs\qa\make_survey123_provenance_qa_data.py
```

PASS: `--check` prints `CHECK OK`. Then run the same shape by hand:

```bat
set QA=%USERPROFILE%\Desktop\AutoGIS-QA\survey123
:: the tool refuses an existing --out, so clear a previous rehearsal first
if exist %QA%\report-1 rmdir /s /q %QA%\report-1
python -m autogis envmon trace-survey123 ^
  --device %QA%\device.sqlite --device-root inspection --device-key record_id ^
  --hosted-json %QA%\hosted.json --hosted-key record_id ^
  --client-json %QA%\client.json --client-key record_id ^
  --out %QA%\report-1
```

PASS (verified against head `4d04727`):
- [ ] Exit code **2** (findings), `report-1\` holds `provenance.json`,
      `records.csv`, `counts.csv`.
- [ ] `counts.csv`: `device_new_ready_unique=3`,
      `device_new_ready_hosted_unique=2`, `device_new_ready_client_unique=1`,
      `excluded_inbox_rows=1`, `needs_review=0`.
- [ ] `records.csv`: the braced/upper GUID from the device matched the
      bare/lower GUID downstream → `visible_at_client`; `edited` is
      `hosted_not_visible_at_client` with `new_ready=False`; `draft` is
      `device_only` with `new_ready=False`.
- [ ] Guardrails: re-run with the same `--out` → refused, no files touched;
      `--device-root wrongroot` → exit 1 "No device rows match"; omit
      `--client-json` → `client_rows` is `null` in `provenance.json`,
      **not** `0` (`counts.csv` shows it as an empty cell).
- [ ] No `device.sqlite-wal` / `-shm` beside the export after any run.

## 2. Real device export (owner-gated)

Close the field app, copy the survey's `.sqlite` off the device per the
operator guide's Offline-use section (consolidate WAL first; never point at
the live app DB). Keep the raw copy **off the repo**. Sanitized = the raw
`.sqlite` stays local; the report copies only IDs, hashes and paths.

```bat
certutil -hashfile <export>.sqlite SHA256          :: record BEFORE
python -m autogis envmon trace-survey123 ^
  --device <export>.sqlite --device-root <form root> --device-key globalid ^
  --hosted-json <hosted snapshot>.json --hosted-key GlobalID ^
  --out <reports>\provenance-device-<date>
certutil -hashfile <export>.sqlite SHA256          :: record AFTER
```

If the form root is unknown, run once with a guessed root: the exit-1
message is the cue to inspect `Surveys.data` for the real top-level key.

PASS:
- [ ] Schema accepted — none of these exit-1 messages:
      `Unsupported device schema: expected a Surveys table with name, data, status.`,
      `Device row N has invalid JSON data.`, `Device row N data must be an object.`,
      or `Device SQLite export could not be read; verify its schema and UTF-8
      data in a closed, consolidated copy.`
      **FAIL here → file a reader-revision issue; stop the run.**
- [ ] Before/after SHA-256 identical; no sidecars created.
- [ ] `device_rows + excluded_inbox_rows` equals the independent count
      `SELECT count(*) FROM Surveys WHERE json_extract(data,'$.<root>') IS NOT NULL`
      (any SQLite browser; the reader matches a top-level key, not a substring).
- [ ] Box states line up with what the app showed: Sent rows are
      `hosted_*`/`visible_*`; Outbox/Submission-Error rows are `device_only`
      with `new_ready=True`; Inbox downloads land only in
      `excluded_inbox_rows`; edits (`editMode=1`) have `new_ready=False`.
- [ ] Every `needs_review` row has a written cause (duplicate resend, blank
      key, unknown editMode…) in the run record — explained-not-zero.

## 3. Live non-production services (owner-gated)

```bat
pip install "autogis[survey123]"
python -m autogis envmon trace-survey123 ^
  --device <export>.sqlite --device-root <form root> --device-key globalid ^
  --hosted-url https://<org>/arcgis/rest/services/<svc>/FeatureServer/<n> ^
  --profile <org profile> --hosted-key GlobalID ^
  --client-url https://<client>/arcgis/rest/services/<svc>/FeatureServer/<n> ^
  --client-key <preserved original-GlobalID field> --client-profile <client profile> ^
  --out <reports>\provenance-live-<date>
```

PASS:
- [ ] `hosted_rows` equals the layer's REST `returnCountOnly=true` count
      taken in the same minute; same for the client layer. A layer larger
      than the service `maxRecordCount` proves pagination.
- [ ] Sharing-scope probe: run once with a profile that can see the whole
      hosted layer and once with a restricted view/profile. The restricted
      run must show a visibly smaller `hosted_rows` and list the hidden
      records as `device_only` — the tool cannot tell sharing-hidden from
      absent (documented scope limitation, not a defect). FAIL only if
      `hosted_rows` equals the full-layer count while records are hidden.
- [ ] Credentialed URL (`?token=…`) is refused before run history is
      written; a wrong password aborts with exit 1 and no report directory.
- [ ] `provenance.json` records `source` URLs without credentials and both
      `observed_at` timestamps with timezone.
- [ ] Explained-not-zero applied to any `needs_review` rows.

## 4. Record the outcome

- Comment pass/fail per checkbox on #414; attach `counts.csv` and the
  explained `needs_review` list (never the raw export). File a bug per FAIL.
- On full PASS with owner sign-off, in one follow-up PR: drop DRAFT from
  all four places — `docs/survey123-submission-provenance.md`, the CLI help
  docstring, the `submission_provenance.py` module docstring, and the
  `limitations[0]` string written into every `provenance.json` (grep the
  tests for `acceptance pending` too); flip ADR-0136 to **Accepted**; close
  #414. This does not open Survey123 Phases 4–7.
