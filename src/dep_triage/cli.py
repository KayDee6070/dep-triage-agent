"""Command-line entry point.

Only commands that actually work live here. ``ask``, ``eval`` and ``report``
arrive at M2, M3 and M3 respectively; stubs that raise would be worse than
their absence, because ``--help`` would advertise an interface that does
nothing.
"""

from __future__ import annotations

import json

import typer

from dep_triage import __version__
from dep_triage.config import Settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Dependency security triage agent, and the harness that measures it.",
)


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command()
def config() -> None:
    """Print resolved configuration as JSON, with secrets redacted.

    Useful for checking what a container actually resolved at startup, which is
    otherwise guesswork once this is deployed.
    """
    settings = Settings()
    typer.echo(json.dumps(settings.redacted_dump(), indent=2, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    app()
