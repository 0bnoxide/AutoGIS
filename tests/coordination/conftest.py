import os
import sys

# The coordination module lives under .claude/ (session tooling), not in the
# autogis package, so add it to sys.path for import.
_COORD = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".claude", "coordination")
)
if _COORD not in sys.path:
    sys.path.insert(0, _COORD)

# coord_cli's ADR scan imports the new-adr skill's scanner from the tree it is
# scanning; the #425 tests point that tree at a fixture, so make the real
# scanner importable independently of it.
_NEW_ADR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..",
                 ".claude", "skills", "new-adr")
)
if _NEW_ADR not in sys.path:
    sys.path.insert(0, _NEW_ADR)
