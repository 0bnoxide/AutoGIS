"""Guard against ADR-number collisions (docs/adr/NNNN-*.md).

Parallel branches have repeatedly grabbed the same "next" ADR number
(0034, 0061/0062, ...) because git doesn't flag a duplicate when the
filenames differ. This test fails the suite if two real ADR files share a
numeric prefix. `XXXX-*.md` placeholders (real number assigned at merge —
see docs/adr/README.md) are intentionally ignored.
"""
import re
from collections import defaultdict
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
# ponytail: \d{4} also matches a bare year (e.g. "2026-..."); only a concern
# if a date-named file is ever dropped directly in docs/adr/ (logs/ is a
# separate, non-recursive-glob-safe subdir). Tighten if that ever happens.
NUMBERED = re.compile(r"^(\d{4})-.+\.md$")


def test_no_duplicate_adr_numbers():
    by_number = defaultdict(list)
    for path in ADR_DIR.glob("*.md"):
        match = NUMBERED.match(path.name)
        if match:
            by_number[match.group(1)].append(path.name)

    dupes = {num: names for num, names in by_number.items() if len(names) > 1}
    assert not dupes, f"Duplicate ADR numbers found: {dupes}"
