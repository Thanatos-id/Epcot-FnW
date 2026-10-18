"""Whether a dish reads sweet, savoury, both, or neither.

Read off the same menu copy everything else here is read from, with the same
stance: assert what the words support and leave the rest alone. The tags are
a browsing aid - "show me somewhere to get dessert" - not a claim about a
recipe nobody published.

Three things this deliberately does not do.

**Neither is a real answer.** Most of this menu's drinks are a dry Riesling
or a hoppy IPA, which are not sweet and are not savoury, and 97 of 145
drinks matched nothing at all when both lists were first run over them. A
classifier that forced every one into a bucket would be inventing the
answer, and a "sweet drinks" filter built on it would return every wine on
the promenade.

**Both is a real answer too.** Salted caramel, sweet-and-sour, a cider-brined
pork with apple butter: nine dishes on the current menu carry words from
both lists, and they carry them honestly. Nothing here breaks a tie.

**A sweet ingredient does not make a sweet dish.** This is where the list
earns its keep or fails: honey on griddled cheese, a cherry in a glaze,
chutney beside a lamb chop. So the sweet list is built from things that are
the dish - a cake, a gelato, a churro - and from sugar in the forms that
only turn up when something is a dessert, while the savoury list is built
from proteins, starches and aromatics. Words that cut both ways are in
neither list.
"""

import re

# What the dish *is*, when the dish is a sweet. A noun from this list is
# almost never a garnish on something savoury.
_SWEET_FORMS = [
    # Cake and pie need guarding: a crab cake, an onion cake and a pot pie
    # are all dinner. The savoury word always sits directly in front.
    r"\bdessert\b",
    r"(?<!crab )(?<!fish )(?<!onion )(?<!rice )\bcakes?\b",
    r"(?<!pot )(?<!shepherd's )(?<!cottage )\bpies?\b",
    r"\b(tarts?|cookies?|brownies?|mousse|cheesecake)\b",
    r"\b(gelato|ice cream|sorbet|soft[\s-]serve|sundae|float|milk ?shake)\b",
    r"\b(pudding|trifle|panna cotta|cr(?:e|è)me br(?:u|û)l(?:e|é)e|flan)\b",
    r"(?<!savory )(?<!savoury )\bcustard\b",
    r"\b(doughnuts?|donuts?|churros?|waffles?|strudel|baklava|cannoli|tiramisu)\b",
    r"\b(macarons?|p(?:a|â)tisserie|(?:e|é)clair|profiterole|bombolon[ei]|beignets?)\b",
    r"\b(fudge|toffee|nougat|praline|marshmallow|marzipan)\b",
    # Frozen sweets and the sugary drink forms, which read as dessert in a cup.
    r"\b(slush(?:y|ie)?|frozen lemonade|hot chocolate|affogato)\b",
]

# Sugar in forms that only show up when the thing is meant to be sweet.
# "honey", "apple" and "cherry" are deliberately absent - they garnish
# savoury dishes here more often than they define sweet ones.
_SWEET_MARKERS = [
    # "Caramelised" is almost always onions on this menu - five savoury
    # dishes carried it - so the word only counts when it is the confection.
    r"\b(sweetened|candied)\b",
    r"\bcaramel(?:i[sz]ed)?\b(?![\s-]?onions?)",
    r"\b(chocolate|white chocolate|cocoa)\b",
    r"\b(whipped cream|buttercream|frosting|icing|glazed doughnut|streusel|crumble)\b",
    r"\b(condensed milk|dulce de leche|cajeta|nutella|gianduja)\b",
    # A sweet potato is a vegetable, and three savoury plates said so.
    r"\bsweet\b(?![\s-]?potato)(?![\s-]?(?:and|&|’n|n’)[\s-]?(?:sour|spicy|hot))",
]

# Proteins, starches and the aromatics that only season savoury cooking.
_SAVORY_TERMS = [
    r"\b(beef|pork|chicken|lamb|duck|turkey|bacon|sausage|brisket|steak|ribs?|"
    r"chorizo|jam(?:o|ó)n|prosciutto|schnitzel|meatballs?|wings?)\b",
    r"\b(shrimps?|crab|lobster|scallops?|fish|salmon|tuna|anchov(?:y|ies)|escargot)\b",
    r"(?<!cream )\bcheese\b",
    r"\b(cheddar|parmesan|gouda|mozzarella|feta|halloumi|queso|brie|gruy(?:e|è)re)\b",
    # Truffle is a mushroom on fries and a chocolate in a mousse; olive oil
    # turns up in cakes. Both only count in their savoury sense.
    r"\b(garlic|onions?|shallots?|leeks?|mushrooms?|capers?)\b",
    r"(?<!chocolate )(?<!almond )\btruffles?\b",
    r"\bolives?\b(?!\s+oil)",
    r"\b(potatoes?|fries|rice|noodles?|pasta|gnocchi|polenta|risotto|pretzel)\b",
    r"\bbread\b(?!\s+pudding)",
    r"\b(dumplings?|tacos?|poutine|soup|bisque|stew|chowder|slider|sandwich|wrap|pizza)\b",
    r"\b(hummus|a(?:i|ï)oli|gravy|pesto|chimichurri|vinaigrette|savou?ry|umami)\b",
]


def _any(patterns: list[str]) -> re.Pattern:
    return re.compile("|".join(patterns), re.IGNORECASE)


_SWEET_RE = _any(_SWEET_FORMS + _SWEET_MARKERS)
_SAVORY_RE = _any(_SAVORY_TERMS)


def extract_flavour_tags(*texts: str) -> list[str]:
    """`['sweet']`, `['savory']`, both, or `[]` when the copy says neither."""
    combined = " ".join(t for t in texts if t)
    if not combined:
        return []

    tags = []
    if _SWEET_RE.search(combined):
        tags.append("sweet")
    if _SAVORY_RE.search(combined):
        tags.append("savory")
    return tags


def flavour_payload(*texts: str) -> dict[str, list[str]]:
    """`{"flavor_tags": [...]}` when anything matched, `{}` when nothing did.

    Absence has to stay absence, the same as every other derived field here:
    an empty list from a source that simply describes a drink by its producer
    would otherwise outrank, at the curated layer, a source that actually
    described the thing.
    """
    tags = extract_flavour_tags(*texts)
    return {"flavor_tags": tags} if tags else {}
