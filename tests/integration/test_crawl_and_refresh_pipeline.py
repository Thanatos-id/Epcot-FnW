"""Exercises pipeline/crawl.py's run_full_crawl and pipeline/refresh.py's
run_refresh end-to-end: real orchestration code (stats aggregation, CrawlRun
bookkeeping, per-URL error containment) driven against a *fake* SourceAdapter
registered into SOURCE_REGISTRY for the duration of each test, with all HTTP
traffic (including robots.txt) intercepted by respx.

These functions call session.commit() internally, which the shared db_session
fixture in conftest.py isn't built to survive (it isolates each test with a
single outer transaction + rollback, and an internal commit would prematurely
commit that transaction to the real test database). So this file uses its own
fixture that binds the ORM Session to the connection's transaction in
"create_savepoint" join mode: application-level commit()s only release/reopen
a SAVEPOINT, and the real outer transaction is always rolled back at teardown
regardless of what the code under test committed.
"""

import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from epcot_fw.db.models import Booth, CrawlRun, Festival, RawPage, Source
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline.crawl import run_full_crawl
from epcot_fw.pipeline.refresh import run_refresh
from epcot_fw.sources.base import SeedUrl, SourceAdapter


class StubOkAdapter(SourceAdapter):
    key = "stub_ok"
    priority_rank = 1

    def seed_urls(self, festival_year):
        return [SeedUrl(url="https://stub-ok.test/booths", page_kind="booth_list")]

    def parse(self, raw_html, url, page_kind):
        return [
            ExtractedRecordDTO(entity_type="booth", natural_key_hint=normalize_name("Stub Booth"), payload={"name": "Stub Booth"})
        ]


class StubFlakyAdapter(SourceAdapter):
    """One seed URL that succeeds, one that robots.txt disallows - exercises
    that a single disallowed/failing URL doesn't stop the rest of the crawl."""

    key = "stub_flaky"
    priority_rank = 2

    def seed_urls(self, festival_year):
        return [
            SeedUrl(url="https://stub-flaky.test/ok", page_kind="booth_list"),
            SeedUrl(url="https://stub-flaky.test/down", page_kind="booth_list"),
        ]

    def parse(self, raw_html, url, page_kind):
        return [
            ExtractedRecordDTO(entity_type="booth", natural_key_hint=normalize_name("Flaky Booth"), payload={"name": "Flaky Booth"})
        ]


@pytest.fixture()
def savepoint_session(engine):
    """Like conftest's db_session, but tolerant of session.commit() calls
    made by the code under test - see module docstring."""
    connection = engine.connect()
    trans = connection.begin()
    session = Session(
        bind=connection, future=True, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    session.add_all(
        [
            Source(
                key="stub_ok",
                display_name="Stub Ok",
                base_url="https://stub-ok.test",
                priority_rank=1,
                enabled=True,
                crawl_delay_sec=0,
            ),
            Source(
                key="stub_flaky",
                display_name="Stub Flaky",
                base_url="https://stub-flaky.test",
                priority_rank=2,
                enabled=True,
                crawl_delay_sec=0,
            ),
        ]
    )
    festival = Festival(
        year=2026,
        name="EPCOT International Food & Wine Festival 2026",
        slug="epcot-food-wine-2026",
        status="upcoming",
    )
    session.add(festival)
    session.flush()
    session.info["festival_id"] = festival.id

    yield session

    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture()
def stub_registry(monkeypatch):
    import epcot_fw.pipeline.crawl as crawl_module
    import epcot_fw.pipeline.refresh as refresh_module

    registry = {"stub_ok": StubOkAdapter(), "stub_flaky": StubFlakyAdapter()}
    monkeypatch.setattr(crawl_module, "SOURCE_REGISTRY", registry)
    monkeypatch.setattr(refresh_module, "SOURCE_REGISTRY", registry)
    return registry


def _mock_common_routes(mock: respx.MockRouter) -> None:
    mock.get("https://stub-ok.test/robots.txt").mock(return_value=httpx.Response(404))
    mock.get("https://stub-flaky.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /down\n")
    )


def test_run_full_crawl_aggregates_stats_and_isolates_per_url_failures(savepoint_session, stub_registry):
    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))

        totals = run_full_crawl(savepoint_session, confirm_tos=True)

    # /down is never actually fetched (robots-disallowed before the request);
    # respx would have raised on any unmocked request if it had been.
    assert totals["pages_fetched"] == 2
    assert totals["pages_changed"] == 2
    assert totals["records_extracted"] == 2
    assert totals["errors"] == 1
    assert totals["canonical_upserts"] == 2
    assert totals["open_conflicts"] == 0

    booth_names = {row.canonical_name for row in savepoint_session.query(Booth).all()}
    assert booth_names == {"Stub Booth", "Flaky Booth"}

    run = savepoint_session.query(CrawlRun).one()
    assert run.run_type == "full"
    assert run.status == "success"
    assert run.stats == totals


def test_run_full_crawl_requires_tos_confirmation(savepoint_session, stub_registry):
    with pytest.raises(ValueError, match="ToS confirmation"):
        run_full_crawl(savepoint_session, confirm_tos=False)


def test_run_full_crawl_raises_when_no_sources_enabled(savepoint_session, stub_registry):
    for source in savepoint_session.query(Source).all():
        source.enabled = False
    savepoint_session.flush()

    with pytest.raises(RuntimeError, match="No sources are enabled"):
        run_full_crawl(savepoint_session, confirm_tos=True)


def test_run_refresh_after_crawl_is_a_no_op_on_unchanged_pages(savepoint_session, stub_registry):
    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        first_totals = run_full_crawl(savepoint_session, confirm_tos=True)

    assert first_totals["records_extracted"] == 2

    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        # Identical body -> cache.record_fetch() detects the content hash is
        # unchanged, so this should not be reparsed or re-extracted.
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        second_totals = run_refresh(savepoint_session)

    assert second_totals["pages_fetched"] == 2
    assert second_totals["pages_changed"] == 0
    assert second_totals["records_extracted"] == 0
    assert second_totals["canonical_upserts"] == 0, "already-linked records must not be re-upserted"

    assert savepoint_session.query(Booth).count() == 2
    assert savepoint_session.query(CrawlRun).count() == 2
    refresh_run = (
        savepoint_session.query(CrawlRun).filter_by(run_type="refresh").one()
    )
    assert refresh_run.status == "success"


# ---------------------------------------------------------------------------
# Error responses must not be cached as content
#
# A live crawl hit this: AllEars started returning 403 on every page. Each
# error body hashed as a change, superseded the last good copy, and parsed to
# nothing - so every booth lost its supporting page at once and only the
# reconciliation guard stopped the whole festival being retired.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_an_error_response_is_not_cached_as_content(savepoint_session, stub_registry, status):
    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>good</html>"))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        run_full_crawl(savepoint_session, confirm_tos=True)

    good_pages = savepoint_session.query(RawPage).filter_by(url="https://stub-ok.test/booths").all()
    assert len(good_pages) == 1
    original_id, original_hash = good_pages[0].id, good_pages[0].content_hash

    # The source now refuses us.
    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(
            return_value=httpx.Response(status, text="<html>Forbidden</html>")
        )
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        totals = run_refresh(savepoint_session)

    pages = savepoint_session.query(RawPage).filter_by(url="https://stub-ok.test/booths").all()
    assert len(pages) == 1, "an error response must not create a raw_page"
    assert pages[0].id == original_id
    assert pages[0].content_hash == original_hash, "the good copy must be untouched"
    assert pages[0].superseded_by_id is None, "an error page must never supersede a good one"
    assert totals["errors"] >= 1


def test_an_error_response_is_counted_as_an_error_not_a_fetch(savepoint_session, stub_registry):
    """`pages_fetched: 10, errors: 0` while nothing parsed is exactly the
    signal that misled us on the live run."""
    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(403, text="nope"))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        totals = run_full_crawl(savepoint_session, confirm_tos=True)

    assert totals["pages_fetched"] == 1, "only the successful page counts as fetched"
    assert totals["errors"] == 2, "the 403 plus the robots-disallowed URL"
    assert totals["pages_changed"] == 1


def test_a_successful_response_still_supersedes_a_stale_page(savepoint_session, stub_registry):
    """Guard against over-correcting: real content must still replace old."""
    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>v1</html>"))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        run_full_crawl(savepoint_session, confirm_tos=True)

    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>v2 changed</html>"))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        run_refresh(savepoint_session)

    pages = savepoint_session.query(RawPage).filter_by(url="https://stub-ok.test/booths").order_by(RawPage.id).all()
    assert len(pages) == 2
    assert pages[0].superseded_by_id == pages[1].id


def test_a_304_is_still_treated_as_unchanged_not_as_an_error(savepoint_session, stub_registry):
    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(
            return_value=httpx.Response(200, text="<html>v1</html>", headers={"ETag": '"abc"'})
        )
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        run_full_crawl(savepoint_session, confirm_tos=True)

    with respx.mock(assert_all_called=False) as mock:
        _mock_common_routes(mock)
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(304))
        mock.get("https://stub-flaky.test/ok").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        totals = run_refresh(savepoint_session)

    pages = savepoint_session.query(RawPage).filter_by(url="https://stub-ok.test/booths").all()
    assert len(pages) == 1
    assert pages[0].superseded_by_id is None
    assert pages[0].last_seen_unchanged_at is not None
    assert totals["pages_fetched"] >= 1, "a 304 is a successful conditional GET, not an error"
