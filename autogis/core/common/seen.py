"""The single "seen-before" abstraction (reserved).

One concept unifies two idempotency mechanisms currently scattered across the
suite:

* the harvester's checksum/skip-existing decision (``HarvestConfig.skip_existing``),
* envmon's unique-key import idempotency.

This module reserves the interface now; it is fleshed out post-merge (plan
File Structure note). Both call sites will route their "have I processed this
already?" decision through ``SeenIndex`` so the policy lives in one place.
"""
from __future__ import annotations

from typing import Protocol


class SeenIndex(Protocol):
    """Reserved interface for the unified seen-before check.

    Implementations decide whether a key (checksum, unique import key, …) has
    been observed, and record newly observed keys.
    """

    def seen(self, key: str) -> bool:
        ...

    def mark(self, key: str) -> None:
        ...
