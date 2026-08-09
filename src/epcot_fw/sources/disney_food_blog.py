import datetime
import re

from bs4 import Tag

from epcot_fw.normalize.dietary_tags import extract_dietary_tags
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.html_utils import all_prices, clean_text, soupify
from epcot_fw.parse.images import extract_captioned_images
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter

BASE_URL = "https://www.disneyfoodblog.com"
# DFB republishes a fresh dated hub page each year; the undated slug is kept as
# a stable redirect/landing entry point alongside it.
BOOTH_HUB_PATH = "/epcot-food-and-wine-festival-booths-menus-and-food-photos/"

_CLICK_TO_SEE_RE = re.compile(r"click to see photos", re.IGNORECASE)

# /the-alps-2025-epcot-food-and-wine-festival/     -> "the alps"
# /australia-2025-epcot-food-and-wine-festival-2/  -> "australia"  (WordPress
# appends -2 when a slug collides with a previous year's post)
_DETAIL_SLUG_RE = re.compile(
    r"^(?P<booth>.+?)-\d{4}-epcot-food-and-wine-festival(?:-\d+)?$", re.IGNORECASE
)


def _booth_name_from_detail(soup: Tag, url: str) -> str | None:
    """Booth name for a per-booth photo post, taken from its slug.

    The slug is used in preference to the page's <h1> because it is a stable,
    machine-generated string, whereas the visible title carries editorial
    decoration ("The Alps - 2025 EPCOT Food & Wine Festival - PHOTOS!") that
    would have to be stripped heuristically. Punctuation lost in slugification
    ("Brew-Wing Lab" -> "brew wing lab") is irrelevant here: this name is only
    ever consumed through normalize_name(), which strips punctuation anyway.
    """
    from urllib.parse import urlparse

    slug = urlparse(url).path.strip("/").rsplit("/", 1)[-1]
    match = _DETAIL_SLUG_RE.match(slug)
    if match:
        return match.group("booth").replace("-", " ").strip().title() or None

    heading = soup.find("h1")
    if heading is not None:
        text = clean_text(heading.get_text())
        if text and len(text) <= 80:
            return text
    return None


def _is_booth_boundary(p: Tag) -> bool:
    return p.name == "p" and bool(_CLICK_TO_SEE_RE.search(p.get_text()))


class DisneyFoodBlogAdapter(SourceAdapter):
    key = "disney_food_blog"
    priority_rank = 6

    def seed_urls(self, festival_year: int) -> list[SeedUrl]:
        return [
            SeedUrl(url=f"{BASE_URL}{BOOTH_HUB_PATH}", page_kind="booth_list"),
            SeedUrl(
                url=f"{BASE_URL}/{festival_year}-epcot-food-and-wine-festival-booths-menus-and-food-photos/",
                page_kind="booth_list",
            ),
        ]

    def discover_new_urls(self, since: datetime.datetime) -> list[SeedUrl]:
        """The per-booth "CLICK TO SEE PHOTOS OF MENU ITEMS" posts, one per
        booth, scraped off the hub page.

        These carry the individual dish photos; the hub itself has none. The
        slugs are year- and booth-specific (`/the-alps-2025-epcot-food-and-
        wine-festival/`) so they can't be enumerated ahead of time, which is
        why they're discovered rather than declared in seed_urls().

        `since` is deliberately ignored: these posts are edited in place as
        photos get added over the season rather than republished with a new
        date, so filtering by publish date would freeze out exactly the
        updates worth re-fetching. Re-listing them every run is cheap - the
        conditional-GET and content-hash checks in fetch/cache.py mean an
        unchanged post costs a 304 and is never reparsed.
        """
        from epcot_fw.fetch.http_client import fetch

        result = fetch(f"{BASE_URL}{BOOTH_HUB_PATH}", crawl_delay_sec=5)
        if result.not_modified or not result.text:
            return []
        return self._detail_seeds(result.text)

    def _detail_seeds(self, raw_html: str) -> list[SeedUrl]:
        soup = soupify(raw_html)
        article = soup.find("article") or soup
        seeds: list[SeedUrl] = []
        seen: set[str] = set()

        for boundary_p in (p for p in article.find_all("p") if _is_booth_boundary(p)):
            link = boundary_p.find("a", href=True)
            if link is None:
                continue
            href = link["href"]
            if not href.startswith("http"):
                href = f"{BASE_URL}{href}"
            if href in seen:
                continue
            seen.add(href)
            seeds.append(SeedUrl(url=href, page_kind="booth_detail"))

        return seeds

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        if page_kind == "booth_detail":
            return self._parse_booth_detail(raw_html, url)
        return self._parse_booth_list(raw_html)

    def _parse_booth_detail(self, raw_html: str, url: str) -> list[ExtractedRecordDTO]:
        """One booth's photo post -> a menu_item record per captioned dish photo.

        No caption-to-dish matching happens here on purpose. Each record is
        emitted with the caption as its name, and normal entity resolution
        takes it from there: candidates are scoped to this booth and matched
        fuzzily, so a caption that clearly names a dish already known from the
        hub page merges into it (attaching the photo), a borderline one is
        parked as a merge conflict rather than pinning a photo to the wrong
        dish, and a caption for a dish the hub never listed becomes a new item.
        """
        soup = soupify(raw_html)
        article = soup.find("article") or soup
        booth_name = _booth_name_from_detail(soup, url)
        if not booth_name:
            return []

        records: list[ExtractedRecordDTO] = []
        for image in extract_captioned_images(article):
            records.append(
                ExtractedRecordDTO(
                    entity_type="menu_item",
                    natural_key_hint=normalize_name(image.caption[:80]),
                    payload={
                        "booth_name": booth_name,
                        "name": image.caption,
                        "image_url": image.url,
                    },
                )
            )
        return records

    def _parse_booth_list(self, raw_html: str) -> list[ExtractedRecordDTO]:
        soup = soupify(raw_html)
        article = soup.find("article") or soup
        records: list[ExtractedRecordDTO] = []

        boundary_ps = [p for p in article.find_all("p") if _is_booth_boundary(p)]

        for boundary_p in boundary_ps:
            link = boundary_p.find("a")
            booth_name = clean_text(link.get_text()) if link else clean_text(
                boundary_p.get_text().split("<")[0]
            )
            if not booth_name or len(booth_name) > 80:
                continue

            records.append(
                ExtractedRecordDTO(
                    entity_type="booth",
                    natural_key_hint=normalize_name(booth_name),
                    payload={"name": booth_name, "category": "global_marketplace"},
                )
            )

            current_category: str | None = None
            node = boundary_p.next_sibling
            while node is not None:
                if isinstance(node, Tag):
                    if _is_booth_boundary(node):
                        break
                    if node.name == "p":
                        label = clean_text(node.get_text()).rstrip(":").lower()
                        if label == "food":
                            current_category = "food"
                        elif label == "beverages":
                            current_category = "beverage"
                    elif node.name in ("ul", "div") and current_category:
                        ul = node if node.name == "ul" else node.find("ul")
                        if ul:
                            for li in ul.find_all("li"):
                                item_text = clean_text(li.get_text())
                                if not item_text:
                                    continue
                                name_tag = li.find("strong")
                                item_name = (
                                    clean_text(name_tag.get_text()) if name_tag else item_text
                                )
                                prices = all_prices(item_text)
                                price = min(prices) if prices else None
                                tags = extract_dietary_tags(item_text)
                                category = current_category
                                if category == "beverage":
                                    category = (
                                        "alcoholic_beverage"
                                        if "contains_alcohol" in tags
                                        else "non_alcoholic_beverage"
                                    )
                                records.append(
                                    ExtractedRecordDTO(
                                        entity_type="menu_item",
                                        natural_key_hint=normalize_name(item_name[:80]),
                                        payload={
                                            "booth_name": booth_name,
                                            "name": item_name,
                                            "description": item_text,
                                            "category": category,
                                            "price_usd": str(price) if price else None,
                                            "dietary_tags": tags,
                                        },
                                    )
                                )
                node = node.next_sibling

        return records
