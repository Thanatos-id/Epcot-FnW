import datetime
import re
from collections import Counter
from urllib.parse import urljoin

from bs4 import Tag

from epcot_fw.normalize.dietary_tags import extract_dietary_tags
from epcot_fw.normalize.text import normalize_name
from epcot_fw.parse.html_utils import all_prices, clean_text, soupify
from epcot_fw.parse.images import extract_captioned_images
from epcot_fw.parse.schemas import ExtractedRecordDTO
from epcot_fw.sources.base import SeedUrl, SourceAdapter

BASE_URL = "https://www.disneyfoodblog.com"

# rss_discover() drops entries published before its `since`. This adapter
# wants the whole feed every run, so it passes a floor rather than a cutoff.
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)
# DFB republishes a fresh dated hub page each year; the undated slug is kept as
# a stable redirect/landing entry point alongside it.
BOOTH_HUB_PATH = "/epcot-food-and-wine-festival-booths-menus-and-food-photos/"

# The festival tag's feed. It is the only route to the 2026 review posts:
# the hub links none of them and their slugs can't be enumerated. It carries
# about ten entries, roughly four days of posting at festival pace, which is
# only full coverage because the refresh runs daily (see
# scripts/launchd/com.epcot.foodwine.refresh.plist). On a weekly schedule
# most of a season's posts would scroll off the feed unseen.
#
# Deliberately only the first page. WordPress will serve ?paged=2 and beyond,
# but DFB starts returning 429 after a couple of those in quick succession,
# and a crawler that has to be rate-limited into behaving is one page away
# from being blocked outright the way allears.net now blocks everyone. The
# daily cadence is what buys coverage here, not depth per run. A post that
# scrolled off before this shipped is not reachable this way; ingest it by
# URL or attach its photo in docs/studio.html.
REVIEW_FEED_PATH = "/tag/epcot-food-and-wine-festival/feed/"

# /2026/08/27/review-.../ -> 2026. These are dated permalinks, so the year is
# in the path rather than the slug.
_PERMALINK_YEAR_RE = re.compile(r"^/(?P<year>\d{4})/\d{2}/\d{2}/")

_CLICK_TO_SEE_RE = re.compile(r"click to see photos", re.IGNORECASE)

# Booth headings carry the staggered run dates some marketplaces have:
#   "The Alps - Opening October 2nd"
#   "Coastal Eats - Opens October 2nd"
#   "The Wedge - NEW! Open September 18th through November 8th"
# That is scheduling, not identity, and left in it would stop the booth
# matching the same booth as named anywhere else. The clause is only stripped
# when it actually mentions opening, so a hyphen inside a real name
# ("Brew-Wing Lab") is untouched.
_OPENING_SUFFIX_RE = re.compile(r"\s*[—–-]\s*[^—–]*\bopen(?:s|ing)?\b.*$", re.IGNORECASE)

# The category markers that separate a booth's food list from its drinks list.
_CATEGORY_LABELS = {"food": "food", "beverages": "beverage", "beverage": "beverage"}

# Words that name a drink rather than describe one. Matched only at the END of
# an item's name, because English puts the head noun of a drink name last:
# "Peroni Pilsner" and "Samuel Adams Boston Brick Red Irish Red Ale" are
# drinks, while "Cider-brined Pork Tenderloin" and "Red Wine-braised Beef
# Short Rib" are dishes that merely mention one. That distinction is what
# rescues Hops & Barley, whose beer list on the 2026 page sits under the
# booth's "Food:" label with no "Beverages:" heading of its own.
_BEVERAGE_FORM_RE = re.compile(
    r"\b(lager|ale|ipa|stout|porter|pilsner|hefeweizen|weisse|witbier|saison|bock|"
    r"festbier|gose|radler|shandy|cider|wine|champagne|prosecco|cava|riesling|"
    r"chardonnay|sauvignon|cabernet|merlot|pinot|shiraz|syrah|zinfandel|malbec|"
    r"viognier|godello|veltliner|moscato|(?:red|white) blend|cocktail|margarita|mojito|martini|"
    r"spritz|mule|sangria|mimosa|bellini|coffee|cold brew|tea|latte|cappuccino|"
    r"espresso|lemonade|soda|cola|slushy|shake|smoothie|juice|lassi|boba|float|"
    r"flight)\s*[*.!]?$",
    re.IGNORECASE,
)


def _resolve_category(section_category: str, name: str, tags: list[str]) -> str:
    """Turn a section label into the category actually stored.

    A "Beverages:" list splits on whether the drink is alcoholic. A "Food:"
    list is taken at its word unless the item's own name says it is a drink -
    see _BEVERAGE_FORM_RE for why that check is anchored to the end.
    """
    if section_category != "beverage" and not _BEVERAGE_FORM_RE.search(name):
        return section_category
    return "alcoholic_beverage" if "contains_alcohol" in tags else "non_alcoholic_beverage"


# Roughly a third of the 2026 lines wrap the price inside the same <strong> as
# the dish, in one of two shapes:
#   "Fowles Farm to Table Shiraz, Upton Hills - $7.50"
#   "Piraat 7 Strong Ale (New) - 6 oz $6.00 / 12 oz $9.75"
# The price is already parsed into its own field and kept verbatim in the
# description, so leaving it in the name only duplicates it - and worse, makes
# the name (and the natural key derived from it) change whenever the price
# does, which would stop the dish matching itself year to year or across
# sources.
_PRICE_SEPARATOR_RE = re.compile(r"\s+[—–-]\s+|,\s+")
_TRAILING_PRICE_RE = re.compile(r"\s*\$\s?\d+(?:\.\d{1,2})?\s*$")

# /the-alps-2025-epcot-food-and-wine-festival/     -> "the alps"
# /australia-2025-epcot-food-and-wine-festival-2/  -> "australia"  (WordPress
# appends -2 when a slug collides with a previous year's post)
_DETAIL_SLUG_RE = re.compile(
    r"^(?P<booth>.+?)-(?P<year>\d{4})-epcot-food-and-wine-festival(?:-\d+)?$", re.IGNORECASE
)


# A bare host with no scheme - "www.disneyfoodblog.com/spain-2018-..." - which
# is how the older hubs write some of their links.
_SCHEMELESS_HOST_RE = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+/", re.IGNORECASE)


def _absolute_url(href: str) -> str:
    """Resolve a hub link against the site root.

    Concatenating BASE_URL with anything that does not start with "http" is
    the obvious thing and it is wrong: the 2018 hub writes some links as a
    bare host, so that rule produced
    "https://www.disneyfoodblog.comwww.disneyfoodblog.com/spain-2018-..." -
    a hostname that does not resolve. Every 2018 booth post failed DNS, which
    a backfill reports as a fetch failure and shrugs off, so five seasons of
    photos looked like five seasons with nothing in them.
    """
    href = href.strip()
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("/"):
        return f"{BASE_URL}{href}"
    if _SCHEMELESS_HOST_RE.match(href):
        return f"https://{href}"
    return urljoin(f"{BASE_URL}/", href)


def _slug_year(url: str) -> int | None:
    """Festival year named by a per-booth photo post's slug, or None if the
    URL isn't one of those posts."""
    from urllib.parse import urlparse

    slug = urlparse(url).path.strip("/").rsplit("/", 1)[-1]
    match = _DETAIL_SLUG_RE.match(slug)
    return int(match.group("year")) if match else None


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


# ---------------------------------------------------------------------------
# Review posts (the 2026 shape)
# ---------------------------------------------------------------------------
#
# Through 2025 the dish photos lived in per-booth posts whose slug named the
# booth and the year. For 2026 DFB is publishing them as dated review
# permalinks instead - /2026/08/27/review-this-epcot-food-wine-festival-booth-
# proves-sometimes-keeping-it-simple-is-the-way-to-go/ - which carry the same
# captioned dish photos and none of the same handles: the slug names no booth,
# the hub links to none of them, and the page <h1> is a newsletter signup.
#
# The booth is recovered from the image filenames, which do name it, in the
# two shapes DFB's photo desk produces:
#
#   2026-...-Wine-Festival-Belgium-Booth-Belgian-Waffle-700x525.jpg
#   DFB-_-Beer-Flight_-Belgium-_-2026-EPCOT-Food-Wine-Festival-_-...jpg
#
# Every image votes and the majority wins, so one oddly-named file cannot
# decide the booth for a whole post. Below the threshold the post is skipped
# outright: a photo on the wrong booth's dish is worse than no photo, and it
# is the kind of wrong that looks like data.

_IMAGE_SIZE_SUFFIX_RE = re.compile(r"-\d+x\d+$")
_IMAGE_EXTENSION_RE = re.compile(r"\.(?:jpe?g|png|webp|gif)$", re.IGNORECASE)
_YEAR_RE = re.compile(r"^\d{4}$")

# Words that sit next to a booth name in these filenames but are never part
# of one, so walking back from the "Booth" marker knows where to stop.
_FILENAME_NOISE = frozenset(
    {"dfb", "epcot", "wdw", "disney", "world", "food", "and", "wine", "festival", "photo", "photos"}
)

# At least this share of the images that produced a candidate must agree
# before the winner is trusted. A tie, or a post whose photos are named
# inconsistently, resolves to no booth rather than to a guess.
_BOOTH_VOTE_THRESHOLD = 0.5
_MIN_BOOTH_VOTES = 2


def _filename_stem(image_url: str) -> str:
    stem = image_url.rsplit("/", 1)[-1]
    stem = _IMAGE_EXTENSION_RE.sub("", stem)
    return _IMAGE_SIZE_SUFFIX_RE.sub("", stem)  # WordPress's -700x525 rendition


def _walk_back(tokens: list[str], end: int, limit: int = 3) -> str | None:
    """The up-to-`limit` tokens before `end`, stopping at the first noise word
    or year - which is where the booth name starts."""
    out: list[str] = []
    for token in reversed(tokens[:end]):
        if len(out) >= limit or token.lower() in _FILENAME_NOISE or _YEAR_RE.match(token):
            break
        out.append(token)
    return " ".join(reversed(out)) or None


def _booth_from_filename(image_url: str) -> str | None:
    """The booth this photo's filename names, or None."""
    stem = _filename_stem(image_url)

    # Underscore-delimited shape: fields separated by "_", the booth in the
    # field just before the one that opens with the festival year.
    if "_" in stem:
        fields = [f.strip("-") for f in stem.split("_")]
        for i, field in enumerate(fields):
            head = field.split("-", 1)[0]
            if _YEAR_RE.match(head) and i > 0 and fields[i - 1]:
                return fields[i - 1].replace("-", " ").strip() or None

    tokens = [t for t in re.split(r"[-_]+", stem) if t]
    lowered = [t.lower() for t in tokens]
    if "booth" in lowered:
        return _walk_back(tokens, lowered.index("booth"))
    return None


def _booth_name_from_photos(image_urls: list[str]) -> str | None:
    """The booth a review post is about, by majority vote of its photos."""
    votes = Counter()
    for url in image_urls:
        name = _booth_from_filename(url)
        if name:
            votes[normalize_name(name)] += 1
    if not votes:
        return None
    winner, count = votes.most_common(1)[0]
    if count < _MIN_BOOTH_VOTES or count / sum(votes.values()) <= _BOOTH_VOTE_THRESHOLD:
        return None
    # Title-cased rather than the normalized key: this string is matched
    # through normalize_name() downstream anyway, and a readable value is
    # what shows up in a merge_conflicts row someone has to look at.
    return winner.title()


def _is_booth_boundary(p: Tag) -> bool:
    return p.name == "p" and bool(_CLICK_TO_SEE_RE.search(p.get_text()))


def _h3_sections(article: Tag) -> list[tuple[str, list[Tag]]]:
    """Split the article into (heading text, following elements) per <h3>.

    Walks in document order rather than by sibling, because the 2026 page
    nests some booths' lists inside wrapper divs while leaving others as
    direct siblings - a next_sibling walk silently drops the nested ones.
    Nested <ul>s are skipped so a list inside a list is not counted twice.
    """
    sections: list[tuple[str, list[Tag]]] = []
    current: tuple[str, list[Tag]] | None = None

    for element in article.find_all(["h3", "p", "ul", "ol"]):
        if element.name == "h3":
            current = (clean_text(element.get_text()), [])
            sections.append(current)
        elif current is not None:
            if element.name in ("ul", "ol") and element.find_parent(["ul", "ol"]) is not None:
                continue
            current[1].append(element)

    return sections


def _strip_price_clause(name: str) -> str:
    """Cut a trailing pricing clause off a dish name, leaving the dish.

    Cuts at the last separator whose remainder mentions a price, so a name
    that legitimately contains commas keeps them ("Loimer Lois Gruner
    Veltliner, Niederosterreich, Austria" loses only ", $6.50"). A name that
    is nothing but a price is left alone - there is no dish left in it, and an
    empty name is worse than a noisy one.
    """
    cut = None
    for match in _PRICE_SEPARATOR_RE.finditer(name):
        if "$" in name[match.end() :]:
            cut = match.start()
    stripped = name[:cut] if cut is not None else name
    stripped = _TRAILING_PRICE_RE.sub("", stripped)
    # A line can separate the price with a lone dash the split above doesn't
    # consume ("Harken Barrel Fermented Chardonnay -- $6.50"), which would
    # otherwise leave the name ending in dangling punctuation.
    stripped = stripped.strip().rstrip(",-–— ").strip()
    return stripped or name


# DFB bolds most dish names, but not all. On an unbolded line the name and
# its description run together, separated by a spaced dash or a colon:
#   "Mango-Peach Bubble Tea - Green Tea, Mango and Peach Syrups, and White Boba"
# Spacing is what makes this safe: a hyphen inside a name is never spaced
# ("Mango-Peach", "Cider-brined").
_NAME_TAIL_RE = re.compile(r"\s+[—–]\s+|:\s+")

# The 2026 page flags a chunk of the lineup - new dishes and, seemingly by
# mistake, plenty of returning ones (Belgian Waffle, Wiener Schnitzel) - with
# a "NEW!" or "NEW" badge bolded onto the front of the name. Sometimes it
# shares the <strong> with the dish name ("NEW! Belgian Waffle"), sometimes
# it's its own <strong> with the name as plain sibling text ("NEW" / "Affogato
# ... Cold Brew"). Either way it is not part of the dish's identity, and
# leaving it in shifts the name just far enough that entity resolution treats
# a returning dish as a new one instead of matching it to itself. Matched
# case-sensitively so a real title-case name ("New England...") is never
# touched, and only at the very start with nothing but a space/colon/end
# after it, so "Newcastle" is never mistaken for the badge.
_NEW_BADGE_RE = re.compile(r"^NEW!?(?=\s|:|$)\s*[:\-–—]?\s*")


def _strip_new_badge(s: str) -> str:
    return _NEW_BADGE_RE.sub("", s, count=1)


def _description_from(text: str, name: str) -> str | None:
    """What the line says beyond the dish's own name.

    DFB writes one run-on line per dish - "Seafood Pot Pie with Shrimp,
    Scallops, and Lobster Bisque topped with Puff Pastry - $7.49" - of which
    the name is the head and the price is the tail. Storing the whole line as
    the description means every surface that shows both renders the name
    twice and the price twice. What is left in the middle is the actual
    description, and there is genuinely nothing left for a line like "Beer
    Flight - $12.75", which gets None rather than an echo of its own name.
    """
    remainder = text
    if remainder.lower().startswith(name.lower()):
        remainder = remainder[len(name) :]
    remainder = _strip_price_clause(remainder)
    # Whatever joined the name to its description - a dash, a colon, a comma.
    remainder = remainder.strip().lstrip(":,-–—").strip()
    # _strip_price_clause returns its input unchanged rather than empty, so a
    # line that was only ever a name and a price comes back as the price - and
    # a multi-serving line comes back as "6 oz $6.00 / 12 oz $9.75", which has
    # letters in it but is still pricing. Any surviving "$" means there was no
    # description here to find.
    if not remainder or remainder == text or "$" in remainder:
        return None
    if not re.search(r"[A-Za-z]", remainder):
        return None
    return remainder


def _inline_menu_item(
    li: Tag, booth_name: str, category: str
) -> tuple[ExtractedRecordDTO, str] | None:
    """One <li> from a 2026 booth list -> a menu_item record.

    Returns the record and the name to fall back on if the short one turns out
    to collide inside this booth - see _restore_colliding_names.
    """
    text = clean_text(li.get_text())
    if not text:
        return None
    text = _strip_new_badge(text)

    name_tag = li.find("strong")
    name = _strip_new_badge(clean_text(name_tag.get_text())) if name_tag is not None else ""
    if not name:
        # Either there was no <strong> at all, or it turned out to be nothing
        # but the badge (name text is a plain sibling, not inside it) - both
        # fall back to splitting the (already badge-stripped) full line.
        name = _NAME_TAIL_RE.split(text, 1)[0]
    if not name:
        return None
    name = _strip_price_clause(name)
    fallback = _strip_price_clause(text)

    prices = all_prices(text)
    tags = extract_dietary_tags(text)
    resolved = _resolve_category(category, name, tags)

    record = ExtractedRecordDTO(
        entity_type="menu_item",
        natural_key_hint=normalize_name(name[:80]),
        payload={
            "booth_name": booth_name,
            "name": name,
            "description": _description_from(text, name),
            "category": resolved,
            # min(): a drink priced by the glass and the flight lists both, and
            # the single-serving price is the comparable one.
            "price_usd": str(min(prices)) if prices else None,
            "dietary_tags": tags,
        },
    )
    return record, fallback


def _restore_colliding_names(
    parsed: list[tuple[ExtractedRecordDTO, str]],
) -> list[ExtractedRecordDTO]:
    """Undo the name/description split where it would merge two dishes.

    Joffrey's sells three cold brews in a plain and a spiked version, listed
    as two lines that agree word for word up to the spirit at the end. Cutting
    each at the dash leaves two items called "Dolce Affogato Cold Brew" in the
    same booth, which resolution then merges - quietly dropping the one with
    the Baileys in it. Where that would happen, both lines keep their full
    text as the name: a long name is a much smaller problem than a missing
    drink.
    """
    counts = Counter(record.payload["name"] for record, _ in parsed)
    records = []
    for record, fallback in parsed:
        if counts[record.payload["name"]] > 1 and fallback != record.payload["name"]:
            record.payload["name"] = fallback
            record.payload["description"] = None
            record.natural_key_hint = normalize_name(fallback[:80])
        records.append(record)
    return records


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

    def discover_new_urls(self, since: datetime.datetime, festival_year: int) -> list[SeedUrl]:
        """The per-booth "CLICK TO SEE PHOTOS OF MENU ITEMS" posts, one per
        booth, scraped off the hub page.

        These carry the individual dish photos; the hub itself has none. The
        slugs are year- and booth-specific (`/the-alps-2025-epcot-food-and-
        wine-festival/`) so they can't be enumerated ahead of time, which is
        why they're discovered rather than declared in seed_urls().

        Only posts whose slug names `festival_year` are returned. The undated
        hub keeps serving last season's line-up until DFB publishes the new
        one, so ahead of opening day this page is still linking to the
        previous year's photo posts. Booth names repeat season to season and
        many dish names do too, so those would fuzzy-match onto this year's
        entities and quietly fill the ledger with last year's plates - which
        reads as success rather than as the no-data-yet it actually is.

        `since` is deliberately ignored: these posts are edited in place as
        photos get added over the season rather than republished with a new
        date, so filtering by publish date would freeze out exactly the
        updates worth re-fetching. Re-listing them every run is cheap - the
        conditional-GET and content-hash checks in fetch/cache.py mean an
        unchanged post costs a 304 and is never reparsed.
        """
        from epcot_fw.fetch.http_client import fetch

        seeds: list[SeedUrl] = []
        result = fetch(f"{BASE_URL}{BOOTH_HUB_PATH}", crawl_delay_sec=5)
        if not result.not_modified and result.text:
            seeds.extend(self._detail_seeds(result.text, festival_year))
        seeds.extend(self._review_seeds(festival_year))
        return seeds

    def _review_seeds(self, festival_year: int) -> list[SeedUrl]:
        """This season's review posts, off the festival tag's feed.

        `since` is not passed through, for the same reason discover_new_urls
        ignores it: the point is to hold every current-season post, not the
        ones published since the last run. The feed is ten entries, so the
        cost of re-listing is bounded, and fetch/cache.py turns an unchanged
        post into a 304 that is never reparsed.

        Filtered to permalinks whose date names the festival year. Last
        season's reviews carry last season's plates, and booth and dish names
        repeat enough that they would fuzzy-match onto this year's rows and
        quietly fill the ledger with 2025 photos.
        """
        from urllib.parse import urlparse

        from epcot_fw.sources.common import rss_discover

        seeds = []
        for seed in rss_discover(
            f"{BASE_URL}{REVIEW_FEED_PATH}", _EPOCH, page_kind="booth_review"
        ):
            match = _PERMALINK_YEAR_RE.match(urlparse(seed.url).path)
            if match and int(match.group("year")) == festival_year:
                seeds.append(seed)
        return seeds

    def historical_detail_seeds(self, year: int) -> list[SeedUrl]:
        """Per-booth photo-post links for a *past* festival year.

        discover_new_urls() always reads the undated hub, because for the
        current season that is the page that gets edited as new posts appear.
        A past season's undated hub was long since overwritten by whatever
        came after it, so this reads that year's own dated hub instead
        (`/{year}-epcot-food-and-wine-festival-booths-menus-and-food-
        photos/`) - the same URL this adapter's own seed_urls() fetches for
        the current year, just pointed at an earlier one.

        Returns [] rather than raising on a 404 or an unexpected shape: not
        every year necessarily used this URL pattern or this page layout, and
        one missing season should not stop a backfill run across several.
        """
        from epcot_fw.fetch.http_client import fetch

        url = f"{BASE_URL}/{year}-epcot-food-and-wine-festival-booths-menus-and-food-photos/"
        result = fetch(url, crawl_delay_sec=5)
        if not (200 <= result.status_code < 300) or not result.text:
            return []
        return self._detail_seeds(result.text, year)

    def _detail_seeds(self, raw_html: str, festival_year: int) -> list[SeedUrl]:
        soup = soupify(raw_html)
        article = soup.find("article") or soup
        seeds: list[SeedUrl] = []
        seen: set[str] = set()

        for boundary_p in (p for p in article.find_all("p") if _is_booth_boundary(p)):
            link = boundary_p.find("a", href=True)
            if link is None:
                continue
            href = _absolute_url(link["href"])
            if href in seen:
                continue
            if _slug_year(href) != festival_year:
                continue
            seen.add(href)
            seeds.append(SeedUrl(url=href, page_kind="booth_detail"))

        return seeds

    def parse(self, raw_html: str, url: str, page_kind: str) -> list[ExtractedRecordDTO]:
        if page_kind == "booth_detail":
            return self._parse_booth_detail(raw_html, url)
        if page_kind == "booth_review":
            return self._parse_booth_review(raw_html)
        return self._parse_booth_list(raw_html)

    def _parse_booth_review(self, raw_html: str) -> list[ExtractedRecordDTO]:
        """A dated review post -> a menu_item record per captioned dish photo.

        Same output as _parse_booth_detail and for the same reasons; the only
        difference is where the booth comes from. A per-booth post names it in
        the slug, and this shape does not name it anywhere reliable - the <h1>
        on these pages is a newsletter signup - so it is recovered from the
        image filenames by majority vote. No booth, no records: these posts
        are about one booth, and guessing which would attach a photo to
        another booth's dish.
        """
        soup = soupify(raw_html)
        article = soup.find("article") or soup
        images = extract_captioned_images(article)

        booth_name = _booth_name_from_photos([image.url for image in images])
        if not booth_name:
            return []

        return [
            ExtractedRecordDTO(
                entity_type="menu_item",
                natural_key_hint=normalize_name(image.caption[:80]),
                payload={
                    "booth_name": booth_name,
                    "name": image.caption,
                    "image_url": image.url,
                    # These posts caption the booth sign, the menu board and
                    # the writer's asides in the same markup as the dishes,
                    # so a caption here is only ever evidence about a dish
                    # that already exists - never grounds to create one.
                    "attach_only": True,
                },
            )
            for image in images
        ]

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
        """Dispatch on the hub layout, which DFB rebuilt for 2026.

        Through 2025 each booth was introduced by a paragraph linking to its
        photo post ("Belgium <- CLICK TO SEE PHOTOS OF MENU ITEMS!"), with the
        menu following as sibling lists. For 2026 the menus were brought onto
        the hub itself: booths are <h3> headings and the photo links are gone.
        Both are kept because the shape of the page is the only reliable way to
        tell them apart, and an archived page or a mid-season revert should
        still parse rather than silently yield nothing - which is exactly what
        happened on the first 2026 crawl.
        """
        soup = soupify(raw_html)
        article = soup.find("article") or soup

        if any(_is_booth_boundary(p) for p in article.find_all("p")):
            return self._parse_booth_list_linked(article)
        return self._parse_booth_list_inline(article)

    def _parse_booth_list_inline(self, article: Tag) -> list[ExtractedRecordDTO]:
        """2026 layout: <h3> booth, then "Food:"/"Beverages:" paragraphs each
        followed by a <ul> of dishes.

        A heading only counts as a booth if its section actually carries one of
        those category labels. That is a structural test rather than a list of
        headings to ignore, so unrelated <h3>s on the page ("Click here for
        information on the EPCOT Food and Wine Festival!") are excluded without
        having to enumerate them.
        """
        records: list[ExtractedRecordDTO] = []

        for heading, elements in _h3_sections(article):
            booth_name = _OPENING_SUFFIX_RE.sub("", heading).strip()
            if not booth_name or len(booth_name) > 80:
                continue

            parsed_items: list[tuple[ExtractedRecordDTO, str]] = []
            category: str | None = None
            for element in elements:
                if element.name == "p":
                    label = clean_text(element.get_text()).rstrip(":").lower()
                    if label in _CATEGORY_LABELS:
                        category = _CATEGORY_LABELS[label]
                    continue
                if category is None:
                    continue
                for li in element.find_all("li"):
                    item = _inline_menu_item(li, booth_name, category)
                    if item is not None:
                        parsed_items.append(item)

            # No category label anywhere in the section -> not a booth.
            if category is None:
                continue

            records.append(
                ExtractedRecordDTO(
                    entity_type="booth",
                    natural_key_hint=normalize_name(booth_name),
                    payload={"name": booth_name, "category": "global_marketplace"},
                )
            )
            records.extend(_restore_colliding_names(parsed_items))

        return records

    def _parse_booth_list_linked(self, article: Tag) -> list[ExtractedRecordDTO]:
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
