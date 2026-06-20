from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_group_lists_harvest():
    result = CliRunner().invoke(autogis, ["--help"])
    assert result.exit_code == 0
    assert "harvest" in result.output
