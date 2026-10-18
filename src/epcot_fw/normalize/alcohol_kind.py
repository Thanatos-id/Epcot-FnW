"""Which kind of drink an alcoholic drink is: beer, wine, liquor or cider.

One value per drink, so this answers with a single code rather than a set.
Only ever asked about drinks the parser already filed as alcoholic - it does
not decide *whether* a drink contains alcohol, which is
normalize/dietary_tags.py's job and a different question.

Order matters, and it is the whole design. The strings overlap heavily on
this menu: "3 Daughters Brewing Apple Strudel Hard Cider" names a brewery
and is not beer, "1000 Stories Bourbon Barrel-Aged Zinfandel" names a
bourbon barrel and is wine, "Kirschwasser Torte" is a cake. So the most
specific claim wins:

1. **cider** - "hard cider" says so outright, whoever brewed it. Eleven of
   these are on the menu and a brewery made most of them, so testing beer
   first would swallow the lot.
2. **beer, by style** - a hefeweizen or a stout is beer whatever else the
   name says, including a "spritz".
3. **wine** - a varietal or a sparkling style is unambiguous, and beats the
   barrel a wine was aged in.
4. **beer, by maker** - brewery words, which only decide it once cider and
   wine have had their say.
5. **liquor** - spirits, liqueurs, and the cocktails built on them. Last
   because a cocktail's name lists its spirits *and* its mixers, and a wine
   or beer rarely mentions a spirit at all.

Anything still unmatched gets no value rather than a guess. Five drinks were
in that position when this was written, all of them wines whose names never
say wine - Château des Charmes Pétales Rouge, Schlumberger Klassik Brut -
and docs/studio.html is where those get set by hand.
"""

import re

BEER = "beer"
WINE = "wine"
LIQUOR = "liquor"
CIDER = "cider"

KINDS = frozenset({BEER, WINE, LIQUOR, CIDER})

# Said outright, and tested before the brewery that made it.
_CIDER_RE = re.compile(r"\b(hard cider|cidery|perry|hard seltzer|mead)\b", re.IGNORECASE)

_WINE_RE = re.compile(
    r"\b(wines?|champagne|prosecco|cava|sangria|mimosa|bellini|spritz(?:er)?|"
    r"moscato|riesling|chardonnay|sauvignon|cabernet|merlot|pinot|shiraz|syrah|"
    r"zinfandel|malbec|tempranillo|grenache|viognier|godello|veltliner|xinomavro|"
    r"colombard|verdejo|albari(?:n|ñ)o|garnacha|sangiovese|nebbiolo|chianti|rioja|"
    r"vinho|ros(?:e|é)|sekt|sherry|port|madeira|brut|sparkling|"
    r"red blend|white blend|vineyards?|winery|wineries|cellars|bodegas?|ch(?:a|â)teau)\b",
    re.IGNORECASE,
)

# Beer splits in two, because its two kinds of evidence deserve different
# places in the order. A *style* - hefeweizen, stout, lager - says beer and
# nothing else, so it is checked before wine: "Schöfferhofer Orange Spritz
# Hefeweizen" was filed as wine on its "spritz" until this moved. A *maker* -
# brewing, brewery - is weaker, since breweries make ciders and barrel-age
# other people's wine, so it stays after wine.
#
# Ginger beer and root beer are soft drinks, and ginger ale is a mixer: the
# Spiced Apple Mule is a vodka cocktail, and read as a beer on its "Frozen
# Ginger Beer" until the same guards normalize/dietary_tags.py already had
# were copied here.
_BEER_STYLE_RE = re.compile(
    r"(?<!ginger )(?<!root )\bbeers?\b|(?<!ginger )\bales?\b|"
    r"\b(lagers?|ipa|stouts?|porters?|pilsn(?:er|ers)|hefeweizen|weisse|weizen|"
    r"witbier|saison|bock|festbier|gose|k(?:o|ö)lsch|radler|shandy)\b",
    re.IGNORECASE,
)

_BEER_MAKER_RE = re.compile(
    r"\b(brewing|brewery|brewer|brew(?:\s|-)?(?:co|hub|pub)|brauerei|brouwerij|"
    r"brasserie|cervecer(?:i|í)a)\b",
    re.IGNORECASE,
)

_LIQUOR_RE = re.compile(
    r"\b(vodka|gins?|rums?|whisk(?:e)?y|bourbon|scotch|tequila|mezcal|brandy|cognac|"
    r"armagnac|grappa|absinthe|soju|sake|schnapps|a(?:q|k)vavit|ouzo|pisco|rye|"
    r"kirschwasser|calvados|cacha(?:ç|c)a|spirits?|liquor|distiller(?:y|ies)?|"
    r"liqueur|amaretto|baileys|kahl(?:u|ú)a|cointreau|cura(?:ç|c)ao|aperol|campari|"
    r"vermouth|limoncello|sambuca|chartreuse|triple sec|bitters|"
    r"cocktails?|margarita|mojito|martini|old fashioned|negroni|daiquiri|mule|"
    r"cosmo(?:politan)?|punch|slushy cocktail)\b",
    re.IGNORECASE,
)

# Checked in this order; first hit wins. See the module docstring.
_ORDER = (
    (CIDER, _CIDER_RE),
    (BEER, _BEER_STYLE_RE),
    (WINE, _WINE_RE),
    (BEER, _BEER_MAKER_RE),
    (LIQUOR, _LIQUOR_RE),
)


def classify_alcohol(*texts: str) -> str | None:
    """`'beer' | 'wine' | 'liquor' | 'cider'`, or None when the copy does not say."""
    combined = " ".join(t for t in texts if t)
    if not combined:
        return None
    for kind, pattern in _ORDER:
        if pattern.search(combined):
            return kind
    return None


def alcohol_kind_payload(category: str | None, *texts: str) -> dict[str, str]:
    """`{"alcohol_kind": ...}` for an alcoholic drink the copy identifies.

    Scoped to `alcoholic_beverage` on purpose. "Kirschwasser Torte" is a cake
    and "Beer-braised Beef" is a plate of beef; both name a drink, and
    neither is one.
    """
    if category != "alcoholic_beverage":
        return {}
    kind = classify_alcohol(*texts)
    return {"alcohol_kind": kind} if kind else {}
