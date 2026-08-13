# ADR-0129: Connection-profile picker — registered profiles as a dropdown

**Status:** Accepted

**Date:** 2026-08-12

## Context

The AGOL connection profile (an ArcGIS API for Python connection profile
name) was entered as free text everywhere it appears: 11 `agol`/harvester CLI
commands declared `--profile` as a plain string, and the Site Config Builder
GUI dialog used a `QLineEdit`. Users had no way to see which profiles were
registered on the machine — they had to remember exact names — which is the
"pick don't type" gap the GUI usability track already targets.

The `arcgis` API's `ProfileManager` stores profile metadata (name, url,
username) in `~/.arcgisprofile` (a plain INI file); the password lives
separately in the OS keyring, keyed by profile name. Listing the registered
profiles therefore needs only the INI file — no `arcgis` import, no keyring
read.

## Decision

1. **`autogis.runtime.sessions.list_connection_profiles(path=None)`** — a
   stdlib-only (`configparser`) helper that returns the sorted names of
   *complete* profiles (sections carrying both `url` and `username`), skipping
   the half-written sections a failed `store_credential` leaves behind. It is
   **fail-open**: a missing or corrupt profile file yields `[]` rather than
   raising, so it is safe to call at CLI import time. It never reads the
   keyring or imports `arcgis`, preserving the arcgis-free import invariant of
   `core`/`adapters`.

2. **CLI** — a single `connection_profile_option` decorator in `cli.py`
   (mirroring the existing `qa_report_options` pattern) replaces the 11
   hand-written `--profile` declarations. It wires the option to a
   `SuggestedChoice` of the registered profile names, which `gui/introspect.py`
   already renders as an editable combo box. **Suggest, not restrict:** the CLI
   still accepts any typed name, because a headless/cloud box may have no
   profile store. When *zero* profiles are registered the option type is
   `None` (plain text) rather than an empty `SuggestedChoice`, preserving the
   introspection guard that every choice field carries choices.

3. **GUI** — the Config Builder dialog's connection field becomes an editable
   `QComboBox` populated from `list_connection_profiles()` at dialog
   construction (so a profile added since launch appears without restarting),
   with a blank first item meaning anonymous access.

The profile names are snapshotted once at CLI import (a CLI run is a fresh
process, so always current); the long-running GUI re-reads on each dialog open.

## Consequences

- The dropdown reflects only *complete* profiles; a profile whose keyring
  password is missing still lists (the file has url+username) and fails at
  login time, as it did before — this helper does not probe the keyring.
- No new dependency; the heavy `arcgis.ProfileManager` is deliberately not
  used.
- Tests: `tests/test_connection_profiles.py` (filter + fail-open) and a Config
  Builder dialog test asserting the editable dropdown is populated yet still
  accepts a typed name.
