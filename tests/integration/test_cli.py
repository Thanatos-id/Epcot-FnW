"""cli/main.py commands each open their own SessionLocal() bound to the real
production engine (epcot_fw.db.base.engine), so - like
test_crawl_and_refresh_pipeline.py - these tests monkeypatch SessionLocal to
a sessionmaker in "create_savepoint" join mode over a single connection/
transaction we roll back at teardown, regardless of how many sessions a
command opens+commits internally.
"""

import datetime

import httpx
import pytest
import respx
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

import epcot_fw.cli.main as cli_main
from epcot_fw.db.models import DietaryTag, Festival, MergeConflict, Source
from epcot_fw.fetch import rate_limiter
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter
from tests.conftest import DIETARY_TAG_ROWS, SOURCE_ROWS

runner = CliRunner()


class StubAdapter(SourceAdapter):
    key = "stub_ok"
    priority_rank = 1

    def seed_urls(self, festival_year):
        return [SeedUrl(url="https://stub-ok.test/booths", page_kind="booth_list")]

    def parse(self, raw_html, url, page_kind):
        return [
            ExtractedRecordDTO(entity_type="booth", natural_key_hint="stub booth", payload={"name": "Stub Booth"})
        ]


@pytest.fixture()
def cli_session_factory(engine, monkeypatch):
    connection = engine.connect()
    trans = connection.begin()
    session_factory = sessionmaker(
        bind=connection, future=True, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    seed_session = session_factory()
    for row in SOURCE_ROWS:
        seed_session.add(Source(**row))
    for code, label in DIETARY_TAG_ROWS:
        seed_session.add(DietaryTag(code=code, label=label))
    seed_session.add(
        Festival(
            year=2026,
            name="EPCOT International Food & Wine Festival 2026",
            slug="epcot-food-wine-2026",
            status="upcoming",
        )
    )
    seed_session.commit()

    monkeypatch.setattr(cli_main, "SessionLocal", session_factory)
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)

    yield session_factory, seed_session

    seed_session.close()
    trans.rollback()
    connection.close()


def test_sources_list_shows_seeded_sources(cli_session_factory):
    result = runner.invoke(cli_main.app, ["sources", "list"])
    assert result.exit_code == 0
    assert "allears" in result.stdout
    assert "disney_official" in result.stdout


def test_sources_enable_and_disable(cli_session_factory):
    _, seed_session = cli_session_factory

    result = runner.invoke(cli_main.app, ["sources", "enable", "wdwmagic"])
    assert result.exit_code == 0
    assert "enabled wdwmagic" in result.stdout
    row = seed_session.query(Source).filter_by(key="wdwmagic").one()
    seed_session.refresh(row)
    assert row.enabled is True

    result = runner.invoke(cli_main.app, ["sources", "disable", "wdwmagic"])
    assert result.exit_code == 0
    assert "disabled wdwmagic" in result.stdout
    seed_session.refresh(row)
    assert row.enabled is False


def test_sources_enable_unknown_key_fails(cli_session_factory):
    result = runner.invoke(cli_main.app, ["sources", "enable", "not-a-real-source"])
    assert result.exit_code != 0


def test_sources_disable_unknown_key_fails(cli_session_factory):
    result = runner.invoke(cli_main.app, ["sources", "disable", "not-a-real-source"])
    assert result.exit_code != 0


def test_review_lists_open_conflicts(cli_session_factory):
    _, seed_session = cli_session_factory

    seed_session.add(
        MergeConflict(
            entity_type="booth",
            canonical_id=1,
            field_name="category",
            candidate_values={"1": "food", "2": "beverage"},
            status="open",
            opened_at=datetime.datetime.now(datetime.UTC),
        )
    )
    seed_session.commit()

    result = runner.invoke(cli_main.app, ["review"])
    assert result.exit_code == 0
    assert "1 open conflict(s) shown" in result.stdout


def test_review_with_no_open_conflicts(cli_session_factory):
    result = runner.invoke(cli_main.app, ["review"])
    assert result.exit_code == 0
    assert "0 open conflict(s) shown" in result.stdout


def test_db_seed_command_invokes_seed(cli_session_factory, monkeypatch):
    called = {}

    def fake_seed():
        called["ran"] = True

    monkeypatch.setattr("epcot_fw.db.seed.seed", fake_seed)

    result = runner.invoke(cli_main.app, ["db", "seed"])
    assert result.exit_code == 0
    assert called.get("ran") is True
    assert "Seed complete." in result.stdout


def test_db_upgrade_command_invokes_alembic(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "subprocess.run", lambda args, check: calls.append((args, check))
    )

    result = runner.invoke(cli_main.app, ["db", "upgrade"])
    assert result.exit_code == 0
    assert calls == [(["alembic", "upgrade", "head"], True)]


def test_serve_command_invokes_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, host, port, reload: calls.append((app, host, port, reload)))

    result = runner.invoke(cli_main.app, ["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert result.exit_code == 0
    assert calls == [("epcot_fw.api.main:app", "0.0.0.0", 9000, False)]


def test_crawl_command_runs_full_crawl_and_prints_stats(cli_session_factory, monkeypatch):
    import epcot_fw.pipeline.crawl as crawl_module

    monkeypatch.setattr(crawl_module, "SOURCE_REGISTRY", {"stub_ok": StubAdapter()})

    _, seed_session = cli_session_factory
    seed_session.query(Source).filter(Source.key != "stub_ok").update({"enabled": False})
    seed_session.add(Source(key="stub_ok", display_name="Stub", base_url="https://stub-ok.test", priority_rank=1, enabled=True, crawl_delay_sec=0))
    seed_session.commit()

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://stub-ok.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        result = runner.invoke(cli_main.app, ["crawl", "--confirm-tos", "--sources", "stub_ok"])

    assert result.exit_code == 0, result.stdout
    assert "'records_extracted': 1" in result.stdout


def test_crawl_without_confirm_tos_fails(cli_session_factory):
    result = runner.invoke(cli_main.app, ["crawl"])
    assert result.exit_code != 0


def test_refresh_command_runs_and_prints_stats(cli_session_factory, monkeypatch):
    import epcot_fw.pipeline.refresh as refresh_module

    monkeypatch.setattr(refresh_module, "SOURCE_REGISTRY", {"stub_ok": StubAdapter()})

    _, seed_session = cli_session_factory
    seed_session.query(Source).filter(Source.key != "stub_ok").update({"enabled": False})
    seed_session.add(
        Source(
            key="stub_ok",
            display_name="Stub",
            base_url="https://stub-ok.test",
            priority_rank=1,
            enabled=True,
            crawl_delay_sec=0,
        )
    )
    seed_session.commit()

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://stub-ok.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get("https://stub-ok.test/booths").mock(return_value=httpx.Response(200, text="<html>ok</html>"))
        result = runner.invoke(cli_main.app, ["refresh", "--sources", "stub_ok"])

    assert result.exit_code == 0, result.stdout
    assert "'records_extracted': 1" in result.stdout


def test_resolve_command_runs_resolution_and_prints_stats(cli_session_factory):
    result = runner.invoke(cli_main.app, ["resolve"])
    assert result.exit_code == 0, result.stdout
    assert "canonical_upserts" in result.stdout
