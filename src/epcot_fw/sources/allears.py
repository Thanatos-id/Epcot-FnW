import copy
import datetime
import re

from bs4 import Tag

from epcot_fw.normalize.dietary_tags import extract_dietary_tags
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.html_utils import clean_text, soupify
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter

BASE_URL = "https://allears.net"
BOOTH_HUB_PATH = "/epcot-international-food-and-wine-festival-menus-and-food-photos/"
# Reader reviews of "the festival's food booths" as a whole (not one page per
# booth - see _attach reviews via booth-name mention in resolve/reviews.py).
# Paginated at ~10/page; 4 pages exist as of this writing (37 reviews) - a
# small buffer beyond that is harmless, an empty page just yields 0 records.
BOOTH_REVIEWS_PATH = "/reviews/impressions-food-booths/"
REVIEW_PAGE_COUNT = 6

_REVIEW_CARD_ID_RE = re.compile(r"^reviewCardDetail__(\d+)$")
_RATING_RE = re.compile(r"Rating:\s*\((\d+)\)")
_REVIEW_DATE_RE = re.compile(r"Review Date:\s*(\d{2}/\d{2}/\d{4})")


def _is_booth_boundary(p: Tag) -> bool:
    """AllEars marks each booth section start with <p><strong><a name="..."/>
    BoothName</strong></p> - a named anchor inside a <p>."""
    return p.name == "p" and p.find("a", attrs={"name": True}) is not None


def _boundary_name(p: Tag) -> str:
    """Extract the booth name text from a boundary <p>, stripped of any real
    links. Two real-world wrinkles in this page's HTML rule out simpler
    approaches:
      - A couple of boundary paragraphs carry a stray, textless
        `<a href="#top">RETURN TO TOP</a>` from an orphaned anchor - reading
        the whole <p>'s text would wrongly pick that up as the booth name.
      - At least one booth's name is split across two sibling <strong> tags
        (`<strong><a name="germany"/>G</strong><strong>ermany</strong>`) -
        so grabbing only the first <strong> truncates it to "G".
    Stripping just the href-bearing <a> tags and reading the rest of the
    paragraph's text handles both.
    """
    clone = copy.deepcopy(p)
    for link in clone.find_all("a", href=True):
        link.decompose()
    return clean_text(clone.get_text())


def _boundary_image(boundary_p: Tag) -> str | None:
    """Each booth section on this page opens with a <figure><img> of the
    physical menu board, before the "Food Items:"/"Beverages:" lists. Walk
    forward only up to that point - the page also has a second, unrelated
    "full spread" photo later in each section, and grabbing the first image
    found keeps this deterministic and tied to this specific booth."""
    node = boundary_p.next_sibling
    while node is not None:
        if isinstance(node, Tag):
            if _is_booth_boundary(node):
                return None
            if node.name == "p":
                label = clean_text(node.get_text()).rstrip(":").lower()
                if label in ("food items", "beverages"):
                    return None
            if node.name == "figure":
                img = node.find("img")
                if img and img.get("src"):
                    return img["src"]
        node = node.next_sibling
    return None


class AllEarsAdapter(SourceAdapter):
    key = "allears"
    priority_rank = 4

    def seed_urls(self, festival_year: int) -> list[SeedUrl]:
        seeds = [SeedUrl(url=f"{BASE_URL}{BOOTH_HUB_PATH}", page_kind="booth_list")]
        seeds.append(SeedUrl(url=f"{BASE_URL}{BOOTH_REVIEWS_PATH}", page_kind="booth_reviews"))
        for page in range(2, REVIEW_PAGE_COUNT + 1):
            seeds.append(
                SeedUrl(url=f"{BASE_URL}{BOOTH_REVIEWS_PATH}page/{page}/", page_kind="booth_reviews")
            )
        return seeds

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        if page_kind == "booth_reviews":
            return self._parse_reviews(raw_html, url)
        return self._parse_booth_list(raw_html)

    def _parse_reviews(self, raw_html: str, url: str) -> list[ExtractedRecordDTO]:
        soup = soupify(raw_html)
        records: list[ExtractedRecordDTO] = []

        for card in soup.find_all("div", id=_REVIEW_CARD_ID_RE):
            match = _REVIEW_CARD_ID_RE.match(card["id"])
            external_review_id = match.group(1)

            h2 = card.find("h2")
            h3 = card.find("h3")
            body = card.find("p")
            if h3 is None or body is None:
                continue

            reviewer_link = h2.find("a") if h2 else None
            reviewer_name = clean_text(reviewer_link.get_text()) if reviewer_link else None

            date_match = _REVIEW_DATE_RE.search(h2.get_text(" ")) if h2 else None
            reviewed_at = None
            if date_match:
                try:
                    reviewed_at = datetime.datetime.strptime(date_match.group(1), "%m/%d/%Y").date()
                except ValueError:
                    reviewed_at = None

            h3_text = h3.get_text(" ")
            rating_match = _RATING_RE.search(h3_text)
            if not rating_match:
                continue  # no numeric rating on this card - nothing usable to extract
            rating_raw = int(rating_match.group(1))
            recommended = "not recommended" not in h3_text.lower()

            review_text = clean_text(body.get_text())
            if not review_text:
                continue

            records.append(
                ExtractedRecordDTO(
                    entity_type="review",
                    natural_key_hint=f"allears-review-{external_review_id}",
                    payload={
                        "external_review_id": external_review_id,
                        "reviewer_name": reviewer_name,
                        "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
                        "rating_raw": rating_raw,
                        "rating_scale": 10,
                        "recommended": recommended,
                        "review_text": review_text,
                        "review_url": f"{BASE_URL}{BOOTH_REVIEWS_PATH}",
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
            booth_name = _boundary_name(boundary_p)
            if not booth_name or len(booth_name) > 80:
                continue

            records.append(
                ExtractedRecordDTO(
                    entity_type="booth",
                    natural_key_hint=normalize_name(booth_name),
                    payload={
                        "name": booth_name,
                        "category": "global_marketplace",
                        "image_url": _boundary_image(boundary_p),
                    },
                )
            )

            current_category: str | None = None
            node = boundary_p.next_sibling
            while node is not None:
                if isinstance(node, Tag):
                    if _is_booth_boundary(node):
                        break  # reached the next booth section
                    if node.name == "p":
                        label = clean_text(node.get_text()).rstrip(":").lower()
                        if label == "food items":
                            current_category = "food"
                        elif label == "beverages":
                            current_category = "beverage"
                    elif node.name == "ul" and current_category:
                        for li in node.find_all("li"):
                            item_text = clean_text(li.get_text())
                            if not item_text:
                                continue
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
                                    natural_key_hint=normalize_name(item_text[:80]),
                                    payload={
                                        "booth_name": booth_name,
                                        "name": item_text,
                                        "description": None,
                                        "category": category,
                                        "price_usd": None,
                                        "dietary_tags": tags,
                                    },
                                )
                            )
                node = node.next_sibling

        return records
