# ADR-0051: Concurrency-safe run-history writes via msvcrt sentinel-byte lock

**Status:** Accepted

**Date:** 2026-07-04

## Context

ADR-0050 (unified GUI direction) decided that concurrent multi-analyst use
over shared/networked project files is real v1 scope (item 5), and that
run-history writes hook at the CLI adapter seam so every invocation logs
(item 6). That turns the known unlocked-append race in
`autogis/core/common/run_history.py` from theoretical into live:

- `RunHistory.write()` checked `Path.exists()` *before* opening the file
  (check-then-act / TOCTOU): two simultaneous first-writers could each
  conclude the file was new and both emit a CSV header row.
- A second header row mid-file makes `_decode` raise on
  `int("qa_count_error")`, which `_load()` converts into a
  `RunHistoryError` for the **entire file** — breaking
  `evaluate-readiness` / `portfolio-metrics` for every tool, not just the
  racing pair.
- Reads were also unlocked, so a reader could observe a torn, mid-write row.

Constraints: this repo runs on Windows (no `fcntl`); nothing in `autogis/`
does file locking today; the deployment scenario is shared SMB project
drives; and an audit-log write must never crash or hang the tool run that
triggered it (existing best-effort contract).

## Decision

A module-private context manager in `run_history.py` (`_sentinel_lock`)
built on stdlib `msvcrt.locking()`, holding a 1-byte OS byte-range lock at a
fixed **past-EOF sentinel offset** (1 GiB):

- **Acquire:** save fd position, `os.lseek` to the sentinel offset,
  `msvcrt.locking(fd, LK_LOCK, 1)` (retries internally ~10 s, then raises
  `OSError`), restore position. Release mirrors it with `LK_UNLCK`.
- **`write()`:** open `"a+"`, acquire the lock, decide the header by
  `os.fstat(fh.fileno()).st_size == 0` **while holding the lock** (atomic
  with respect to other lockers — this closes the TOCTOU), write header if
  needed, write the row, `flush()`, release. Any failure — including lock
  timeout — falls into the existing log-a-warning best-effort path.
- **`_load()`:** the same lock around the read, with the file opened `"r+"`
  because `msvcrt.locking` requires a write-capable handle even for a read.
  A reader therefore never observes a mid-write torn row.
- `import msvcrt` is guarded by `try/except ImportError` so the module still
  imports (lock degrades to a no-op) off-Windows.
- The per-instance read cache is unchanged: every CLI invocation constructs
  a fresh `RunHistory`, so cross-process staleness was never the cache's
  problem and is not made worse here.

## Consequences

### Positive consequences

- Windows byte-range locks are **OS-mandatory and enforced over SMB
  shares** — correctness holds on the actual shared-project-drive
  deployment, not just on one machine.
- Locks are **auto-released when a process dies**; no leaked sidecar
  lockfile, no stale-lock heuristics.
- Locking a **past-EOF sentinel byte** (not byte 0, a real data byte) means
  any process that ignores the convention degrades to the old unlocked
  behavior instead of hitting spurious `ERROR_LOCK_VIOLATION` mid-read.
- Zero new dependencies; CSV schema (ADR-0017's contract) untouched; public
  signatures of `write()`/`_load()` unchanged.

### Negative consequences

- A contended lock can stall a write up to `LK_LOCK`'s ~10 s internal retry
  window before the best-effort path drops the record (still: never crashes,
  never hangs indefinitely).
- The 1 GiB sentinel offset is a ceiling assumption; marked with a
  `# ponytail:` comment — revisit if `run_history.csv` ever approaches it.
- `_load()` now needs write permission on the file (`"r+"`); a read-only
  copy of a history file surfaces as `RunHistoryError` rather than parsing.
- Off-Windows the lock is a no-op — acceptable, as the repo convention and
  all deployments are Windows-only.

## Alternatives considered

1. **`portalocker` / `filelock` dependency.** Rejected: a new dependency for
   what ~25 lines of stdlib do; `filelock` is sidecar-file based (see 3).
2. **Lock byte 0 (a real data byte).** Rejected: a non-cooperating reader
   (someone opening the CSV in Excel or a script) could hit
   `ERROR_LOCK_VIOLATION` mid-read; past-EOF sentinel fails soft instead.
3. **Sidecar lockfile (`run_history.csv.lock`).** Rejected: leaks when a
   process dies mid-hold and then needs stale-lock age heuristics; OS
   byte-range locks are released by the kernel on process death.
4. **Serialize writes through a small local service/daemon.** Rejected:
   massive machinery for an audit log, and a per-machine daemon cannot
   serialize writers on *different* machines sharing an SMB drive — the
   byte-range lock is enforced by the file server itself.
5. **Switch the log to SQLite.** Rejected: changes ADR-0017's CSV contract
   and every existing reader for a problem a 1-byte lock solves.

## Related decisions

- [ADR-0017: CSV-based append-only run history log](0017-run-history-csv-log.md)
  — the schema this preserves.
- [ADR-0050: Unified GUI adapter direction](0050-unified-gui-adapter-direction.md)
  — items 5 and 6, which made this race live and mandated closing it in v1.
