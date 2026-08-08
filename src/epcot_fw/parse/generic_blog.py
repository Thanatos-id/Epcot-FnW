import re

from bs4 import Tag

from epcot_fw.normalize.dietary_tags import extract_dietary_tags
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.html_utils import all_prices, clean_text
from epcot_fw.parse.schemas import ExtractedRecordDTO

_HEADING_TAGS = ("h2", "h3", "h4")
_NAME_SPLIT_RE = re.compile(r"\s*[—–\-:]\s*\$")


def extract_priced_items(article: Tag) -> list[ExtractedRecordDTO]:
    """Best-effort extraction for blog-style sources without a fixed template:
    walk the article tracking the nearest preceding heading as a "booth_name"
    guess, and treat any <li>/<p> containing a $price as a candidate menu item.

    This is intentionally lower-fidelity than the dedicated AllEars/Disney
    Food Blog adapters - it exists to catch content on sources (WDWMagic,
    Touring Plans, WDW Prep School, Disney Parks Blog) that don't publish a
    single consistently-templated booth/menu hub page. Results here are
    ordinary extracted_records like any other source; the resolver's source
    priority ranking (these sources rank below the two dedicated ones) is
    what keeps a shaky generic extraction from winning a field-level conflict
    against a higher-confidence source.
    """
    records: list[ExtractedRecordDTO] = []
    current_heading: str | None = None

    for el in article.find_all(_HEADING_TAGS + ("li", "p")):
        if el.name in _HEADING_TAGS:
            heading_text = clean_text(el.get_text())
            if heading_text and len(heading_text) < 80:
                current_heading = heading_text
            continue

        text = clean_text(el.get_text())
        if not text or len(text) > 300:
            continue
        prices = all_prices(text)
        if not prices:
            continue

        price = min(prices)
        name = _NAME_SPLIT_RE.split(text, maxsplit=1)[0].strip() or text[:80]
        tags = extract_dietary_tags(text)
        category = "alcoholic_beverage" if "contains_alcohol" in tags else "food"

        records.append(
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=normalize_name(name[:80]),
                payload={
                    "booth_name": current_heading,
                    "name": name,
                    "description": text,
                    "category": category,
                    "price_usd": str(price),
                    "dietary_tags": tags,
                },
            )
        )

    return records
