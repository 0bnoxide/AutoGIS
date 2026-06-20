import click

from autogis.adapters.config_loader import load_config
from autogis.core.harvest.gis_session import build_gis_from_env
from autogis.core.harvest.harvester import harvest


def run(config_path, where, out, incremental, *, gis_builder, harvest_fn, load_fn):
    overrides = {"where": where, "directory": out, "incremental": incremental}
    config, profile = load_fn(config_path, overrides=overrides)
    gis = gis_builder(profile)
    summary = harvest_fn(gis, config)
    click.echo(
        f"Downloaded: {summary.downloaded}  "
        f"Skipped: {summary.skipped}  Failed: {summary.failed}")
    return summary


@click.group()
def autogis():
    """AutoGIS suite — harvest + envmon tools."""


@autogis.command("harvest")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("--where", default=None)
@click.option("--out", default=None)
@click.option("--incremental/--no-incremental", default=None)
def harvest_cmd(config_path, where, out, incremental):
    run(config_path, where, out, incremental,
        gis_builder=build_gis_from_env, harvest_fn=harvest, load_fn=load_config)


# Legacy single-command entry point kept as an alias.
main = autogis


if __name__ == "__main__":
    autogis()
