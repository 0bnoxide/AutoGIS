import click

from autogis.adapters.config_loader import load_config
from autogis.core.gis_session import build_gis_from_env
from autogis.core.harvester import harvest


def run(config_path, where, out, incremental, *,
        gis_builder, harvest_fn, load_fn):
    overrides = {"where": where, "directory": out, "incremental": incremental}
    config, profile = load_fn(config_path, overrides=overrides)
    gis = gis_builder(profile)
    summary = harvest_fn(gis, config)
    click.echo(
        f"Downloaded: {summary.downloaded}  "
        f"Skipped: {summary.skipped}  Failed: {summary.failed}")
    return summary


@click.command()
@click.option("--config", "config_path", required=True,
              type=click.Path(exists=True), help="Path to harvest job YAML.")
@click.option("--where", default=None, help="Override the attribute where clause.")
@click.option("--out", default=None, help="Override the output directory.")
@click.option("--incremental/--no-incremental", default=None,
              help="Override incremental mode.")
def main(config_path, where, out, incremental):
    run(config_path, where, out, incremental,
        gis_builder=build_gis_from_env,
        harvest_fn=harvest,
        load_fn=load_config)


if __name__ == "__main__":
    main()
