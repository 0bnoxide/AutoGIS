import os
import sys

# The coordination module lives under .claude/ (session tooling), not in the
# autogis package, so add it to sys.path for import.
_COORD = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".claude", "coordination")
)
if _COORD not in sys.path:
    sys.path.insert(0, _COORD)
