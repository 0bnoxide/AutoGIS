"""``python -m autogis`` — same CLI as the ``autogis`` console script.

Exists for uninstalled checkouts (worktree QA via PYTHONPATH + ArcGIS Pro's
propy.bat), where the console scripts don't.
"""
from autogis.adapters.cli import autogis

if __name__ == "__main__":
    autogis()
