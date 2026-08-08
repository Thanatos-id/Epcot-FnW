import logging

import typer
from rich.console import Console
from rich.table import Table

from epcot_fw.db.base import SessionLocal
from epcot_fw.db.models import MergeConflict, Source
from epcot_fw.pipeline.crawl import _current_festival, run_full_crawl
from epcot_fw.pipeline.refresh import run_refresh
from epcot_fw.pipeline.resolve_pipeline import run_resolve

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="Epcot Food & Wine Festival crawler/API CLI")
sources_app = typer.Typer(help="Manage crawl sources")
db_app = typer.Typer(help="Database maintenance")
app.add_typer(sources_app, name="sources")
app.add_typer(db_app, name="db")

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
) -> None:
    """Weekly incremental refresh: re-check known pages + discover new posts, then resolve."""
    with SessionLocal() as session:
        stats = run_refresh(session, source_keys=_parse_keys(sources))
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


@app.command()
def review(limit: int = typer.Option(50, "--limit")) -> None:
    """List open merge_conflicts for manual review."""
    with SessionLocal() as session:
        conflicts = (
            session.query(MergeConflict)
            .filter_by(status="open")
            .order_by(MergeConflict.opened_at.desc())
            .limit(limit)
            .all()
        )
        table = Table("ID", "Entity", "Canonical ID", "Field", "Candidates")
        for c in conflicts:
            table.add_row(
                str(c.id),
                c.entity_type,
                str(c.canonical_id) if c.canonical_id else "-",
                c.field_name or "(match)",
                str(c.candidate_values)[:80],
            )
        console.print(table)
        console.print(f"{len(conflicts)} open conflict(s) shown")


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
