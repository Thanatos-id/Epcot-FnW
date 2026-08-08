import re

_TAG_PATTERNS: dict[str, re.Pattern] = {
    "vegan": re.compile(r"\bvegan\b", re.IGNORECASE),
    "vegetarian": re.compile(r"\bvegetarian\b", re.IGNORECASE),
    "plant_based": re.compile(r"\bplant[\s-]based\b", re.IGNORECASE),
    "gluten_free": re.compile(r"\bgluten[\s/-]?(free|friendly|wheat friendly)\b", re.IGNORECASE),
    "contains_alcohol": re.compile(
        r"\b(wine|beer|lager|ale|cocktail|spirits?|liquor|sake|cider|margarita|"
        r"champagne|prosecco|sangria|mimosa|brewery|winery)\b",
        re.IGNORECASE,
    ),
    "spicy": re.compile(r"\bspicy\b", re.IGNORECASE),
    "contains_nuts": re.compile(r"\b(peanut|almond|cashew|walnut|pecan|hazelnut|pistachio)s?\b", re.IGNORECASE),
}


def extract_dietary_tags(*texts: str) -> list[str]:
    """Scan free-text (item name, description, notes) for known dietary-tag keywords."""
    combined = " ".join(t for t in texts if t)
    return [code for code, pattern in _TAG_PATTERNS.items() if pattern.search(combined)]
