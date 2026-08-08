import re

from bs4 import Tag

from epcot_fw.normalize.dietary_tags import extract_dietary_tags
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.html_utils import all_prices, clean_text, soupify
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter

BASE_URL = "https://www.disneyfoodblog.com"
# DFB republishes a fresh dated hub page each year; the undated slug is kept as
# a stable redirect/landing entry point alongside it.
BOOTH_HUB_PATH = "/epcot-food-and-wine-festival-booths-menus-and-food-photos/"

_CLICK_TO_SEE_RE = re.compile(r"click to see photos", re.IGNORECASE)


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

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
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
