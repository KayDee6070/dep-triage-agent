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
from dep_triage.fixture import FixtureNotBuilt, load_fixture

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


@app.command()
def ask(
    question: str = typer.Argument(..., help="A dependency-security question."),
    trace: bool = typer.Option(False, "--trace", help="Show each tool call."),
) -> None:
    """Ask the agent one question, using the local model."""
    # Imported here so `version` and `config` stay usable without the model
    # stack, and without paying its import cost.
    from dep_triage.agent.loop import run_agent
    from dep_triage.tools.wrapper import Toolkit

    settings = Settings()
    try:
        fixture = load_fixture(settings.fixture_path)
    except FixtureNotBuilt as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    result = run_agent(question, Toolkit(fixture), settings)

    if trace:
        for call in result.calls:
            mark = "ok" if call.ok else "ERR"
            typer.echo(f"  [{call.index}] {mark} {call.tool}({call.arguments})", err=True)
        typer.echo(
            f"  {result.steps} calls, {result.duration_s:.1f}s, "
            f"terminated={result.terminated} ({result.stop_reason})",
            err=True,
        )

    typer.echo(result.answer or "(no answer produced)")
    if not result.terminated:
        raise typer.Exit(2)


if __name__ == "__main__":  # pragma: no cover
    app()
