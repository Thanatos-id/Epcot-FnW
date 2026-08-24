"""Round-tripping dish photos out for external processing and back in.

`_download_bytes()` is monkeypatched out in every export test - these
exercise the manifest/matching/publish logic, which is where the actual
rules live: only active dishes with a photo are exported, files are keyed
by public_id so a rename or extension change in processing can't break the
match, and import is a deliberate overwrite (unlike the backfill tool).
"""

import csv
import json

import httpx
import pytest
import respx
from sqlalchemy import select

from epcot_fw.db.models import Booth, MenuItem
from epcot_fw.fetch import rate_limiter, robots
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.pipeline import photo_workflow as workflow_mod
from epcot_fw.pipeline.manual import merge_menu_item_overrides
from epcot_fw.pipeline.photo_workflow import _download_bytes, export_dish_photos, import_dish_photos

from ._helpers import ingest


def _seed_menu(db_session, festival_id, booth="Germany", dish="Kirschwasser Torte", image_url=None):
    ingest(
        db_session,
        [
            ExtractedRecordDTO(
                entity_type="booth",
                natural_key_hint=booth.lower(),
                payload={"name": booth, "category": "global_marketplace"},
            ),
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=dish.lower(),
                payload={"booth_name": booth, "name": dish, "category": "food"},
            ),
        ],
        "disney_food_blog",
        festival_id,
        url="https://example.test/hub-2026",
    )
    item = db_session.scalars(select(MenuItem).where(MenuItem.canonical_name == dish)).one()
    if image_url is not None:
        item.image_url = image_url
        db_session.flush()
    return item


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_downloads_and_writes_a_manifest(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    item = _seed_menu(db_session, festival_id, image_url="https://cdn.test/torte.jpg")
    monkeypatch.setattr(workflow_mod, "_download_bytes", lambda url, **kw: b"fake-bytes")

    out_dir = tmp_path / "dish-photos"
    report = export_dish_photos(db_session, out_dir)

    assert report.total == 1
    assert report.downloaded == 1
    assert report.failed == []

    filename = f"{item.public_id}.jpg"
    assert (out_dir / filename).read_bytes() == b"fake-bytes"

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert len(manifest["photos"]) == 1
    entry = manifest["photos"][0]
    assert entry["public_id"] == str(item.public_id)
    assert entry["booth_name"] == "Germany"
    assert entry["dish_name"] == "Kirschwasser Torte"
    assert entry["filename"] == filename
    assert entry["downloaded"] is True

    with (out_dir / "manifest.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["public_id"] == str(item.public_id)


def test_export_only_includes_active_dishes_with_a_photo(db_session, monkeypatch, tmp_path):
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id, dish="No Photo Yet")  # image_url stays None
    pictured = _seed_menu(db_session, festival_id, dish="Has A Photo", image_url="https://cdn.test/a.jpg")
    retired = _seed_menu(db_session, festival_id, dish="Retired Dish", image_url="https://cdn.test/b.jpg")
    db_session.execute(
        MenuItem.__table__.update().where(MenuItem.id == retired.id).values(is_active=False)
    )
    db_session.flush()
    monkeypatch.setattr(workflow_mod, "_download_bytes", lambda url, **kw: b"bytes")

    report = export_dish_photos(db_session, tmp_path / "out")

    names = {p.dish_name for p in report.photos}
    assert names == {"Has A Photo"}
    assert report.photos[0].public_id == str(pictured.public_id)


def test_a_failed_download_is_still_listed_but_not_downloaded(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    item = _seed_menu(db_session, festival_id, image_url="https://cdn.test/gone.jpg")
    monkeypatch.setattr(workflow_mod, "_download_bytes", lambda url, **kw: None)

    out_dir = tmp_path / "out"
    report = export_dish_photos(db_session, out_dir)

    assert report.total == 1
    assert report.downloaded == 0
    assert len(report.failed) == 1
    assert report.failed[0].public_id == str(item.public_id)
    assert not (out_dir / f"{item.public_id}.jpg").exists()

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["photos"][0]["downloaded"] is False


def test_filename_extension_follows_the_source_url(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    item = _seed_menu(db_session, festival_id, image_url="https://cdn.test/dish.png?w=800")
    monkeypatch.setattr(workflow_mod, "_download_bytes", lambda url, **kw: b"png-bytes")

    report = export_dish_photos(db_session, tmp_path / "out")

    assert report.photos[0].filename == f"{item.public_id}.png"


def test_an_unrecognized_extension_falls_back_to_jpg(db_session, tmp_path, monkeypatch):
    festival_id = db_session.info["festival_id"]
    item = _seed_menu(db_session, festival_id, image_url="https://cdn.test/dish-image-handler.php")
    monkeypatch.setattr(workflow_mod, "_download_bytes", lambda url, **kw: b"bytes")

    report = export_dish_photos(db_session, tmp_path / "out")

    assert report.photos[0].filename == f"{item.public_id}.jpg"


def test_export_never_reads_or_writes_a_booth_image(db_session, tmp_path, monkeypatch):
    """The one hard requirement carried over from the backfill tool: this
    workflow is dish photos only."""
    festival_id = db_session.info["festival_id"]
    _seed_menu(db_session, festival_id, image_url="https://cdn.test/torte.jpg")
    monkeypatch.setattr(workflow_mod, "_download_bytes", lambda url, **kw: b"bytes")

    export_dish_photos(db_session, tmp_path / "out")

    booth = db_session.scalars(select(Booth).where(Booth.canonical_name == "Germany")).one()
    assert booth.image_url is None


# ---------------------------------------------------------------------------
# _download_bytes: the actual network layer, mocked out everywhere else above
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_robots_cache(monkeypatch):
    # robots.is_allowed() caches per domain at module scope - each test below
    # uses its own domain, but reset anyway so ordering can never matter.
    monkeypatch.setattr(robots, "_robots_cache", {})


def test_download_bytes_returns_the_body_on_success(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)
    url = "https://cdn-ok.test/dish.jpg"

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://cdn-ok.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(url).mock(return_value=httpx.Response(200, content=b"real-image-bytes"))
        result = _download_bytes(url)

    assert result == b"real-image-bytes"


def test_download_bytes_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)
    url = "https://cdn-404.test/missing.jpg"

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://cdn-404.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(url).mock(return_value=httpx.Response(404))
        result = _download_bytes(url)

    assert result is None


def test_download_bytes_returns_none_on_connection_error(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)
    url = "https://cdn-unreachable.test/dish.jpg"

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://cdn-unreachable.test/robots.txt").mock(return_value=httpx.Response(404))
        mock.get(url).mock(side_effect=httpx.ConnectError("refused"))
        result = _download_bytes(url)

    assert result is None


def test_download_bytes_respects_robots_disallow(monkeypatch):
    monkeypatch.setattr(rate_limiter, "wait_for_domain", lambda url, min_delay_sec: None)
    url = "https://cdn-blocked.test/blocked/dish.jpg"

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://cdn-blocked.test/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /blocked/")
        )
        result = _download_bytes(url)

    assert result is None


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def _write_manifest(in_dir, photos):
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "manifest.json").write_text(
        json.dumps({"photos": photos}, indent=2)
    )


def test_import_publishes_matched_files_and_stages_overrides(tmp_path):
    in_dir = tmp_path / "processed"
    public_id = "11111111-1111-1111-1111-111111111111"
    _write_manifest(
        in_dir,
        [
            {
                "public_id": public_id,
                "booth_name": "Germany",
                "dish_name": "Kirschwasser Torte",
                "category": "food",
                "original_url": "https://cdn.test/torte.jpg",
                "filename": f"{public_id}.jpg",
                "downloaded": True,
            }
        ],
    )
    # Processing swapped the extension - a PNG came back for the JPEG that went in.
    (in_dir / f"{public_id}.png").write_bytes(b"processed-bytes")

    publish_dir = tmp_path / "docs" / "dish-photos"
    overrides_path = tmp_path / "menu_items.json"

    report = import_dish_photos(
        in_dir,
        publish_dir=publish_dir,
        base_url="https://thanatos-id.github.io/Epcot-FnW",
        overrides_path=overrides_path,
    )

    assert report.published == ["Kirschwasser Torte"]
    assert report.missing == []

    published_file = publish_dir / f"{public_id}.png"
    assert published_file.read_bytes() == b"processed-bytes"

    written = json.loads(overrides_path.read_text())
    assert written["menu_items"] == [
        {
            "booth_name": "Germany",
            "name": "Kirschwasser Torte",
            "image_url": f"https://thanatos-id.github.io/Epcot-FnW/dish-photos/{public_id}.png",
        }
    ]


def test_import_reports_manifest_entries_with_no_processed_file(tmp_path):
    in_dir = tmp_path / "processed"
    public_id = "22222222-2222-2222-2222-222222222222"
    _write_manifest(
        in_dir,
        [
            {
                "public_id": public_id,
                "booth_name": "Norway",
                "dish_name": "Kringle",
                "category": "food",
                "original_url": "https://cdn.test/kringle.jpg",
                "filename": f"{public_id}.jpg",
                "downloaded": False,
            }
        ],
    )
    # No file was ever downloaded and nothing was dropped in for processing.

    report = import_dish_photos(
        in_dir,
        publish_dir=tmp_path / "docs" / "dish-photos",
        base_url="https://thanatos-id.github.io/Epcot-FnW",
        overrides_path=tmp_path / "menu_items.json",
    )

    assert report.published == []
    assert len(report.missing) == 1
    assert report.missing[0]["dish_name"] == "Kringle"
    assert not (tmp_path / "menu_items.json").exists()


def test_import_deliberately_overwrites_an_existing_curated_value(tmp_path):
    """Unlike the backfill tool, running `images import` is a decision to
    replace whatever is already staged - proves overwrite=True actually
    takes effect through the full import path, not just in the shared
    helper's own unit tests."""
    in_dir = tmp_path / "processed"
    public_id = "33333333-3333-3333-3333-333333333333"
    _write_manifest(
        in_dir,
        [
            {
                "public_id": public_id,
                "booth_name": "Germany",
                "dish_name": "Kirschwasser Torte",
                "category": "food",
                "original_url": "https://cdn.test/old.jpg",
                "filename": f"{public_id}.jpg",
                "downloaded": True,
            }
        ],
    )
    (in_dir / f"{public_id}.jpg").write_bytes(b"new-processed-bytes")

    overrides_path = tmp_path / "menu_items.json"
    overrides_path.write_text(
        json.dumps(
            {
                "menu_items": [
                    {
                        "booth_name": "Germany",
                        "name": "Kirschwasser Torte",
                        "image_url": "https://cdn.test/hand-picked-old.jpg",
                    }
                ]
            }
        )
    )

    import_dish_photos(
        in_dir,
        publish_dir=tmp_path / "docs" / "dish-photos",
        base_url="https://thanatos-id.github.io/Epcot-FnW",
        overrides_path=overrides_path,
    )

    written = json.loads(overrides_path.read_text())
    assert written["menu_items"][0]["image_url"] == (
        f"https://thanatos-id.github.io/Epcot-FnW/dish-photos/{public_id}.jpg"
    )


def test_import_raises_without_a_manifest(tmp_path):
    in_dir = tmp_path / "empty"
    in_dir.mkdir()

    with pytest.raises(RuntimeError, match="images export"):
        import_dish_photos(
            in_dir,
            publish_dir=tmp_path / "docs" / "dish-photos",
            base_url="https://thanatos-id.github.io/Epcot-FnW",
            overrides_path=tmp_path / "menu_items.json",
        )


def test_import_url_is_built_from_base_url_and_publish_dir_name(tmp_path):
    in_dir = tmp_path / "processed"
    public_id = "44444444-4444-4444-4444-444444444444"
    _write_manifest(
        in_dir,
        [
            {
                "public_id": public_id,
                "booth_name": "Japan",
                "dish_name": "Sushi Roll",
                "category": "food",
                "original_url": "https://cdn.test/sushi.jpg",
                "filename": f"{public_id}.jpg",
                "downloaded": True,
            }
        ],
    )
    (in_dir / f"{public_id}.jpg").write_bytes(b"bytes")

    overrides_path = tmp_path / "menu_items.json"
    import_dish_photos(
        in_dir,
        publish_dir=tmp_path / "docs" / "custom-photos-dir",
        base_url="https://example.org/site/",
        overrides_path=overrides_path,
    )

    written = json.loads(overrides_path.read_text())
    assert written["menu_items"][0]["image_url"] == (
        f"https://example.org/site/custom-photos-dir/{public_id}.jpg"
    )


# ---------------------------------------------------------------------------
# merge_menu_item_overrides: overwrite toggle, exercised directly since this
# is now a shared utility rather than private to one caller
# ---------------------------------------------------------------------------


def test_merge_menu_item_overrides_overwrite_false_leaves_existing_value(tmp_path):
    path = tmp_path / "menu_items.json"
    path.write_text(
        json.dumps({"menu_items": [{"booth_name": "Germany", "name": "Torte", "image_url": "old.jpg"}]})
    )

    merge_menu_item_overrides(
        path, [{"booth_name": "Germany", "name": "Torte", "image_url": "new.jpg"}], overwrite=False
    )

    written = json.loads(path.read_text())
    assert written["menu_items"][0]["image_url"] == "old.jpg"


def test_merge_menu_item_overrides_overwrite_true_replaces_existing_value(tmp_path):
    path = tmp_path / "menu_items.json"
    path.write_text(
        json.dumps({"menu_items": [{"booth_name": "Germany", "name": "Torte", "image_url": "old.jpg"}]})
    )

    merge_menu_item_overrides(
        path, [{"booth_name": "Germany", "name": "Torte", "image_url": "new.jpg"}], overwrite=True
    )

    written = json.loads(path.read_text())
    assert written["menu_items"][0]["image_url"] == "new.jpg"


def test_merge_menu_item_overrides_preserves_readme_and_adds_new_entries(tmp_path):
    path = tmp_path / "menu_items.json"
    path.write_text(json.dumps({"_README": ["kept"], "menu_items": []}))

    merge_menu_item_overrides(
        path, [{"booth_name": "Norway", "name": "Kringle", "image_url": "kringle.jpg"}], overwrite=True
    )

    written = json.loads(path.read_text())
    assert written["_README"] == ["kept"]
    assert written["menu_items"] == [
        {"booth_name": "Norway", "name": "Kringle", "image_url": "kringle.jpg"}
    ]
