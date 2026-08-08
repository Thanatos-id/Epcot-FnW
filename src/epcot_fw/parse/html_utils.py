import json
import re
from collections.abc import Callable, Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup, Tag

PRICE_RE = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")


def soupify(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def find_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Return all parseable JSON-LD blobs on the page. Prefer this over CSS
    scraping when present - it's far more robust to layout/theme changes."""
    out: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def first_price(text: str) -> Decimal | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def all_prices(text: str) -> list[Decimal]:
    prices = []
    for match in PRICE_RE.finditer(text):
        try:
            prices.append(Decimal(match.group(1)))
        except InvalidOperation:
            continue
    return prices


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def iter_sections(
    start_after: Tag, is_boundary: Callable[[Tag], bool]
) -> Iterator[list[Tag]]:
    """Walk sibling tags after `start_after`, yielding groups of tags between
    successive elements matched by `is_boundary` (e.g. one group of tags per
    booth heading found on a page)."""
    current: list[Tag] = []
    node = start_after.next_sibling
    started = False
    while node is not None:
        if isinstance(node, Tag):
            if is_boundary(node):
                if started:
                    yield current
                current = [node]
                started = True
            elif started:
                current.append(node)
        node = node.next_sibling
    if started and current:
        yield current
