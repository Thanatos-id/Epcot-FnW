"""Dish photos for a file-backed festival, from Disney's own Foodie Guides.

Festival of the Holidays has no crawl behind it (see epcot_fw.festival_files),
so `backfill-images` - which searches Disney Food Blog's per-booth photo
posts - has nothing to attach to, and Disney Food Blog and AllEars now both
answer automated requests with a bot challenge, which this project does not
try to get past. Disney Parks Blog's "Disney Eats" Foodie Guide for the
festival is the better source anyway: an official photo of most dishes,
each with alt text naming the dish, laid out booth by booth.

The guide's layout is what the parser leans on: a run of dish photos, then
the "<Booth> Menu" heading they belong to. Each photo is therefore read as
belonging to the next "... Menu" heading, and its alt text - "Turkey
Poutine: Sweet potato fries with..." - as the dish.

The same rules as pipeline/image_backfill.py keep this from inventing
anything:

1. A photo only ever attaches to a dish already in the festival's
   menu_items.json. A photo of a dish that is not on the menu is reported
   and dropped.
2. The dish is matched within its booth at the pipeline's auto-merge
   confidence (resolve/matcher.AUTO_MERGE_THRESHOLD). A photo whose heading
   names no booth is matched across the whole menu, and only kept when
   exactly one dish clears the bar. Near misses are reported, not taken.
3. A photo already on a dish is never replaced, with one exception: one
   this command placed itself, when a newer season's guide has the same
   dish. That is the point of re-running it once the next guide is out.
   A photo published from the studio is never touched.

Photos are linked, not copied: `image_url` points at Disney Parks Blog, and
`image_source` records the credit, the season and the guide it came from,
in the shape pipeline/photo_source.py gives the database festival's dishes.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from epcot_fw.normalize.text import normalize_name
from epcot_fw.resolve.matcher import AUTO_MERGE_THRESHOLD, REVIEW_THRESHOLD, score_pair

logger = logging.getLogger(__name__)

VIA = "festival-photos"
# Credited by the host of the *guide*, not of the image: an archived guide's
# photos may be served by the Internet Archive, and are still Disney's.
PUBLISHERS = {
    "disneyparksblog.com": "Disney Parks Blog",
    "disneyparks.disney.go.com": "Disney Parks Blog",
}

# Disney rewrites one guide per festival in place each year, so last year's
# photos survive only in the Internet Archive's copies of the page. Those
# copies point every image at the Archive too; the original upload is
# usually still live, and is what gets linked when it is.
_ARCHIVE_RE = re.compile(r"\Ahttps?://web\.archive\.org/web/(?P<ts>\d+)[a-z_]*/(?P<orig>https?://.+)\Z")


def unwrap_archive(url: str) -> str:
    """The original URL inside an Internet Archive URL, or `url` unchanged."""
    match = _ARCHIVE_RE.match(url)
    return match["orig"] if match else url


def _absolute(src: str) -> str:
    # The Archive rewrites some image paths to be relative to itself.
    if src.startswith("/web/"):
        return "https://web.archive.org" + src
    if src.startswith("//"):
        return "https:" + src
    return src

_MENU_HEADING_RE = re.compile(r"\s+menu\s*$", re.IGNORECASE)
_NEW_PREFIX_RE = re.compile(r"^\s*new!?\s+", re.IGNORECASE)
# Where an alt text stops naming the dish and starts describing it.
_DESCRIPTION_SPLIT_RE = re.compile(r"\s*:\s+|\s+(?:with|featuring|topped with|sprinkled with)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class GuidePhoto:
    url: str
    alt: str
    heading: str | None  # the "... Menu" heading after it, without " Menu"


@dataclass(frozen=True)
class PhotoMatch:
    booth_name: str
    item_name: str
    url: str
    alt: str
    season: int
    page_url: str
    score: float


@dataclass
class PhotoReport:
    pages: list[str] = field(default_factory=list)
    photos_found: int = 0
    matched: list[PhotoMatch] = field(default_factory=list)
    replaced: list[PhotoMatch] = field(default_factory=list)
    kept_existing: list[PhotoMatch] = field(default_factory=list)
    near_misses: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def _src(img) -> str | None:
    for attr in ("src", "data-src", "data-lazy-src"):
        value = (img.get(attr) or "").strip()
        if value and not value.startswith("data:"):
            return _absolute(value)
    return None


def _text(node) -> str:
    return " ".join(node.get_text(" ").split())


_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?")


def parse_guide(html: str) -> list[GuidePhoto]:
    """Every dish photo with a name, tagged with the menu it belongs to.

    Disney has laid these guides out two ways, and a page can be read
    without knowing which:

    - **a run of photos, then its "... Menu" heading** (Holidays, Arts): a
      photo belongs to the next menu heading, and its alt text names the dish.
      The level of that heading moves between years (h3 in 2025, h4 in 2024,
      under a park-area heading that can fall between a photo and its menu),
      so only "... Menu" decides anything.
    - **a menu heading, then a card per dish** (Flower & Garden 2026): a
      photo inside a card belongs to the menu heading before it, and the
      card's own title names the dish - better than any alt text. Cards are
      repeated for phone and desktop; each photo is taken once.

    Reading stops at Kids Picks, which repeats dishes from earlier menus, and
    a photo after the last menu heading - the related-posts strip - is dropped.
    """
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup.find("main") or soup
    pending: list[tuple[str, str]] = []
    photos: list[GuidePhoto] = []
    seen: set[str] = set()
    current: str | None = None
    for node in article.find_all(["img", "h2", "h3", "h4", "p", "div"]):
        if "kids" in (node.get("id") or "").lower() or (
            node.name == "img" and "kids pick" in (node.get("alt") or "").lower()
        ):
            break
        if node.name == "div":
            continue  # only ever an anchor to stop at (Flower & Garden's #KidsPicks)
        card = node.find_parent(class_="card-container")
        if node.name == "img":
            src, alt = _src(node), " ".join((node.get("alt") or "").split())
            if not src or src.lower().endswith(".svg") or src in seen:
                continue
            title = card.find("h4") if card is not None else None
            if title is not None:
                if current:
                    seen.add(src)
                    name = _EMOJI_RE.sub("", _text(title)).strip()
                    photos.append(GuidePhoto(url=src, alt=name or alt, heading=current))
                continue
            if alt:
                pending.append((src, alt))
            continue
        if card is not None:
            continue
        text = _NEW_PREFIX_RE.sub("", _text(node))
        if node.name == "p" and (len(text) > 90 or "(" in text):
            continue
        if node.name != "h4" and re.search(r"\bkids\b", text, re.IGNORECASE) and len(text) < 90:
            break
        if _MENU_HEADING_RE.search(text):
            current = _MENU_HEADING_RE.sub("", text)
            for u, a in pending:
                seen.add(u)
                photos.append(GuidePhoto(url=u, alt=a, heading=current))
            pending = []
    return photos


def _dish_keys(alt: str) -> list[str]:
    """The alt text, and the alt text cut where the description starts."""
    keys = [alt]
    head = _DESCRIPTION_SPLIT_RE.split(alt, maxsplit=1)[0]
    if head and head != alt:
        keys.append(head)
    return [normalize_name(k) for k in keys if normalize_name(k)]


def _score(alt: str, dish_name: str) -> float:
    """0-100 for how surely `alt` names `dish_name`.

    Fuzzy similarity on the whole alt and on its name part, plus two rules
    that score exactly at the bar, so a genuine full match still outranks
    them:

    - the alt *starts with* the dish name: "Cheese Fondue in a bread bowl
      with...", "Crème de Saumon Fumé en Brioche aux Grains de Sesames...";
    - every word of the alt's name part is in the dish name, three words or
      more: the guide wrote "Holiday Sweater Liege Waffle" for the "Figment
      Holiday Sweater Liège Waffle".

    "Gingerbread Milk Shake with whipped cream vodka" names the spirited
    shake in full and the plain shake only as a prefix; both reach 100 on
    some key, and match_photos breaks the tie toward the longer name, so
    each gets its own photo.
    """
    dish = normalize_name(dish_name)
    keys = _dish_keys(alt)
    best = max((score_pair(k, dish) for k in keys), default=0.0)
    whole = keys[0] if keys else ""
    if dish and (whole == dish or whole.startswith(dish + " ")):
        best = max(best, AUTO_MERGE_THRESHOLD)
    head = set(keys[-1].split()) if keys else set()
    if len(head) >= 3 and head <= set(dish.split()):
        best = max(best, AUTO_MERGE_THRESHOLD)
    return best


def _ranked(alt: str, pool: list[dict[str, Any]]) -> list[tuple[float, int, dict[str, Any]]]:
    return sorted(
        ((_score(alt, i["name"]), len(i["name"]), i) for i in pool),
        key=lambda t: (t[0], t[1]),
        reverse=True,
    )


def _booth_for(heading: str | None, booth_names: list[str]) -> str | None:
    if not heading:
        return None
    key = normalize_name(heading)
    best, best_score = None, 0.0
    for name in booth_names:
        candidate = normalize_name(name)
        score = score_pair(key, candidate)
        # "Connections Café" is the start of "Connections Café & Eatery";
        # "Regal Eagle Smokehouse" the start of its long heading.
        if candidate.startswith(key + " ") or key.startswith(candidate + " "):
            score = max(score, AUTO_MERGE_THRESHOLD)
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= AUTO_MERGE_THRESHOLD else None


def match_photos(
    photos: list[GuidePhoto], items: list[dict[str, Any]], booth_names: list[str]
) -> tuple[list[tuple[GuidePhoto, dict[str, Any], float]], list[str], list[str]]:
    """(photo, dish entry, score) for each confident match, then near misses
    and photos matched to nothing, one line each."""
    active = [i for i in items if i.get("is_active") is not False]
    matches, near, none = [], [], []
    fallbacks: list[tuple[GuidePhoto, dict[str, Any], float, str]] = []
    for photo in photos:
        booth = _booth_for(photo.heading, booth_names)
        label = f"{photo.heading or '?'}: {photo.alt[:70]}"
        scored = _ranked(photo.alt, [i for i in active if i.get("booth_name") == booth]) if booth else []
        if scored and scored[0][0] >= AUTO_MERGE_THRESHOLD:
            matches.append((photo, scored[0][2], scored[0][0]))
            continue
        # Not on this booth's menu - or no booth at all. The guide sometimes
        # files a photo under the neighbouring heading (Block & Hans' slush
        # sits above Fife and Drum's), so look across the whole menu, and
        # take it only when one dish clearly beats every other.
        anywhere = _ranked(photo.alt, active)
        if anywhere and anywhere[0][0] >= AUTO_MERGE_THRESHOLD and (
            len(anywhere) == 1 or anywhere[0][0] > anywhere[1][0]
        ):
            fallbacks.append((photo, anywhere[0][2], anywhere[0][0], label))
            continue
        best = scored[0] if scored else (anywhere[0] if anywhere else None)
        if best is None or best[0] < REVIEW_THRESHOLD:
            none.append(label)
        else:
            near.append(f"{label} ~ {best[2]['name']} ({best[0]:.0f})")
    # A photo found in its own booth's section outranks one that only
    # matched from somewhere else: the guide mislabels the odd photo (2025
    # put a "Plant-based Chorizo Tamale" alt on Las Posadas' tamal), and
    # first-come would hand Nochebuena's dish the wrong picture.
    taken = {id(item) for _, item, _ in matches}
    for photo, item, score, label in fallbacks:
        if id(item) in taken:
            near.append(f"{label} ~ {item['name']} (already pictured in its own section)")
            continue
        taken.add(id(item))
        matches.append((photo, item, score))
    return matches, near, none


def _season_of(source: dict[str, Any] | None) -> int:
    try:
        return int((source or {}).get("season") or 0)
    except (TypeError, ValueError):
        return 0


def apply_photos(
    directory: Path,
    pages: list[dict[str, Any]],
    fetch_html,
    *,
    image_is_live=None,
    dry_run: bool = False,
) -> PhotoReport:
    """Fetch each guide in `pages` ({url, season}), match, and write.

    Newest season first, so an older guide only fills what a newer one left
    empty. `fetch_html(url) -> str | None` is injected so this is testable
    without the network, and so is `image_is_live(url) -> bool`, which
    decides whether an archived guide's photo links to Disney's original
    upload or, where that has gone, to the Archive's copy.
    """
    report = PhotoReport()
    items_path = directory / "menu_items.json"
    payload = json.loads(items_path.read_text())
    items: list[dict[str, Any]] = payload.get("menu_items") or []
    booths = json.loads((directory / "booths.json").read_text()).get("booths") or []
    booth_names = [b["name"] for b in booths if b.get("name") and b.get("is_active") is not False]

    claimed: set[int] = set()
    for page in sorted(pages, key=lambda p: int(p.get("season") or 0), reverse=True):
        url, season = page["url"], int(page.get("season") or 0)
        html = fetch_html(url)
        if not html:
            logger.warning("no page at %s", url)
            continue
        report.pages.append(url)
        photos = parse_guide(html)
        report.photos_found += len(photos)
        matches, near, none = match_photos(photos, items, booth_names)
        report.near_misses.extend(f"{season} {line}" for line in near)
        report.unmatched.extend(f"{season} {line}" for line in none)

        for photo, item, score in matches:
            hit = PhotoMatch(item["booth_name"], item["name"], photo.url, photo.alt, season, url, score)
            if id(item) in claimed:
                # A newer guide, or a better photo in this one, got it first.
                # Counted, so a past year that adds nothing says why.
                report.kept_existing.append(hit)
                continue
            existing = item.get("image_url")
            source = item.get("image_source") or {}
            ours = source.get("via") == VIA
            if existing and not (ours and _season_of(source) < season):
                report.kept_existing.append(hit)
                claimed.add(id(item))
                continue
            (report.replaced if existing else report.matched).append(hit)
            claimed.add(id(item))
            image_url = photo.url
            original = unwrap_archive(photo.url)
            if original != photo.url and (image_is_live is None or image_is_live(original)):
                image_url = original
            page_original = unwrap_archive(url)
            host = urlparse(page_original).netloc.lower().removeprefix("www.")
            item["image_url"] = image_url
            item["image_source"] = {
                "credit": PUBLISHERS.get(host, host),
                "site": host,
                "season": season,
                "page_url": page_original,
                "via": VIA,
            }
            if page_original != url:
                item["image_source"]["archived_at"] = url

    if not dry_run and (report.matched or report.replaced):
        items_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return report
