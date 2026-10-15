"""Command-line entry point.

Only commands that actually work live here. ``ask``, ``eval`` and ``report``
arrive at M2, M3 and M3 respectively; stubs that raise would be worse than
their absence, because ``--help`` would advertise an interface that does
nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from dep_triage import __version__
from dep_triage.config import Settings
from dep_triage.fixture import FixtureNotBuilt, load_fixture

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Dependency security triage agent, and the harness that measures it.",
)


class EvalSplit(StrEnum):
    dev = "dev"
    held_out = "held_out"


class EvalSystem(StrEnum):
    agent = "agent"
    no_agent = "no_agent"
    always_lookup = "always_lookup"
    all = "all"


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


@app.command("eval")
def evaluate(
    split: Annotated[
        EvalSplit, typer.Option(help="Declared split; exposed probes are excluded.")
    ] = EvalSplit.dev,
    system: Annotated[
        EvalSystem, typer.Option(help="System, or all for paired comparisons.")
    ] = EvalSystem.agent,
    faults: bool = typer.Option(
        False, "--faults", help="Run the error/empty/malformed fault suite."
    ),
    tasks: Annotated[Path, typer.Option(help="Frozen task file.")] = Path("data/tasks.json"),
    output: Annotated[
        Path | None, typer.Option(help="New JSON path (default: results/<unique-run>.json).")
    ] = None,
    confirm_held_out_once: bool = typer.Option(
        False, "--confirm-held-out-once", help="Consume the final held-out run reservation."
    ),
) -> None:
    """Evaluate frozen tasks; emit metrics, full traces, and per-task checkpoints."""
    from typing import cast

    from dep_triage.eval.artifacts import evaluate_to_file
    from dep_triage.eval.suite import SYSTEMS, SystemName

    systems = list(SYSTEMS) if system is EvalSystem.all else [cast(SystemName, system.value)]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = (
        output
        or Path("results")
        / f"{split.value}-{system.value}-{'faults' if faults else 'clean'}-{stamp}.json"
    )
    try:
        report = evaluate_to_file(
            settings=Settings(),
            tasks_path=tasks,
            output=destination,
            split=split.value,
            systems=systems,
            faults=faults,
            confirm_held_out=confirm_held_out_once,
            progress=True,
        )
    except (ValueError, OSError, FixtureNotBuilt) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Wrote {destination} ({len(report['records'])} executions)")


@app.command()
def report(
    clean: Annotated[
        Path | None, typer.Option(help="Clean evaluation run file (default: newest known).")
    ] = None,
    faults: Annotated[Path | None, typer.Option(help="Fault-arm run file.")] = None,
    output: Annotated[Path, typer.Option(help="Where to write the HTML.")] = Path(
        "results/report.html"
    ),
) -> None:
    """Render the static evaluation report from committed run artifacts."""
    from dep_triage.service.app import build_report_html
    from dep_triage.service.report import render_from_paths

    html = (
        render_from_paths(clean, faults)
        if clean is not None
        else build_report_html(Settings(report_path=Path("/nonexistent")))
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    typer.echo(f"Wrote {output} ({len(html):,} bytes)")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "0.0.0.0",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
) -> None:
    """Run the service: static report, live agent, health and metrics.

    Binds all interfaces by default because the only intended use is inside a
    container, where binding loopback would make the service unreachable.
    """
    import uvicorn

    uvicorn.run(
        "dep_triage.service.app:app_factory",
        factory=True,
        host=host,
        port=port,
        access_log=False,  # structlog already records each request outcome
    )


if __name__ == "__main__":  # pragma: no cover
    app()
