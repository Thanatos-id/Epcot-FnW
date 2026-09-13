"""The "new this year" marker sources put on a dish, read as data.

Every season the blogs mark which dishes are new to the festival, and they do
it in the copy rather than in any field. Until this module the mark was
thrown away: it decorates a name, a name is prose, and the prose stopped at
the canonical layer.

Two different marks exist, and only one of them is worth believing.

**"(New)" after the name - trusted.** Disney Food Blog and AllEars both
write it, independently, about the same dishes: 51 records and 50 records at
the time this was written. Two sources that agree without sharing a template
is the strongest signal available here.

**"NEW!" in front of the name - read, stripped, and not believed.** Only
Disney Food Blog writes it, and sources/disney_food_blog.py's own
`_strip_new_badge` has been removing it since before this module existed,
for a reason recorded there: the 2026 page hangs it on "plenty of returning
ones (Belgian Waffle, Wiener Schnitzel)". The database agrees - `NEW!
Belgian Waffle` and `NEW! Wiener Schnitzel` are both in it, and AllEars
lists both with no mark at all. A badge that is wrong about dishes anyone
can name is not evidence, so it never sets the flag.

The badge still comes *off* a name that carries it, though, which is a
separate job from believing it: "NEW! Belgian Waffle" is not what the dish
is called, and leaving it in shifts the name far enough that resolution
reads a returning dish as a new one.

That asymmetry is the whole design. A dish wrongly badged "new" is a visible
error in the app - a guest is told the Belgian Waffle is new when it has
been there for years - while a genuinely new dish that no source
parenthesised is merely missing, and can be ticked on by hand in
docs/studio.html. Precision is the direction to err in.

Precision against the ordinary language of food, too. "New York Strip",
"New England Clam Chowder" and "New Zealand Sauvignon Blanc" are all
plausible festival copy, so the bare word never counts: inside parentheses
the word is an aside by construction, and the badge pattern is capitalised
and anchored to the start, which is what keeps "Newcastle Brown Ale" out of
both.
"""

import re

# "(New)" anywhere in the text, in any case: the parentheses carry the
# meaning, so case is free to vary. This is the one that sets the flag.
_PAREN_MARKER_RE = re.compile(r"\(\s*new\s*\)", re.IGNORECASE)

# Disney Food Blog's own words for a dish that is *not* new: "(30th
# Anniversary Legacy Item)", which it writes on returning dishes all season.
# On the Belgian Waffle it writes both at once - "...speculoos cookie pieces
# (30th anniversary legacy item (New) - $5.49" - and the two cannot both be
# true. The dish that has been at the festival for years is the one to
# believe, so an explicit legacy note beats the mark, exactly as an explicit
# "non-alcoholic" beats a named spirit in normalize/dietary_tags.py.
#
# Only this phrase. "Classic" and "Returning" looked like siblings of it
# until the corpus showed them to be product names - Famille Hugel Classic
# Pinot Noir, CORKCICLE Classic Tumbler.
_LEGACY_RE = re.compile(r"\blegacy item\b", re.IGNORECASE)

# "NEW!" / "NEW" opening the text. Capitals only, anchored to the start, and
# allowed a colon or dash after it - deliberately the same shape as
# disney_food_blog's `_NEW_BADGE_RE`, since it is the same badge. Stripped
# from names, never believed. See the module docstring.
_PREFIX_BADGE_RE = re.compile(r"^NEW!?(?=\s|:|$)\s*[:\-–—]?\s*")

_WS_RE = re.compile(r"\s{2,}")


def mentions_new_this_year(*texts: str) -> bool:
    """True when any of `texts` carries the trusted "(New)" marker and none of
    them calls the dish a legacy item.

    The "NEW!" badge deliberately does not count - see the module docstring.
    """
    present = [t for t in texts if t]
    if any(_LEGACY_RE.search(t) for t in present):
        return False
    return any(bool(_PAREN_MARKER_RE.search(t)) for t in present)


def new_this_year_payload(*texts: str) -> dict[str, bool]:
    """`{"is_new_this_year": True}` when the marker is there, `{}` when it isn't.

    Spread into a menu_item payload. The empty dict is the point: a source
    that never writes the marker at all - Disney's own site does not - must
    not be read as asserting the dish is *not* new, because it outranks the
    blogs that do write it. disney_official sits at priority_rank 1 and
    disney_food_blog, which marks new dishes, at 6; a `False` from the former
    would bury every `True` from the latter.

    So absence stays absence, the column keeps its default, and the only
    thing that can ever say "no, this one came back from last year" is a
    person correcting it in docs/studio.html.
    """
    return {"is_new_this_year": True} if mentions_new_this_year(*texts) else {}


def strip_new_marker(text: str) -> str:
    """The text with either "new" mark removed, for the name it was decorating.

    Both marks come off here, including the badge this module refuses to
    believe: taking it out of a name is about what the dish is called, not
    about whether it is new.

    Only the mark goes. Everything else - a "(plant-based item)" aside that
    followed it, the dish's own parentheses - is left as the source wrote it.
    """
    if not text:
        return text
    cleaned = _PREFIX_BADGE_RE.sub("", text, count=1)
    cleaned = _PAREN_MARKER_RE.sub(" ", cleaned)
    return _WS_RE.sub(" ", cleaned).strip()
