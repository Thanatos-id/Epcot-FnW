"""End-to-end: a dish photo published on a per-booth photo post has to end up
attached to the menu item the hub page already created for that dish.

Nothing in the adapter matches captions to dishes. The detail page emits a
menu_item record whose name *is* the caption, and ordinary entity resolution
does the rest: candidates scoped to the booth, fuzzy-matched, merged when
confident. These tests exercise that path rather than the adapter in
isolation, because the interesting behaviour lives in the seam.

"Kirschwasser Torte" is used as the worked example because it survives hub
ingest as its own row. The two raclette dishes on that menu ("Warm Raclette
Swiss Cheese" and "... and Alpine Ham") are close enough that the resolver
auto-merges them into one item, which makes them a poor fixture for asserting
*which* row a photo landed on.
"""

from pathlib import Path

from sqlalchemy import select

from epcot_fw.db.models import Booth, EntityFieldProvenance, MenuItem, MergeConflict
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.disney_food_blog import BASE_URL, DisneyFoodBlogAdapter

from ._helpers import ingest

HUB_FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures/html_snapshots/disney_food_blog/booth_menus_hub.html"
)
ALPS_URL = f"{BASE_URL}/the-alps-2025-epcot-food-and-wine-festival/"
TORTE = "Kirschwasser Torte"
TORTE_PHOTO = "https://www.disneyfoodblog.com/wp-content/uploads/2025/08/torte.jpg"


def _detail_html(*captioned: tuple[str, str]) -> str:
    figures = "".join(
        f'<figure><img src="{url}" /><figcaption>{caption}</figcaption></figure>'
        for caption, url in captioned
    )
    return f"<html><body><article><h1>The Alps</h1>{figures}</article></body></html>"


def _ingest_hub(db_session, festival_id):
    dtos = DisneyFoodBlogAdapter().parse(
        HUB_FIXTURE.read_text(), f"{BASE_URL}/hub/", "booth_list"
    )
    ingest(db_session, dtos, "disney_food_blog", festival_id, url=f"{BASE_URL}/hub/")


def _ingest_detail(db_session, festival_id, html, url=ALPS_URL):
    dtos = DisneyFoodBlogAdapter().parse(html, url, "booth_detail")
    ingest(db_session, dtos, "disney_food_blog", festival_id, url=url)


def _booth(db_session, like):
    return db_session.scalars(select(Booth).where(Booth.canonical_name.ilike(like))).first()


def _item(db_session, booth_id, name):
    return db_session.scalars(
        select(MenuItem).where(MenuItem.booth_id == booth_id, MenuItem.canonical_name == name)
    ).first()


def test_photo_attaches_to_the_dish_the_hub_already_created(db_session):
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")

    before = _item(db_session, alps.id, TORTE)
    assert before is not None and before.image_url is None
    item_id = before.id
    total_before = len(db_session.scalars(select(MenuItem)).all())

    _ingest_detail(db_session, festival_id, _detail_html((TORTE, TORTE_PHOTO)))

    assert db_session.get(MenuItem, item_id).image_url == TORTE_PHOTO
    assert len(db_session.scalars(select(MenuItem)).all()) == total_before, (
        "matching a known dish must not create a duplicate menu item"
    )


def test_photo_attachment_is_recorded_as_provenance(db_session):
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    item_id = _item(db_session, alps.id, TORTE).id

    _ingest_detail(db_session, festival_id, _detail_html((TORTE, TORTE_PHOTO)))

    rows = db_session.scalars(
        select(EntityFieldProvenance).where(
            EntityFieldProvenance.entity_type == "menu_item",
            EntityFieldProvenance.canonical_id == item_id,
            EntityFieldProvenance.field_name == "image_url",
        )
    ).all()
    assert [r.value for r in rows] == [TORTE_PHOTO]
    assert rows[0].is_selected is True


def test_a_caption_close_enough_to_a_known_dish_still_matches_it(db_session):
    """Captions are rarely byte-identical to the menu listing - this is the
    whole reason matching is fuzzy rather than exact."""
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    item_id = _item(db_session, alps.id, TORTE).id

    _ingest_detail(db_session, festival_id, _detail_html(("Kirschwasser Torte!", TORTE_PHOTO)))

    assert db_session.get(MenuItem, item_id).image_url == TORTE_PHOTO


def test_caption_for_an_unlisted_dish_becomes_a_new_item_with_its_photo(db_session):
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    photo = "https://ex.test/secret-menu.jpg"

    _ingest_detail(
        db_session, festival_id, _detail_html(("Limited Time Truffle Fondue Pot", photo))
    )

    created = _item(db_session, alps.id, "Limited Time Truffle Fondue Pot")
    assert created is not None
    assert created.image_url == photo


# ---------------------------------------------------------------------------
# review posts: attach only, never create
# ---------------------------------------------------------------------------


def _review_html(*captioned: tuple[str, str]) -> str:
    """A 2026-shape review post: no booth in the slug, a newsletter <h1>, and
    the booth recoverable only from the image filenames."""
    figures = "".join(
        f'<figure><img src="{url}" /><figcaption>{caption}</figcaption></figure>'
        for caption, url in captioned
    )
    return f"<html><body><article><h1>Get the DFB Newsletter</h1>{figures}</article></body></html>"


def _alps_photo(slug: str) -> str:
    return (
        "https://www.disneyfoodblog.com/wp-content/uploads/2026/08/"
        f"2026-Disney-World-WDW-EPCOT-Food-and-Wine-Festival-The-Alps-Booth-{slug}-700x525.jpg"
    )


def _ingest_review(db_session, festival_id, html):
    url = f"{BASE_URL}/2026/08/27/review-a-booth-that-keeps-it-simple/"
    dtos = DisneyFoodBlogAdapter().parse(html, url, "booth_review")
    ingest(db_session, dtos, "disney_food_blog", festival_id, url=url)


def test_a_review_posts_photo_attaches_to_the_dish_the_hub_created(db_session):
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    assert _item(db_session, alps.id, TORTE).image_url is None

    _ingest_review(db_session, festival_id, _review_html(
        (TORTE, _alps_photo("Kirschwasser-Torte")),
        ("Full Spread", _alps_photo("spread")),
    ))

    assert _item(db_session, alps.id, TORTE).image_url == _alps_photo("Kirschwasser-Torte")


def test_a_reviews_chatty_caption_does_not_become_a_dish(db_session):
    """The whole reason these records are attach_only. A review captions the
    booth sign and the writer's asides in the same markup as the food, and
    those match no dish - which the matcher would otherwise read as a menu of
    brand-new items, once per post, all season."""
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    before = len(db_session.scalars(select(MenuItem).where(MenuItem.booth_id == alps.id)).all())

    _ingest_review(db_session, festival_id, _review_html(
        ("A closer look", _alps_photo("closer")),
        ("Full Spread", _alps_photo("spread")),
        ("Is it still reliably good?", _alps_photo("good")),
        ("The Alps Booth", _alps_photo("atmo")),
    ))

    after = db_session.scalars(select(MenuItem).where(MenuItem.booth_id == alps.id)).all()
    assert len(after) == before, [i.canonical_name for i in after]
    for junk in ("A closer look", "Full Spread", "Is it still reliably good?"):
        assert _item(db_session, alps.id, junk) is None


def test_an_unmatched_review_caption_does_not_pile_up_conflicts(db_session):
    """A caption that turned out to be a photo of the queue is not something
    a human should be asked to adjudicate."""
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    before = len(db_session.scalars(select(MergeConflict)).all())

    _ingest_review(db_session, festival_id, _review_html(
        ("Full Spread", _alps_photo("spread")),
        ("A closer look", _alps_photo("closer")),
    ))

    assert len(db_session.scalars(select(MergeConflict)).all()) == before


def test_a_review_of_somewhere_that_is_not_a_festival_booth_is_dropped_quietly(db_session):
    """The festival tag's feed carries reviews of permanent kiosks - Block &
    Hans, Funnel Cakes - which are not booths on this menu. That is a post
    about somewhere else, not an unresolved dish for a human to look at."""
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    before = len(db_session.scalars(select(MergeConflict)).all())

    photo = (
        "https://www.disneyfoodblog.com/wp-content/uploads/2026/08/"
        "2026-Disney-World-WDW-EPCOT-Food-and-Wine-Festival-Block-and-Hans-Booth-Beer-700x525.jpg"
    )
    _ingest_review(db_session, festival_id, _review_html(("Spicy Strawberry-Mango Smoothie", photo)))

    assert len(db_session.scalars(select(MergeConflict)).all()) == before


def test_a_review_whose_photos_name_no_booth_ingests_nothing(db_session):
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    before = len(db_session.scalars(select(MenuItem)).all())

    _ingest_review(db_session, festival_id, _review_html(
        (TORTE, "https://www.disneyfoodblog.com/wp-content/uploads/2026/08/mystery-photo.jpg"),
    ))

    assert len(db_session.scalars(select(MenuItem)).all()) == before


def test_a_photo_never_overwrites_an_existing_dish_name_or_price(db_session):
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    before = _item(db_session, alps.id, TORTE)
    price_before, name_before = before.price_usd, before.canonical_name

    _ingest_detail(db_session, festival_id, _detail_html((TORTE, TORTE_PHOTO)))

    after = db_session.get(MenuItem, before.id)
    assert after.canonical_name == name_before
    assert after.price_usd == price_before
    assert after.image_url == TORTE_PHOTO


def test_reingesting_the_same_photo_post_is_idempotent(db_session):
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    html = _detail_html((TORTE, TORTE_PHOTO))
    _ingest_detail(db_session, festival_id, html)

    def counts():
        return (
            len(db_session.scalars(select(MenuItem)).all()),
            len(
                db_session.scalars(
                    select(MergeConflict).where(MergeConflict.status == "open")
                ).all()
            ),
        )

    first = counts()
    _ingest_detail(db_session, festival_id, html, url=ALPS_URL + "?again")
    assert counts() == first


def test_a_later_crawl_can_photograph_a_dish_that_had_none(db_session):
    """The whole point of re-crawling: photos appear after the menus do."""
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    torte_id = _item(db_session, alps.id, TORTE).id
    frozen = _item(db_session, alps.id, "Frozen Rosé — $9.50")

    _ingest_detail(db_session, festival_id, _detail_html((TORTE, TORTE_PHOTO)))
    assert db_session.get(MenuItem, torte_id).image_url == TORTE_PHOTO
    assert db_session.get(MenuItem, frozen.id).image_url is None

    _ingest_detail(
        db_session,
        festival_id,
        _detail_html(("Frozen Rosé", "https://ex.test/rose.jpg")),
        url=ALPS_URL + "?pass2",
    )

    assert db_session.get(MenuItem, frozen.id).image_url == "https://ex.test/rose.jpg"
    assert db_session.get(MenuItem, torte_id).image_url == TORTE_PHOTO, (
        "an earlier photo must survive a later crawl"
    )


def test_photos_are_scoped_to_their_own_booth(db_session):
    """A caption is only matched against dishes from the same booth, so a
    photo posted under one booth can never be pinned onto an identically
    named dish belonging to another."""
    festival_id = db_session.info["festival_id"]
    _ingest_hub(db_session, festival_id)
    alps = _booth(db_session, "%alps%")
    torte_id = _item(db_session, alps.id, TORTE).id

    dtos = [
        ExtractedRecordDTO(
            entity_type="menu_item",
            natural_key_hint="kirschwasser torte",
            payload={
                "booth_name": "Australia",
                "name": TORTE,
                "image_url": "https://ex.test/wrong-booth.jpg",
            },
        )
    ]
    ingest(db_session, dtos, "disney_food_blog", festival_id, url=f"{BASE_URL}/australia/")

    assert db_session.get(MenuItem, torte_id).image_url != "https://ex.test/wrong-booth.jpg"


def test_a_booth_payloads_image_url_is_never_resolved_onto_the_booth(db_session):
    """AllEars is the only adapter that puts a photo on a *booth* payload
    (the header image on its listing page) - the app has no use for a booth
    photo, only a dish's own. FIELD_MAP["booth"] deliberately has no
    "image_url" entry, so this can never reach Booth.image_url, from AllEars
    or any future source that starts doing the same thing."""
    festival_id = db_session.info["festival_id"]
    dtos = [
        ExtractedRecordDTO(
            entity_type="booth",
            natural_key_hint="germany",
            payload={
                "name": "Germany",
                "category": "global_marketplace",
                "image_url": "https://ex.test/germany-booth-header.jpg",
            },
        )
    ]
    ingest(db_session, dtos, "allears", festival_id, url="https://allears.test/germany/")

    booth = _booth(db_session, "%germany%")
    assert booth is not None
    assert booth.image_url is None
