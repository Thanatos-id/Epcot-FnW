"""Pull captioned photos out of a page.

Blog sources publish dish photos as captioned figures, and the caption is
almost always the dish name ("Warm Raclette Swiss Cheese"). That makes the
caption the join key back to a menu item - see
sources/disney_food_blog.py, which turns these pairs into menu_item records
and lets the normal resolver fuzzy-match them onto dishes already known for
the booth.

A caption is *required*. Every uncaptioned <img> on these pages is site
furniture - header banners, newsletter-signup graphics, affiliate buttons,
tracking pixels - so requiring a caption is both the cheapest and the most
reliable filter available, and it costs nothing: an image with no caption
could not be matched to a dish anyway.
"""

import re
from dataclasses import dataclass

from bs4 import Tag

# Substrings that appear in the src of non-editorial images on these sites
# (ad units, mailing-list widgets, product buttons). Matched case-insensitively
# against the URL.
_JUNK_SRC_RE = re.compile(
    r"(aweber|leadbox|lpages|doubleclick|googlesyndication|/ads?/|"
    r"homepage-button|guide-cover|banner|logo|icon|avatar|gravatar|spacer|pixel)",
    re.IGNORECASE,
)

# Captions that are boilerplate rather than a dish name.
_JUNK_CAPTION_RE = re.compile(
    r"^(click|photo credit|advertisement|sponsored|read more|shop|buy)\b", re.IGNORECASE
)

MIN_CAPTION_LEN = 3
MAX_CAPTION_LEN = 160
# Below this, an image is a UI sprite rather than a photograph. Only applied
# when the markup actually declares a size.
MIN_DIMENSION = 120


@dataclass(frozen=True)
class CaptionedImage:
    url: str
    caption: str


def _declared_dimension(img: Tag, attr: str) -> int | None:
    raw = img.get(attr)
    if raw is None:
        return None
    try:
        return int(str(raw).strip().rstrip("px"))
    except ValueError:
        return None


def _too_small(img: Tag) -> bool:
    for attr in ("width", "height"):
        value = _declared_dimension(img, attr)
        if value is not None and value < MIN_DIMENSION:
            return True
    return False


def _best_src(img: Tag) -> str | None:
    """Prefer a real src, falling back to lazy-loading attributes.

    WordPress image lazy-loaders leave src empty (or pointing at a placeholder)
    and stash the real URL in data-src / data-lazy-src, so reading only src
    would silently drop those photos.
    """
    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
        value = img.get(attr)
        if value and not value.startswith("data:"):
            return value.strip()
    return None


def _caption_text(figure: Tag) -> str | None:
    node = figure.find("figcaption")
    if node is None:
        # Classic WordPress caption shortcode markup, still emitted by older
        # themes and by the block editor's "legacy" output.
        node = figure.find(class_="wp-caption-text")
    if node is None:
        return None
    text = " ".join(node.get_text(" ").split())
    return text or None


def _captioned_containers(container: Tag) -> list[Tag]:
    seen: list[Tag] = []
    for node in container.find_all(["figure", "div"]):
        if node.name == "div" and "wp-caption" not in (node.get("class") or []):
            continue
        seen.append(node)
    return seen


def extract_captioned_images(container: Tag) -> list[CaptionedImage]:
    """Captioned photos in document order, de-duplicated by URL.

    De-duplication keeps the first caption for a repeated image: these posts
    often re-show a hero shot at the bottom, and the first occurrence is the
    one sitting next to the dish it belongs to.
    """
    out: list[CaptionedImage] = []
    seen_urls: set[str] = set()

    for node in _captioned_containers(container):
        img = node.find("img")
        if img is None:
            continue

        url = _best_src(img)
        if not url or url in seen_urls:
            continue
        if _JUNK_SRC_RE.search(url) or _too_small(img):
            continue

        caption = _caption_text(node)
        if not caption:
            continue
        if not (MIN_CAPTION_LEN <= len(caption) <= MAX_CAPTION_LEN):
            continue
        if _JUNK_CAPTION_RE.match(caption):
            continue

        seen_urls.add(url)
        out.append(CaptionedImage(url=url, caption=caption))

    return out
