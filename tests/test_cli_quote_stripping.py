"""RecordingCommand strips literal quotes from argv values.

Windows "Copy as path" pastes '"C:\\...\\x.gdb"' and a trailing backslash
escapes the closing quote in PowerShell, so quoted paths reach click as
literal-quote strings. Every leaf command under the ``autogis`` root is a
RecordingCommand (Group.command_class cascade), so stripping there covers
the whole CLI -- including click.Path(exists=True) validation, which runs
after parse_args (2026-07-10: CreateFileGDB crashed on a quote-prefixed
folder).
"""
import click
from click.testing import CliRunner

from autogis.adapters.cli import RecordingCommand


def _toy_command():
    @click.command(cls=RecordingCommand)
    @click.option("--gdb")
    @click.argument("csv", type=click.Path(exists=True))
    def cmd(gdb, csv):
        click.echo(f"{gdb}|{csv}")
    return cmd


def test_surrounding_quotes_stripped_before_path_validation(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text("x\n", encoding="utf-8")
    result = CliRunner().invoke(
        _toy_command(), [f'"{p}"', "--gdb", f'"{tmp_path}\\x.gdb"'])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"{tmp_path}\\x.gdb|{p}"


def test_lone_trailing_quote_stripped(tmp_path):
    # PowerShell: --gdb "C:\x\" -> value 'C:\x"'
    p = tmp_path / "in.csv"
    p.write_text("x\n", encoding="utf-8")
    result = CliRunner().invoke(
        _toy_command(), [str(p), "--gdb", 'C:\\x\\y.gdb"'])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"C:\\x\\y.gdb|{p}"


def test_unquoted_values_pass_through_unchanged(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text("x\n", encoding="utf-8")
    result = CliRunner().invoke(_toy_command(), [str(p), "--gdb", "plain"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"plain|{p}"


def test_sql_where_clause_with_interior_quotes_untouched(tmp_path):
    # FGDB SQL delimits field names with double quotes; a --where value like
    # '"EditDate" > DATE ...' must NOT be stripped (interior quote present).
    p = tmp_path / "in.csv"
    p.write_text("x\n", encoding="utf-8")
    where = '"EditDate" > DATE \'2026-01-01\''
    result = CliRunner().invoke(_toy_command(), [str(p), "--gdb", where])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"{where}|{p}"
