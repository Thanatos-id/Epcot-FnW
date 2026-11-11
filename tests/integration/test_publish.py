"""Publishing a Studio changeset in one step, behind the guards.

The file-festival path is exercised end to end here, in a throwaway repo
and with no database: that is the path a GitHub Action runs. The database
path is exercised with the resolve-and-rebuild step replaced by a stand-in
that edits the feed, which is all the guards ever look at.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from epcot_fw import festival_files
from epcot_fw.pipeline import publish
from epcot_fw.pipeline.studio import ChangesetError

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools/data_ledger"))

import build_studio  # noqa: E402

KEY = "festival-of-the-holidays"
BASE_URL = "https://example.test/Epcot-FnW"
YUKON = "Yukon Holiday Kitchen"


def _dish(name, public_id, **kw):
    return {"booth_name": YUKON, "name": name, "public_id": public_id, "category": "food",
            "price_usd": 7.25, "status": "2025-menu", "stroll": False, **kw}


@pytest.fixture
def repo(tmp_path):
    directory = tmp_path / "data" / "festivals" / KEY
    directory.mkdir(parents=True)
    (directory / "festival.json").write_text(json.dumps({
        "key": KEY, "name": "Festival of the Holidays 2026", "short_name": "Holidays", "year": 2026,
        "start": "2026-11-27", "end": "2026-12-30", "menu_season": 2025, "summary": "First pass.",
        "stroll_label": "Cookie Stroll", "typical_dates": "Late November to late December",
    }))
    # Written the way the real files are - indented, one field a line - so a
    # diff of one dish is a few lines and not the whole file.
    def write(name, payload):
        (directory / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    write("booths.json", {"booths": [
        {"name": YUKON, "public_id": "b-yukon", "category": "holiday_kitchen"},
        {"name": "Refreshment Port", "public_id": "b-port", "category": "festival_location"},
    ]})
    write("menu_items.json", {"menu_items": [
        _dish("Beef Bourguignon", "i-beef"),
        _dish("Seared Salmon", "i-salmon"),
        {"booth_name": "Refreshment Port", "name": "Turkey Poutine", "public_id": "i-poutine",
         "category": "food", "status": "confirmed-2026"},
    ]})
    docs = tmp_path / "docs"
    (docs / "v1").mkdir(parents=True)
    festivals = {KEY: festival_files.build_snapshot(KEY, tmp_path / "data" / "festivals")}
    (docs / "studio.html").write_text(build_studio.render({"booths": []}, festivals=festivals))
    return tmp_path


def _changeset(repo, festival=KEY, **payload):
    path = repo / "changeset.json"
    body = {"version": 1, **payload}
    if festival:
        body["festival"] = festival
    path.write_text(json.dumps(body))
    return path


def _publish(repo, **kw):
    return publish.publish_changeset(repo / "changeset.json", base_url=BASE_URL, repo=repo, **kw)


def _items(repo):
    return {i["name"]: i for i in json.loads(
        (repo / "data" / "festivals" / KEY / "menu_items.json").read_text())["menu_items"]}


def _feed(repo):
    return json.loads((repo / "docs" / "v1" / "festivals" / KEY / "snapshot.json").read_text())


def _studio_rows(repo):
    import re
    html = (repo / "docs" / "studio.html").read_text()
    blob = re.search(r'<script id="studio-festivals" type="application/json">(.*?)</script>', html, re.DOTALL)
    return json.loads(blob.group(1))[KEY]


PRICE_CHANGE = {"menu_items": [{"booth_name": YUKON, "name": "Beef Bourguignon", "price_usd": 7.75}]}


# ---------------------------------------------------------------------------
# the file-festival path
# ---------------------------------------------------------------------------


def test_one_call_updates_the_files_the_feed_and_the_studio(repo):
    _changeset(repo, **PRICE_CHANGE)
    report = _publish(repo)
    assert report.ok and report.written
    assert report.headline() == "Holidays: 1 dish"
    assert _items(repo)["Beef Bourguignon"]["price_usd"] == 7.75
    beef = next(i for i in _feed(repo)["menu_items"] if i["public_id"] == "i-beef")
    assert beef["price_usd"] == "7.75"
    studio_beef = next(i for i in _studio_rows(repo)["items"] if i["public_id"] == "i-beef")
    assert studio_beef["price"] == 7.75
    assert f"data/festivals/{KEY}" in report.paths and "docs/studio.html" in report.paths


def test_a_dry_run_runs_the_checks_and_writes_nothing(repo):
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and p.name != "changeset.json"}
    _changeset(repo, **PRICE_CHANGE)
    report = _publish(repo, dry_run=True)
    assert report.ok and not report.written and report.dishes
    after = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and p.name != "changeset.json"}
    assert after == before


def test_an_edit_that_cannot_be_applied_refuses_the_whole_publish(repo):
    """A skipped entry is an edit somebody made that would silently not happen."""
    _changeset(repo, menu_items=[
        {"booth_name": YUKON, "name": "Beef Bourguignon", "price_usd": 7.75},
        {"booth_name": YUKON, "name": "Never Heard Of It", "price_usd": 1},
    ])
    report = _publish(repo)
    assert not report.ok and not report.written
    assert any("Never Heard Of It" in line for line in report.refusals)
    assert _items(repo)["Beef Bourguignon"]["price_usd"] == 7.25
    assert not (repo / "docs" / "v1" / "festivals").exists()


def test_a_delete_the_changeset_asks_for_is_allowed(repo):
    _changeset(repo, menu_items=[{"booth_name": YUKON, "name": "Seared Salmon", "is_active": False}])
    report = _publish(repo)
    assert report.ok
    assert "i-salmon" not in {i["public_id"] for i in _feed(repo)["menu_items"]}


def test_deleting_a_booth_takes_its_dishes_without_tripping_the_guard(repo):
    _changeset(repo, booths=[{"name": YUKON, "is_active": False}])
    report = _publish(repo)
    assert report.ok
    assert [b["canonical_name"] for b in _feed(repo)["booths"]] == ["Refreshment Port"]


def test_a_status_and_a_stroll_mark_can_be_set(repo):
    _changeset(repo, menu_items=[
        {"booth_name": YUKON, "name": "Beef Bourguignon", "status": "confirmed-2026", "stroll": True},
    ])
    assert _publish(repo).ok
    beef = _items(repo)["Beef Bourguignon"]
    assert (beef["status"], beef["stroll"]) == ("confirmed-2026", True)
    studio_beef = next(i for i in _studio_rows(repo)["items"] if i["public_id"] == "i-beef")
    assert studio_beef["badges"] == ["Confirmed 2026", "Cookie Stroll"]


def test_a_status_that_is_not_one_is_refused(repo):
    _changeset(repo, menu_items=[{"booth_name": YUKON, "name": "Beef Bourguignon", "status": "maybe"}])
    report = _publish(repo)
    assert not report.ok and any("status" in line for line in report.refusals)


def test_publishing_the_same_changeset_twice_changes_nothing_the_second_time(repo):
    _changeset(repo, **PRICE_CHANGE)
    _publish(repo)
    first = {p: p.read_bytes() for p in (repo / "docs").rglob("*") if p.is_file()}
    assert _publish(repo).ok
    assert {p: p.read_bytes() for p in (repo / "docs").rglob("*") if p.is_file()} == first


def test_an_unknown_festival_is_an_error_not_a_guess(repo):
    _changeset(repo, festival="epcot-candlelight", **PRICE_CHANGE)
    with pytest.raises(ChangesetError, match="epcot-candlelight"):
        _publish(repo)


def test_an_empty_changeset_publishes_nothing(repo):
    _changeset(repo, menu_items=[], booths=[])
    report = _publish(repo)
    assert report.ok and not report.written and report.headline() == "Holidays: nothing to change"


# ---------------------------------------------------------------------------
# the guards on their own
# ---------------------------------------------------------------------------


def _inventory(booths, items):
    return publish.Inventory(booths=dict(booths), items=dict(items))


BEFORE = _inventory({"b1": "Yukon", "b2": "Port"},
                    {"i1": ("Yukon", "Beef"), "i2": ("Yukon", "Salmon"), "i3": ("Port", "Poutine")})


def test_a_dish_that_vanishes_unasked_is_refused_by_name():
    after = _inventory(BEFORE.booths, {"i1": ("Yukon", "Beef"), "i3": ("Port", "Poutine")})
    refusals = publish.check_guards(BEFORE, after, {"menu_items": []}, [])
    assert len(refusals) == 1 and "Yukon / Salmon" in refusals[0]


def test_a_booth_that_vanishes_unasked_is_refused():
    after = _inventory({"b1": "Yukon"}, {"i1": ("Yukon", "Beef"), "i2": ("Yukon", "Salmon")})
    refusals = publish.check_guards(BEFORE, after, {}, [])
    assert any("booth" in line and "Port" in line for line in refusals)
    assert any("Port / Poutine" in line for line in refusals)


def test_a_rename_is_not_a_loss_because_the_id_survives():
    after = _inventory(BEFORE.booths, {**BEFORE.items, "i1": ("Yukon", "Boeuf")})
    assert publish.check_guards(BEFORE, after, {}, []) == []


def test_the_database_festival_is_allowed_the_few_rows_a_crawl_retired():
    after = _inventory(BEFORE.booths, {"i1": ("Yukon", "Beef"), "i3": ("Port", "Poutine")})
    assert publish.check_guards(BEFORE, after, {}, [], loss_floor=5, loss_share=0.1) == []


def test_rows_that_cannot_be_told_apart_are_refused():
    inventory = publish.inventory_of_client_snapshot({
        "booths": [{"id": 1, "public_id": "b1", "canonical_name": "Yukon"}],
        "menu_items": [
            {"booth_id": 1, "public_id": "i1", "canonical_name": "Beef"},
            {"booth_id": 1, "public_id": "i1", "canonical_name": "Salmon"},
            {"booth_id": 1, "public_id": None, "canonical_name": "Cookie"},
            {"booth_id": 9, "public_id": "i4", "canonical_name": "Orphan"},
        ],
    })
    assert len(inventory.problems) == 3
    refusals = publish.check_guards(publish.Inventory(), inventory, {}, [])
    assert len(refusals) == 3


def test_a_festival_emptied_out_is_refused():
    refusals = publish.check_guards(BEFORE, publish.Inventory(), {}, [], loss_floor=99)
    assert any("no booths at all" in line for line in refusals)


# ---------------------------------------------------------------------------
# the database path, with resolve-and-rebuild replaced
# ---------------------------------------------------------------------------


def _database_repo(repo):
    manual = repo / "data" / "manual"
    manual.mkdir(parents=True)
    (manual / "menu_items.json").write_text(json.dumps({"menu_items": []}))
    (manual / "booth_locations.json").write_text(json.dumps({"booths": []}))
    feed = {
        "booths": [{"id": 1, "public_id": "b-canada", "canonical_name": "Canada"}],
        "menu_items": [{"booth_id": 1, "public_id": f"i-{n}", "canonical_name": f"Dish {n}"} for n in range(60)],
    }
    (repo / "docs" / "v1" / "snapshot.json").write_text(json.dumps(feed))
    return feed


def test_a_changeset_naming_no_festival_goes_through_the_database_path(repo):
    feed = _database_repo(repo)
    seen = []
    _changeset(repo, festival=None, menu_items=[
        {"booth_name": "Canada", "name": "Dish 1", "price_usd": 9, "status": "confirmed-2026"},
    ])
    report = _publish(repo, rebuild=seen.append)
    assert report.ok and report.written and report.festival == "food-and-wine"
    assert seen == [repo]
    curated = json.loads((repo / "data" / "manual" / "menu_items.json").read_text())["menu_items"]
    assert curated == [{"booth_name": "Canada", "name": "Dish 1", "price_usd": 9}]  # no `status`
    assert feed  # unchanged by the stand-in


def test_a_rebuild_that_loses_a_large_share_of_the_menu_is_refused(repo):
    feed = _database_repo(repo)

    def broken_resolve(path):
        feed["menu_items"] = feed["menu_items"][:30]
        (path / "docs" / "v1" / "snapshot.json").write_text(json.dumps(feed))

    _changeset(repo, festival=None, menu_items=[{"booth_name": "Canada", "name": "Dish 1", "price_usd": 9}])
    report = _publish(repo, rebuild=broken_resolve)
    assert not report.ok and "30 dish(es) would disappear" in report.refusals[0]


def test_the_database_path_never_rebuilds_on_a_dry_run(repo):
    _database_repo(repo)
    _changeset(repo, festival=None, menu_items=[{"booth_name": "Canada", "name": "Dish 1", "price_usd": 9}])

    def must_not_run(path):
        raise AssertionError("a dry run reached the database")

    assert _publish(repo, dry_run=True, rebuild=must_not_run).ok


# ---------------------------------------------------------------------------
# committing
# ---------------------------------------------------------------------------


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def git_repo(repo):
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "data", "docs")
    _git(repo, "commit", "-q", "-m", "start")
    return repo


def test_a_publish_is_one_commit_of_only_its_own_paths(git_repo):
    (git_repo / "dish-photos").mkdir()
    (git_repo / "dish-photos" / "scratch.jpg").write_bytes(b"not for committing")
    _changeset(git_repo, **PRICE_CHANGE)
    report = publish.commit(_publish(git_repo), repo=git_repo)
    assert report.commit and not report.pushed
    changed = _git(git_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert f"data/festivals/{KEY}/menu_items.json" in changed
    assert "docs/studio.html" in changed
    assert not any(path.startswith("dish-photos/") or path == "changeset.json" for path in changed)
    assert _git(git_repo, "log", "-1", "--format=%s").strip() == "Studio publish - Holidays: 1 dish"


def test_republishing_what_is_already_live_leaves_no_commit(git_repo):
    _changeset(git_repo, **PRICE_CHANGE)
    publish.commit(_publish(git_repo), repo=git_repo)
    head = _git(git_repo, "rev-parse", "HEAD")
    again = publish.commit(_publish(git_repo), repo=git_repo)
    assert again.commit is None
    assert _git(git_repo, "rev-parse", "HEAD") == head


def test_a_refused_publish_is_never_committed(git_repo):
    _changeset(git_repo, menu_items=[{"booth_name": YUKON, "name": "Ghost", "price_usd": 1}])
    report = publish.commit(_publish(git_repo), repo=git_repo)
    assert report.commit is None
    assert _git(git_repo, "status", "--porcelain", "--", "data", "docs") == ""


# ---------------------------------------------------------------------------
# undoing a publish
# ---------------------------------------------------------------------------


def _published(git_repo, **payload):
    _changeset(git_repo, **payload)
    return publish.commit(_publish(git_repo), repo=git_repo).commit


def test_undoing_a_publish_restores_the_files_the_feed_and_the_studio(git_repo):
    start = {p: p.read_bytes() for p in (git_repo / "data").rglob("*.json")}
    sha = _published(git_repo, **PRICE_CHANGE)
    report = publish.commit(publish.revert(sha[:10], repo=git_repo), repo=git_repo)
    assert report.ok and report.commit
    assert {p: p.read_bytes() for p in (git_repo / "data").rglob("*.json")} == start
    beef = next(i for i in _feed(git_repo)["menu_items"] if i["public_id"] == "i-beef")
    assert beef["price_usd"] == "7.25"
    assert next(i for i in _studio_rows(git_repo)["items"] if i["public_id"] == "i-beef")["price"] == 7.25
    assert _git(git_repo, "log", "-1", "--format=%s").strip() == "Studio revert - Holidays: 1 dish"


def test_an_undo_survives_a_later_publish_of_other_dishes(git_repo):
    """A plain `git revert` would conflict in the feed and the Studio page."""
    sha = _published(git_repo, **PRICE_CHANGE)
    _published(git_repo, menu_items=[{"booth_name": "Refreshment Port", "name": "Turkey Poutine", "price_usd": 9.5}])
    report = publish.commit(publish.revert(sha, repo=git_repo), repo=git_repo)
    assert report.ok
    prices = {i["public_id"]: i["price_usd"] for i in _feed(git_repo)["menu_items"]}
    assert prices["i-beef"] == "7.25" and prices["i-poutine"] == "9.50"


def test_an_undo_is_refused_once_the_same_dish_has_been_edited_again(git_repo):
    sha = _published(git_repo, **PRICE_CHANGE)
    _published(git_repo, menu_items=[{"booth_name": YUKON, "name": "Beef Bourguignon", "price_usd": 8.5}])
    report = publish.revert(sha, repo=git_repo)
    assert not report.ok and "later edits" in report.refusals[0]
    assert _git(git_repo, "status", "--porcelain", "--", "data", "docs") == ""


def test_only_a_publish_can_be_undone(git_repo):
    start = _git(git_repo, "rev-parse", "HEAD").strip()
    report = publish.revert(start, repo=git_repo)
    assert not report.ok and "not a Studio publish" in report.refusals[0]


def test_undoing_a_publish_removes_the_photo_it_added(git_repo):
    import base64
    photo = {"id": "i-beef", "mime": "image/png", "data_base64": base64.b64encode(b"\x89PNG-bytes").decode()}
    sha = _published(git_repo, menu_items=[{"booth_name": YUKON, "name": "Beef Bourguignon", "photo": photo}])
    assert (git_repo / "docs" / "dish-photos" / "i-beef.png").exists()
    report = publish.commit(publish.revert(sha, repo=git_repo), repo=git_repo)
    assert report.ok and report.commit
    assert not (git_repo / "docs" / "dish-photos" / "i-beef.png").exists()
    assert not _items(git_repo)["Beef Bourguignon"].get("image_url")
