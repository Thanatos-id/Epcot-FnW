import copy

from bs4 import Tag

from epcot_fw.normalize.dietary_tags import extract_dietary_tags
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.html_utils import clean_text, soupify
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter

BASE_URL = "https://allears.net"
BOOTH_HUB_PATH = "/epcot-international-food-and-wine-festival-menus-and-food-photos/"


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
        return [SeedUrl(url=f"{BASE_URL}{BOOTH_HUB_PATH}", page_kind="booth_list")]

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        return self._parse_booth_list(raw_html)

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
