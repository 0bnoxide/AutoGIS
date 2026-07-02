"""The single "seen-before" abstraction.

One concept unifies two idempotency mechanisms across the suite:

* the harvester's checksum/skip-existing decision (``HarvestConfig.skip_existing``),
* envmon's unique-key import idempotency.

Both call sites can route their "have I processed this already?" decision
through a ``SeenIndex`` so the policy lives in one place.

Not currently wired into either call site: the harvester's
skip_existing/incremental paths use ``manifest.py``/``state.py`` instead, and
no envmon module imports this. Future-use abstraction, not dead code -- keep
it until one of the two call sites is migrated to it, or it is deliberately
removed.
"""
from __future__ import annotations

import os
from typing import Iterable, Protocol, runtime_checkable


@runtime_checkable
class SeenIndex(Protocol):
    """Interface for the unified seen-before check.

    Implementations decide whether a key (checksum, unique import key, …) has
    been observed, and record newly observed keys.
    """

    def seen(self, key: str) -> bool:
        ...

    def mark(self, key: str) -> None:
        ...


class SetSeenIndex:
    """In-memory seen-before index backed by a Python set.

    Suitable for batch operations within a single process run.  Pre-populate
    ``initial`` to seed the index from an existing collection of keys
    (e.g. keys already present in a database table).
    """

    def __init__(self, initial: Iterable[str] = ()) -> None:
        self._seen: set[str] = set(initial)

    def seen(self, key: str) -> bool:
        return key in self._seen

    def mark(self, key: str) -> None:
        self._seen.add(key)

    def __len__(self) -> int:
        return len(self._seen)


class FilesystemSeenIndex:
    """Seen-before index that treats filesystem path existence as the signal.

    ``seen(path)`` returns ``True`` when the path already exists on disk.
    ``mark(path)`` is a no-op because the file's presence on disk is the
    durable record — the caller is responsible for writing the file.
    """

    def seen(self, key: str) -> bool:
        return os.path.exists(key)

    def mark(self, key: str) -> None:
        pass
