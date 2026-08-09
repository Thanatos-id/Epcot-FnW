import logging

import typer
from rich.console import Console
from rich.table import Table

from epcot_fw.agents.conflict_triage import (
    accept_suggestion,
    reject_suggestion,
    run_conflict_triage,
)
from epcot_fw.db.base import SessionLocal
from epcot_fw.db.models import MergeConflict, Source
from epcot_fw.pipeline.crawl import _current_festival, run_full_crawl
from epcot_fw.pipeline.refresh import run_refresh
from epcot_fw.pipeline.resolve_pipeline import run_resolve

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="Epcot Food & Wine Festival crawler/API CLI")
sources_app = typer.Typer(help="Manage crawl sources")
db_app = typer.Typer(help="Database maintenance")
review_app = typer.Typer(help="Review and triage merge_conflicts", invoke_without_command=True)
app.add_typer(sources_app, name="sources")
app.add_typer(db_app, name="db")
app.add_typer(review_app, name="review")

console = Console()


def _parse_keys(sources: str | None) -> list[str] | None:
    return [s.strip() for s in sources.split(",")] if sources else None


@app.command()
def crawl(
    sources: str = typer.Option(None, "--sources", help="Comma-separated source keys (default: all enabled)"),
    confirm_tos: bool = typer.Option(
        False, "--confirm-tos", help="Confirm you've reviewed each enabled source's ToS/robots.txt"
    ),
) -> None:
    """Full first-time crawl: fetch every seed URL for each enabled source, parse, and resolve."""
    with SessionLocal() as session:
        stats = run_full_crawl(session, source_keys=_parse_keys(sources), confirm_tos=confirm_tos)
    console.print(stats)


@app.command()
def refresh(
    sources: str = typer.Option(None, "--sources", help="Comma-separated source keys (default: all enabled)"),
    triage: bool = typer.Option(True, "--triage/--no-triage", help="Run the conflict-triage agent afterward"),
) -> None:
    """Weekly incremental refresh: re-check known pages + discover new posts, then resolve."""
    with SessionLocal() as session:
        stats = run_refresh(session, source_keys=_parse_keys(sources), run_triage=triage)
    console.print(stats)


@app.command()
def resolve() -> None:
    """Re-run entity resolution over whatever's already staged (no fetching)."""
    with SessionLocal() as session:
        festival = _current_festival(session)
        stats = run_resolve(session, festival_id=festival.id)
        session.commit()
    console.print(stats)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Run the FastAPI app with uvicorn."""
    import uvicorn

    uvicorn.run("epcot_fw.api.main:app", host=host, port=port, reload=reload)


@review_app.callback(invoke_without_command=True)
def review_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    status: str = typer.Option(
        "open,suggested", "--status", help="Comma-separated statuses to show"
    ),
) -> None:
    """List merge_conflicts (default: open + agent-suggested) for review.

    Run bare (`epcot-fw review`) for this listing; use the `triage`,
    `accept`, and `reject` subcommands to act on what it shows.
    """
    if ctx.invoked_subcommand is not None:
        return

    statuses = [s.strip() for s in status.split(",") if s.strip()]
    with SessionLocal() as session:
        conflicts = (
            session.query(MergeConflict)
            .filter(MergeConflict.status.in_(statuses))
            .order_by(MergeConflict.opened_at.desc())
            .limit(limit)
            .all()
        )
        table = Table("ID", "Status", "Entity", "Canonical ID", "Field", "Candidates", "Agent suggestion")
        for c in conflicts:
            suggestion = ""
            if c.resolution_value and c.resolution_value.get("decided_by") == "agent":
                suggestion = (
                    f"{c.resolution_value.get('decision')} "
                    f"(conf {c.resolution_value.get('confidence', 0):.2f}): "
                    f"{c.resolution_value.get('rationale', '')}"
                )
            table.add_row(
                str(c.id),
                c.status,
                c.entity_type,
                str(c.canonical_id) if c.canonical_id else "-",
                c.field_name or "(match)",
                str(c.candidate_values)[:60],
                suggestion[:80],
            )
        console.print(table)
        console.print(f"{len(conflicts)} conflict(s) shown ({', '.join(statuses)})")


@review_app.command("triage")
def review_triage(limit: int = typer.Option(None, "--limit", help="Cap how many open conflicts to examine")) -> None:
    """Run the conflict-triage agent over every open merge_conflicts row.

    High-confidence field-value disagreements are resolved automatically;
    everything else the agent has an opinion on is left as status=suggested
    with a rationale, for `epcot-fw review accept/reject` to act on.
    """
    with SessionLocal() as session:
        stats = run_conflict_triage(session, limit=limit)
        session.commit()
    console.print(stats)


@review_app.command("accept")
def review_accept(conflict_id: int) -> None:
    """Apply a status=suggested conflict's agent recommendation for real."""
    with SessionLocal() as session:
        conflict = session.get(MergeConflict, conflict_id)
        if conflict is None:
            raise typer.BadParameter(f"no such conflict: {conflict_id}")
        festival = _current_festival(session)
        accept_suggestion(session, conflict, festival_id=festival.id)
        session.commit()
    console.print(f"accepted conflict {conflict_id}")


@review_app.command("reject")
def review_reject(conflict_id: int) -> None:
    """Dismiss a status=suggested conflict's agent recommendation."""
    with SessionLocal() as session:
        conflict = session.get(MergeConflict, conflict_id)
        if conflict is None:
            raise typer.BadParameter(f"no such conflict: {conflict_id}")
        reject_suggestion(conflict)
        session.commit()
    console.print(f"dismissed conflict {conflict_id}")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply Alembic migrations (equivalent to `alembic upgrade head`)."""
    import subprocess

    subprocess.run(["alembic", "upgrade", "head"], check=True)


@db_app.command("seed")
def db_seed() -> None:
    """Seed sources, dietary tags, and the current festival row."""
    from epcot_fw.db.seed import seed

    seed()
    console.print("Seed complete.")


@sources_app.command("list")
def sources_list() -> None:
    with SessionLocal() as session:
        rows = session.query(Source).order_by(Source.priority_rank).all()
        table = Table("Key", "Priority", "Enabled", "Base URL")
        for r in rows:
            table.add_row(r.key, str(r.priority_rank), "yes" if r.enabled else "no", r.base_url)
        console.print(table)


@sources_app.command("enable")
def sources_enable(key: str) -> None:
    with SessionLocal() as session:
        row = session.query(Source).filter_by(key=key).first()
        if row is None:
            raise typer.BadParameter(f"unknown source key: {key}")
        row.enabled = True
        session.commit()
    console.print(f"enabled {key}")


@sources_app.command("disable")
def sources_disable(key: str) -> None:
    with SessionLocal() as session:
        row = session.query(Source).filter_by(key=key).first()
        if row is None:
            raise typer.BadParameter(f"unknown source key: {key}")
        row.enabled = False
        session.commit()
    console.print(f"disabled {key}")


if __name__ == "__main__":
    app()
