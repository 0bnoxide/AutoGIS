"""Session-wide test defaults.

The CLI adapter writes a RunRecord for every command invocation (ADR-0054).
Hundreds of existing tests drive commands through CliRunner; without this
switch each would litter a real run_history.csv into its working directory.
Tests that exercise the recorder itself point AUTOGIS_RUN_HISTORY at a
tmp_path instead (their own monkeypatch.setenv overrides this autouse one).
"""
import pytest


@pytest.fixture(autouse=True)
def _run_history_off(monkeypatch):
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", "off")
