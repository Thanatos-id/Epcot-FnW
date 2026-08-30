"""Applying a changeset exported by docs/studio.html.

Everything here runs without a database: `apply_changeset` only publishes
photos and merges curated files, and the caller stages and re-resolves. That
split is deliberate - it is what lets a changeset someone emailed you be
inspected with --dry-run before any of it is trusted.
"""

import base64
import json

import pytest

from epcot_fw.pipeline.studio import ChangesetError, apply_changeset, load_changeset

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-not-really-a-png-but-bytes").decode()
BASE_URL = "https://example.test/Epcot-FnW"


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "curated").mkdir()
    items = tmp_path / "curated" / "menu_items.json"
    booths = tmp_path / "curated" / "booth_locations.json"
    items.write_text(json.dumps({"_README": ["keep me"], "menu_items": []}))
    booths.write_text(json.dumps({"_README": ["keep me too"], "booths": []}))
    return {
        "items": items,
        "booths": booths,
        "publish": tmp_path / "docs" / "dish-photos",
        "root": tmp_path,
    }


def _write(workspace, payload):
    path = workspace["root"] / "changeset.json"
    path.write_text(json.dumps(payload))
    return path


def _apply(workspace, payload, **kw):
    return apply_changeset(
        _write(workspace, payload),
        publish_dir=workspace["publish"],
        base_url=BASE_URL,
        items_path=workspace["items"],
        booths_path=workspace["booths"],
        **kw,
    )


def _items(workspace):
    return json.loads(workspace["items"].read_text())["menu_items"]


def _booths(workspace):
    return json.loads(workspace["booths"].read_text())["booths"]


# ---------------------------------------------------------------------------
# the file itself
# ---------------------------------------------------------------------------


def test_a_changeset_from_a_newer_studio_is_refused_rather_than_half_applied(tmp_path):
    path = tmp_path / "cs.json"
    path.write_text(json.dumps({"version": 2, "menu_items": []}))
    with pytest.raises(ChangesetError, match="version 2"):
        load_changeset(path)


def test_something_that_is_not_a_changeset_is_refused(tmp_path):
    path = tmp_path / "cs.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(ChangesetError):
        load_changeset(path)


# ---------------------------------------------------------------------------
# photos
# ---------------------------------------------------------------------------


def test_a_photo_is_published_and_its_url_written_into_the_curated_file(workspace):
    report = _apply(workspace, {
        "version": 1,
        "menu_items": [{
            "booth_name": "Germany", "name": "Kirschwasser Torte",
            "photo": {"id": "3cb25fa7-6ace-48df-b13f-870a0c375f17", "mime": "image/jpeg",
                      "data_base64": PNG},
        }],
    })

    assert report.photos == ["3cb25fa7-6ace-48df-b13f-870a0c375f17.jpg"]
    published = workspace["publish"] / "3cb25fa7-6ace-48df-b13f-870a0c375f17.jpg"
    assert published.read_bytes() == base64.b64decode(PNG)
    assert _items(workspace)[0]["image_url"] == (
        f"{BASE_URL}/dish-photos/3cb25fa7-6ace-48df-b13f-870a0c375f17.jpg"
    )
    assert "photo" not in _items(workspace)[0], "the bytes must not land in the curated file"


def test_the_extension_follows_the_declared_mime_type(workspace):
    _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu",
                        "photo": {"id": "abc", "mime": "image/png", "data_base64": PNG}}],
    })
    assert (workspace["publish"] / "abc.png").exists()


def test_an_unrecognised_mime_type_falls_back_to_jpg(workspace):
    _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu",
                        "photo": {"id": "abc", "mime": "application/octet-stream",
                                  "data_base64": PNG}}],
    })
    assert (workspace["publish"] / "abc.jpg").exists()


@pytest.mark.parametrize(
    "hostile_id",
    ["../../etc/passwd", "/absolute/path", "..", "with space", "sub/dir/file"],
)
def test_a_photo_id_cannot_escape_the_publish_directory(workspace, hostile_id):
    """A changeset is a plain JSON file a person can open and edit, so the id
    that names a file on disk is treated as untrusted input."""
    report = _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu",
                        "photo": {"id": hostile_id, "mime": "image/jpeg", "data_base64": PNG}}],
    })

    (name,) = report.photos
    assert "/" not in name and ".." not in name
    written = list(workspace["publish"].iterdir())
    assert [p.name for p in written] == [name]
    assert written[0].parent == workspace["publish"]


def test_the_same_hostile_id_always_lands_on_the_same_filename(workspace):
    """Re-attaching the same dish's photo has to overwrite it, not pile up a
    second file the curated URL no longer points at."""
    first = _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu",
                        "photo": {"id": "a/b", "mime": "image/jpeg", "data_base64": PNG}}],
    })
    second = _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu",
                        "photo": {"id": "a/b", "mime": "image/jpeg", "data_base64": PNG}}],
    })
    assert first.photos == second.photos
    assert len(list(workspace["publish"].iterdir())) == 1


def test_a_photo_that_is_not_base64_is_reported_rather_than_written(workspace):
    with pytest.raises(ChangesetError, match="base64"):
        _apply(workspace, {
            "version": 1,
            "menu_items": [{"booth_name": "Italy", "name": "Tiramisu",
                            "photo": {"id": "abc", "mime": "image/jpeg",
                                      "data_base64": "not base64 at all!!"}}],
        })


# ---------------------------------------------------------------------------
# merging
# ---------------------------------------------------------------------------


def test_the_readme_and_existing_entries_survive(workspace):
    workspace["items"].write_text(json.dumps({
        "_README": ["keep me"],
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu", "description": "already here"}],
    }))
    _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Germany", "name": "Kirschwasser Torte", "price_usd": 9.5}],
    })

    payload = json.loads(workspace["items"].read_text())
    assert payload["_README"] == ["keep me"]
    assert {(e["booth_name"], e["name"]) for e in payload["menu_items"]} == {
        ("Italy", "Tiramisu"), ("Germany", "Kirschwasser Torte"),
    }


def test_a_changeset_deliberately_overwrites_a_value_already_curated(workspace):
    """Exporting is a decision that this dish should say exactly this - the
    opposite stance from `backfill-images`, which is a search and leaves a
    chosen value alone."""
    workspace["items"].write_text(json.dumps({
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu", "price_usd": 1.0}],
    }))
    _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu", "price_usd": 9.5}],
    })
    assert _items(workspace)[0]["price_usd"] == 9.5


def test_a_booth_edit_does_not_revert_a_pin_it_never_mentioned(workspace):
    """map.html replaced the booths array wholesale, which was safe while
    dropping pins was all it did. The studio changes a note and a pin in the
    same sitting, so the merge has to be per-booth."""
    workspace["booths"].write_text(json.dumps({
        "booths": [{"name": "Australia", "latitude": 28.37, "longitude": -81.54,
                    "location_precision": "mapped"}],
    }))
    _apply(workspace, {
        "version": 1,
        "booths": [{"name": "Belgium", "latitude": 28.36, "longitude": -81.55,
                    "location_precision": "mapped"}],
    })

    by_name = {b["name"]: b for b in _booths(workspace)}
    assert by_name["Australia"]["latitude"] == 28.37, "an untouched pin must survive"
    assert by_name["Belgium"]["location_precision"] == "mapped"


def test_an_unknown_key_is_dropped_rather_than_written_into_a_curated_file(workspace):
    """The curated files are read by people too; a key nothing understands
    would sit in one forever meaning nothing."""
    _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu", "price_usd": 9.5,
                        "invented_field": "junk"}],
        "booths": [{"name": "Italy", "latitude": 28.37, "nonsense": True}],
    })
    assert "invented_field" not in _items(workspace)[0]
    assert "nonsense" not in _booths(workspace)[0]


def test_a_dish_with_no_booth_is_reported_not_guessed_at(workspace):
    """Menu items are matched within a booth, so a dish name with nothing to
    scope it cannot be resolved."""
    report = _apply(workspace, {
        "version": 1,
        "menu_items": [
            {"name": "Orphan Dish", "price_usd": 3},
            {"booth_name": "Italy", "name": "Tiramisu"},
        ],
    })
    assert report.menu_items == ["Italy / Tiramisu"]
    assert len(report.skipped) == 1 and "Orphan Dish" in report.skipped[0]
    assert [e["name"] for e in _items(workspace)] == ["Tiramisu"]


def test_a_rename_travels_as_both_names(workspace):
    """`name` is how the correction finds the dish; `rename_to` is what it
    becomes. A record whose name is already the new one matches nothing."""
    _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu ", "rename_to": "Tiramisu"}],
    })
    entry = _items(workspace)[0]
    assert (entry["name"], entry["rename_to"]) == ("Tiramisu ", "Tiramisu")


def test_added_and_deleted_rows_are_counted_separately(workspace):
    report = _apply(workspace, {
        "version": 1,
        "menu_items": [
            {"booth_name": "Germany", "name": "Invented Dish", "new": True},
            {"booth_name": "Germany", "name": "Regretted Dish", "is_active": False},
        ],
        "booths": [{"name": "Brew-Wing Lab", "new": True}],
    })
    assert report.added == ["Germany / Invented Dish", "Brew-Wing Lab"]
    assert report.deleted == ["Germany / Regretted Dish"]


# ---------------------------------------------------------------------------
# dry run
# ---------------------------------------------------------------------------


def test_a_dry_run_reports_everything_and_writes_nothing(workspace):
    before_items = workspace["items"].read_text()
    before_booths = workspace["booths"].read_text()

    report = _apply(workspace, {
        "version": 1,
        "menu_items": [{"booth_name": "Italy", "name": "Tiramisu",
                        "photo": {"id": "abc", "mime": "image/jpeg", "data_base64": PNG}}],
        "booths": [{"name": "Italy", "latitude": 28.37}],
    }, dry_run=True)

    assert report.menu_items == ["Italy / Tiramisu"]
    assert report.booths == ["Italy"]
    assert report.photos == ["abc.jpg"]
    assert not workspace["publish"].exists()
    assert workspace["items"].read_text() == before_items
    assert workspace["booths"].read_text() == before_booths


def test_an_empty_changeset_is_a_no_op(workspace):
    report = _apply(workspace, {"version": 1, "menu_items": [], "booths": []})
    assert report.total == 0
    assert not workspace["publish"].exists()
