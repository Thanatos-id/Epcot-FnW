import logging
from pathlib import Path

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
from epcot_fw.pipeline.photo_workflow import DEFAULT_PUBLISH_DIR
from epcot_fw.pipeline.refresh import run_refresh
from epcot_fw.pipeline.resolve_pipeline import run_resolve

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="Epcot Food & Wine Festival crawler/API CLI")
sources_app = typer.Typer(help="Manage crawl sources")
db_app = typer.Typer(help="Database maintenance")
review_app = typer.Typer(help="Review and triage merge_conflicts", invoke_without_command=True)
images_app = typer.Typer(help="Round-trip dish photos for external (e.g. AI) processing")
studio_app = typer.Typer(help="Apply changesets exported by docs/studio.html")
app.add_typer(sources_app, name="sources")
app.add_typer(db_app, name="db")
app.add_typer(review_app, name="review")
app.add_typer(images_app, name="images")
app.add_typer(studio_app, name="studio")

# The site this project's own docs/ is published at. Used only as the
# default publish target for `epcot-fw images import` - override with
# --base-url for a fork, a different Pages project, or once these move to a
# dedicated image host.
DEFAULT_PAGES_BASE_URL = "https://thanatos-id.github.io/Epcot-FnW"

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


@app.command("backfill-images")
def backfill_images(
    years: int = typer.Option(
        5, "--years", help="How many prior seasons to search, counting back from the current festival"
    ),
    confirm_tos: bool = typer.Option(
        False, "--confirm-tos", help="Confirm you've reviewed disneyfoodblog.com's ToS/robots.txt"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report matches without writing data/manual/menu_items.json"
    ),
) -> None:
    """Find photos of this year's dishes in prior seasons of Disney Food
    Blog's per-booth photo posts.

    Menu-item photos only - never a booth or location photo - and only ever
    attached to a dish that is already on this year's active menu. A caption
    whose booth or dish doesn't confidently match something on the current
    menu is reported, not guessed at. Fetches up to ~33 booths' worth of
    pages per season searched, so --dry-run first is worth it before running
    across all 5.
    """
    if not confirm_tos:
        raise typer.BadParameter(
            "Pass --confirm-tos once you've reviewed disneyfoodblog.com's terms of service / "
            "robots.txt - this fetches several seasons' worth of its pages in one run."
        )

    from epcot_fw.pipeline.image_backfill import backfill_dish_images

    with SessionLocal() as session:
        report = backfill_dish_images(session, years=years, dry_run=dry_run)

    console.print(f"scanned {len(report.years_scanned)} season(s): {report.years_scanned}")
    console.print(
        f"fetched {report.photo_posts_fetched} photo post(s), "
        f"found {report.captions_found} captioned photo(s)"
    )
    outcome = f"{len(report.matched)} confident match(es)"
    outcome += " (dry run - nothing written)" if dry_run else " written to data/manual/menu_items.json"
    console.print(outcome)
    if report.skipped_already_pictured:
        console.print(f"{len(report.skipped_already_pictured)} skipped - dish already has a photo")
    if report.skipped_no_item_match:
        console.print(f"{len(report.skipped_no_item_match)} caption(s) matched no current dish")
    if report.skipped_no_booth_match:
        console.print(f"{len(report.skipped_no_booth_match)} caption(s) came from a booth not on this year's menu")

    if not dry_run and report.matched:
        console.print("Run [bold]epcot-fw manual[/bold] to apply these to the database.")


@images_app.command("promote")
def images_promote(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would change and write nothing"),
) -> None:
    """Let this season's photo of a dish beat last season's stand-in.

    `backfill-images` stages historical photos into the curated file at
    priority_rank 0, which outranks every later observation permanently.
    That is free while the current season has no photos of its own, and
    stops being free the moment it does: a dish shows a 2025 plate while an
    actual photo of what is being served today sits underneath it.

    Only clears a curated photo when a crawled current-season one is
    available to replace it. A photo published from docs/studio.html is left
    alone whatever the crawl finds - that is an answer, not a stand-in.
    """
    from epcot_fw.pipeline.photo_promotion import promote_current_season_photos

    with SessionLocal() as session:
        report = promote_current_season_photos(session, dry_run=dry_run)
        if not dry_run:
            session.commit()

    verb = "would promote" if dry_run else "promoted"
    console.print(f"{verb} {report.total} dish photo(s) to this season's")
    for p in report.promotions:
        console.print(f"  [bold]{p.booth_name}[/bold] / {p.dish_name}")
        console.print(f"    was {p.was.rsplit('/', 1)[-1][:72]}")
        console.print(f"    now {p.now.rsplit('/', 1)[-1][:72]}")
    if report.kept_hand_attached:
        console.print(
            f"{len(report.kept_hand_attached)} hand-attached photo(s) left alone"
        )
    if dry_run and report.total:
        console.print("Nothing was written. Drop --dry-run to apply.")


@images_app.command("export")
def images_export(
    out_dir: Path = typer.Argument(Path("dish-photos"), help="Directory to write photos + a manifest into"),
) -> None:
    """Download every active dish's current photo into out_dir, named by its
    stable public_id, plus a manifest.json for `images import` to read back.

    Meant for running the whole folder through an external processing step
    (an AI pass for a consistent look, a manual crop, whatever) and bringing
    the results back with `images import` - nothing here cares what happens
    to the files in between, only that the filenames keep their public_id.
    """
    from epcot_fw.pipeline.photo_workflow import export_dish_photos

    with SessionLocal() as session:
        report = export_dish_photos(session, out_dir)

    console.print(f"exported {report.downloaded} of {report.total} photo(s) to {out_dir}/")
    if report.failed:
        console.print(f"[yellow]{len(report.failed)} failed to download[/yellow] - see manifest.json")
    if report.total == 0:
        console.print(
            "No active dish has a photo yet - run `epcot-fw backfill-images` "
            "or add one through the editor first."
        )


@images_app.command("import")
def images_import(
    in_dir: Path = typer.Argument(..., help="Directory of processed photos + the manifest.json from `images export`"),
    base_url: str = typer.Option(
        DEFAULT_PAGES_BASE_URL, "--base-url", help="Public base URL the published photos will be served from"
    ),
    publish_dir: Path = typer.Option(
        DEFAULT_PUBLISH_DIR, "--publish-dir", help="Where to copy processed photos for Pages to serve"
    ),
) -> None:
    """Publish processed photos from in_dir and stage their URLs as curated
    overrides, matching each file to a dish by the public_id in its name.

    Overwrites whatever image_url a dish currently has, staged or applied -
    unlike `backfill-images`, running this command is a deliberate decision
    to set these specific dishes' photos to what's in this folder. Copies
    files into publish_dir (docs/ by default, so a normal commit + push
    publishes them via GitHub Pages); nothing here uploads anywhere on its
    own.
    """
    from epcot_fw.pipeline.photo_workflow import import_dish_photos

    report = import_dish_photos(in_dir, publish_dir=publish_dir, base_url=base_url)

    console.print(f"published {len(report.published)} photo(s) to {publish_dir}/")
    if report.missing:
        console.print(
            f"[yellow]{len(report.missing)} listed in the manifest have no processed file in {in_dir}[/yellow]"
        )
    if report.published:
        console.print(
            "Run [bold]epcot-fw manual[/bold] to apply these, then commit + push "
            f"{publish_dir}/ and data/manual/menu_items.json to publish them."
        )


@studio_app.command("apply")
def studio_apply(
    changeset: Path = typer.Argument(..., help="The .json file docs/studio.html downloaded"),
    base_url: str = typer.Option(
        DEFAULT_PAGES_BASE_URL, "--base-url", help="Public base URL the published photos will be served from"
    ),
    publish_dir: Path = typer.Option(
        DEFAULT_PUBLISH_DIR, "--publish-dir", help="Where to write attached photos for Pages to serve"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would change and write nothing"),
) -> None:
    """Apply a changeset exported by the studio: publish its photos, merge
    its corrections into the curated files, and re-resolve.

    Everything in the file lands under the `manual` source at priority_rank
    0, so it beats every crawled source and survives the next refresh.
    Dishes and booths marked as added by hand come back with
    `origin = 'curated'`, which is what stops reconciliation retiring them
    for having no crawled page behind them.

    Copies photos into publish_dir (docs/ by default, so a normal commit +
    push publishes them via GitHub Pages); nothing here uploads anywhere on
    its own.
    """
    from epcot_fw.pipeline.manual import stage_manual_overrides
    from epcot_fw.pipeline.studio import ChangesetError, apply_changeset

    try:
        report = apply_changeset(
            changeset, publish_dir=publish_dir, base_url=base_url, dry_run=dry_run
        )
    except ChangesetError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    verb = "would change" if dry_run else "changed"
    console.print(
        f"{verb} {len(report.menu_items)} dish(es) and {len(report.booths)} booth(s); "
        f"{len(report.photos)} photo(s) {'would go' if dry_run else 'published'} to {publish_dir}/"
    )
    if report.added:
        console.print(f"added by hand: {len(report.added)} — {', '.join(report.added[:5])}")
    if report.deleted:
        console.print(f"marked deleted: {len(report.deleted)} — {', '.join(report.deleted[:5])}")
    for note in report.skipped:
        console.print(f"[yellow]skipped[/yellow] {note}")

    if dry_run:
        console.print("Nothing was written. Drop --dry-run to apply.")
        return
    if not report.total:
        console.print("Nothing to apply.")
        return

    with SessionLocal() as session:
        staged = stage_manual_overrides(session)
        festival = _current_festival(session)
        stats = run_resolve(session, festival_id=festival.id)
        session.commit()
    console.print(f"staged {staged} curated override(s)")
    console.print(stats)
    if report.photos:
        console.print(
            f"Commit + push {publish_dir}/ and data/manual/ to publish the new photos."
        )


@app.command("ingest")
def ingest(
    url: str = typer.Argument(..., help="One page to fetch and read, e.g. a DFB review permalink"),
    page_kind: str = typer.Option(
        None, "--page-kind", help="Override what kind of page it is (booth_review, booth_detail, booth_list)"
    ),
) -> None:
    """Fetch and ingest a single page you found yourself.

    The crawl keeps up with a site; it does not reach backwards. Disney Food
    Blog's festival feed holds about ten entries, so a review published
    before the crawler learned to read that shape cannot be reached by
    re-running anything. This takes one URL through exactly the same
    fetch/cache/parse/resolve path a crawled page takes.

    The page kind is inferred from the URL where the source can tell.
    """
    from epcot_fw.pipeline.ingest_url import IngestError, ingest_one_url

    try:
        with SessionLocal() as session:
            stats = ingest_one_url(session, url, page_kind=page_kind)
            session.commit()
    except IngestError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"read as [bold]{stats['page_kind']}[/bold] from {stats['source']}")
    if not stats["pages_fetched"]:
        console.print("[yellow]nothing fetched[/yellow] - see the log above")
        return
    if not stats["pages_changed"]:
        console.print("already had this page, unchanged - nothing reparsed")
        return
    console.print(f"extracted {stats['records_extracted']} record(s)")
    console.print(stats)


@app.command("backfill-reviews")
def backfill_reviews_cmd(
    max_pages: int = typer.Option(
        1, "--max-pages", help="How many archive pages to walk (page 1 reaches back before opening day)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would be fetched, fetch nothing"),
) -> None:
    """Sweep this season's Disney Food Blog reviews for dish photos.

    The daily refresh reads the festival tag's feed, which holds about ten
    entries - four days at festival pace. That keeps a running crawl current
    and cannot reach backwards, so reviews published before the crawler
    learned to read that shape are simply missing. This walks the tag's HTML
    archive instead, which carries thirty-odd posts a page.

    Pages already held are not refetched, and the sweep stops early once
    fetches start failing: DFB answers a burst with 429, and the right
    response to being asked to slow down is to stop.
    """
    from epcot_fw.pipeline.review_backfill import backfill_reviews

    with SessionLocal() as session:
        report = backfill_reviews(session, max_pages=max_pages, dry_run=dry_run)
        if not dry_run:
            session.commit()

    console.print(
        f"found {report.discovered} review post(s) for this season; "
        f"{report.already_cached} already held"
    )
    if dry_run:
        for url in report.ingested:
            console.print(f"  would fetch {url}")
        console.print("Nothing was fetched. Drop --dry-run to run it.")
        return

    console.print(f"fetched {report.fetched}, extracted {report.records} record(s)")
    if report.errors:
        console.print(f"[yellow]{report.errors} fetch(es) failed[/yellow]")
    if report.stopped_early:
        console.print("[yellow]stopped early - the site was returning errors[/yellow]")
    if report.records:
        console.print(
            "Run [bold]epcot-fw images promote[/bold] to let this season's photos "
            "beat any historical stand-ins."
        )


@app.command("manual")
def manual_apply() -> None:
    """Apply hand-curated booth facts (coordinates, location notes) from
    data/manual/booth_locations.json and re-resolve.

    Runs automatically as part of crawl/refresh; use this to pick up an edit
    without waiting for the next crawl. Re-running with an unchanged file is
    a no-op.
    """
    from epcot_fw.pipeline.manual import stage_manual_overrides

    with SessionLocal() as session:
        staged = stage_manual_overrides(session)
        festival = _current_festival(session)
        stats = run_resolve(session, festival_id=festival.id)
        session.commit()
    console.print(f"staged {staged} curated override(s)")
    console.print(stats)


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


@sources_app.command("reparse")
def sources_reparse(
    sources: str = typer.Option(
        None, "--sources", help="Comma-separated source keys to reparse (default: every enabled source)"
    ),
) -> None:
    """Reparse already-cached pages with today's parser code, without
    refetching anything.

    Fixes the case where a parser bug got fixed in code but the pages it
    misparsed haven't changed since, so a normal crawl/refresh's change
    detection skips them and the bad data just sits there. No network
    access happens here, so no --confirm-tos is needed.
    """
    from epcot_fw.pipeline.reparse import run_reparse

    with SessionLocal() as session:
        totals = run_reparse(session, source_keys=_parse_keys(sources))

    console.print(
        f"reparsed {totals['pages_reparsed']} page(s), {totals['records_extracted']} record(s) extracted"
    )
    console.print(
        f"{totals['records_relinked']} reconnected directly to their existing dish/booth; "
        f"{totals['canonical_upserts']} more resolved fresh"
    )
    if totals["errors"]:
        console.print(f"[yellow]{totals['errors']} page(s) failed to reparse[/yellow]")
    if totals["open_conflicts"]:
        console.print(f"{totals['open_conflicts']} open conflict(s) - run `epcot-fw review`")


if __name__ == "__main__":
    app()
