import os
import subprocess
import sys

from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_group_lists_harvest():
    result = CliRunner().invoke(autogis, ["--help"])
    assert result.exit_code == 0
    assert "harvest" in result.output


def test_main_reconfigures_cp1252_output_before_click():
    code = """
import click
from autogis.adapters import cli

@cli.autogis.command("_unicode-smoke")
def unicode_smoke():
    click.echo("\\N{RIGHTWARDS ARROW}")
    click.echo("\\N{RIGHTWARDS ARROW}", err=True)

cli.main()
"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, "-c", code, "_unicode-smoke"],
        capture_output=True, env=env)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.decode("utf-8").strip() == "\N{RIGHTWARDS ARROW}"
    assert result.stderr.decode("utf-8").strip() == "\N{RIGHTWARDS ARROW}"
