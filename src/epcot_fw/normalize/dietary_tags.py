"""Dietary tags inferred from menu copy.

These come from keyword-matching the text a food blog published, not from
Disney's allergen data. Disney does not publish machine-readable allergen
information for festival kiosks, and a marketing description omits far more
than it states - "Chocolate-Pistachio Cookie" says pistachio, "Freshly Baked
Carrot Cake" says nothing about the walnuts in it.

So these tags are a browsing convenience - "show me the plant-based things",
"which of these are cocktails" - and never an allergen guarantee. Anyone with
an actual allergy has to ask at the booth. Surfaces that show these tags are
expected to say so.

The lists below err in the direction that makes that framing safe: broad on
`contains_alcohol` and `contains_nuts`, where a miss is the costly direction,
and narrow on the positive dietary claims, which are only ever asserted when
the source says the word.
"""

import re

# Drinks the copy explicitly disclaims. Checked before anything else, because
# a mocktail's description names the spirit it is imitating and a
# "non-alcoholic" cold brew still lists the liqueur its sibling gets.
_NON_ALCOHOLIC_RE = re.compile(
    r"\bnon[\s-]?alcoholic\b|\balcohol[\s-]free\b|\bvirgin\b|\bmocktail\b", re.IGNORECASE
)

# Beer, before "beer" alone: root beer and ginger beer are soft drinks, and
# ginger beer in particular turns up in half the frozen cocktails.
_BEER_RE = r"(?<!root )(?<!ginger )\bbeers?\b"

_ALCOHOL_TERMS = [
    # beer and its styles
    _BEER_RE,
    r"\b(lager|ales?|ipa|stouts?|porters?|pilsn(?:er|ers)|hefeweizen|weisse|weizen|"
    r"witbier|saison|bock|festbier|gose|k(?:o|ö)lsch|radler|shandy|brut)\b",
    # wine, its styles and its varietals
    r"\b(wines?|champagne|prosecco|cava|sangria|mimosa|moscato|riesling|chardonnay|"
    r"sauvignon|cabernet|merlot|pinot|shiraz|syrah|zinfandel|malbec|tempranillo|"
    r"grenache|viognier|godello|veltliner|xinomavro|colombard|verdejo|albari(?:n|ñ)o|"
    r"garnacha|sangiovese|nebbiolo|chianti|rioja|vinho|ros(?:e|é)|sekt|sherry|madeira)\b",
    # "Red Blend" is how a wine list writes an unnamed blend; "blend" on its
    # own is what every frozen drink description calls itself.
    r"\b(red|white)\s+blends?\b",
    # spirits
    r"\b(vodka|gin|rum|whisk(?:e)?y|bourbon|scotch|tequila|mezcal|brandy|cognac|"
    r"armagnac|grappa|absinthe|soju|schnapps|a(?:q|k)vavit|ouzo|pisco|rye|"
    r"kirschwasser|calvados|spirits?|liquor)\b",
    # liqueurs and fortified extras
    r"\b(liqueur|amaretto|baileys|kahl(?:u|ú)a|cointreau|curacao|cura(?:ç)ao|aperol|"
    r"campari|vermouth|limoncello|sambuca|chartreuse|triple sec|bitters)\b",
    # mixed drinks
    r"\b(cocktails?|margarita|mojito|martini|spritz|old fashioned|negroni|daiquiri|"
    r"mule|cosmo(?:politan)?|sour ale|hard seltzer|hard cider|cidery|mead|sake)\b",
    # producers - a name that says who brewed or grew it says what it is
    r"\b(brew(?:ery|eries|ing)|winery|wineries|vineyards?|cellars|distiller(?:y|ies)|"
    r"barrel[\s-]aged|cask[\s-]aged)\b",
]

# Bare "cider" is deliberately absent: in the US it is apple juice unless it
# says hard, which is why "Cider-brined Pork Tenderloin" used to come back
# tagged as containing alcohol.

_NUT_TERMS = [
    r"\b(peanuts?|almonds?|cashews?|walnuts?|pecans?|hazelnuts?|pistachios?|"
    r"macadamias?|pralines?|marzipan|nutella|gianduja|frangipane|nougat|amaretto)\b",
    r"\bpine nuts?\b",
    # "water chestnut" is a vegetable; every other chestnut is a nut.
    r"(?<!water )\bchestnuts?\b",
    # Catches "Toffee Nut Sauce" and "mixed nuts" without catching butternut,
    # coconut, nutmeg or doughnut - word boundaries do that work.
    r"\bnuts?\b",
]


def _any(patterns: list[str]) -> re.Pattern:
    return re.compile("|".join(patterns), re.IGNORECASE)


_TAG_PATTERNS: dict[str, re.Pattern] = {
    "vegan": re.compile(r"\bvegan\b", re.IGNORECASE),
    "vegetarian": re.compile(r"\bvegetarian\b", re.IGNORECASE),
    "plant_based": re.compile(r"\bplant[\s-]based\b", re.IGNORECASE),
    "gluten_free": re.compile(r"\bgluten[\s/-]?(free|friendly|wheat friendly)\b", re.IGNORECASE),
    "contains_alcohol": _any(_ALCOHOL_TERMS),
    "spicy": re.compile(r"\bspicy\b", re.IGNORECASE),
    "contains_nuts": _any(_NUT_TERMS),
}


def extract_dietary_tags(*texts: str) -> list[str]:
    """Scan free-text (item name, description, notes) for known dietary-tag keywords."""
    combined = " ".join(t for t in texts if t)
    tags = [code for code, pattern in _TAG_PATTERNS.items() if pattern.search(combined)]

    # An explicit disclaimer beats any keyword. The alternative is telling a
    # guest their mocktail is a cocktail because its description names the
    # spirit it stands in for.
    if "contains_alcohol" in tags and _NON_ALCOHOLIC_RE.search(combined):
        tags.remove("contains_alcohol")

    return tags
