from pathlib import Path

from sqlalchemy import select

from epcot_fw.db.models import Booth, CanonicalLink, MenuItem, MergeConflict
from epcot_fw.pipeline.resolve_pipeline import run_resolve
from epcot_fw.sources.allears import AllEarsAdapter

from ._helpers import ingest

FIXTURES = Path(__file__).parent.parent / "fixtures/html_snapshots"


def test_rerunning_resolve_does_not_duplicate_anything(db_session):
    """Regression test: run_resolve() previously re-created a fresh
    merge_conflicts row every time it revisited a still-unmatched (review or
    no-parent-booth) extracted_record, since those records never get a
    canonical_links row to short-circuit on. Re-running resolve must be a
    true no-op for already-processed input."""
    festival_id = db_session.info["festival_id"]

    html = (FIXTURES / "allears/booth_menus_hub.html").read_text()
    dtos = AllEarsAdapter().parse(html, "https://example.test/allears", "booth_list")
    ingest(db_session, dtos, "allears", festival_id, url="https://example.test/allears")

    def counts():
        return (
            len(db_session.scalars(select(Booth)).all()),
            len(db_session.scalars(select(MenuItem)).all()),
            len(db_session.scalars(select(CanonicalLink)).all()),
            len(db_session.scalars(select(MergeConflict).where(MergeConflict.status == "open")).all()),
        )

    first = counts()
    assert first[3] > 0, "fixture should produce at least one open conflict to make this test meaningful"

    run_resolve(db_session, festival_id=festival_id)
    second = counts()

    run_resolve(db_session, festival_id=festival_id)
    third = counts()

    assert first == second == third
