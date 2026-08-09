import re
import unicodedata

_BOILERPLATE_TOKENS = [
    r"\bbooth\b",
    r"\bkiosk\b",
    r"\bmarketplace\b",
    r"\bmenu\b",
    r"\bpresented by [\w'&]+(\s[\w'&]+)*",
    r"\bhosted by [\w'&]+(\s[\w'&]+)*",
    r"<—.*",
    r"<-.*",
    r"click to see.*",
]
_BOILERPLATE_RE = re.compile("|".join(_BOILERPLATE_TOKENS), re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")
# Some sources fold pricing and serving size straight into the item name
# ("Frozen Rose - $9.50", "... - 6 oz $5.75 / 12 oz $9.75"). That is pricing
# detail, not identity: the same drink appears without it elsewhere, and on a
# photo caption. Left in, the digits dominate the match key and drag an
# obvious pairing down into the review band. Stripped before punctuation
# removal, since that step would otherwise turn "$9.50" into the tokens
# "9 50".
_PRICE_RE = re.compile(r"\$\s*\d+(?:[.,]\d{1,2})?")
_SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:oz|ounces?|ml|cl|lit(?:er|re)s?)\b", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Normalize a booth/menu-item/artist name into a stable matching key.

    Lowercases, strips accents, drops parenthetical asides, common festival
    boilerplate ("Booth", "Presented by X") and any embedded price/serving
    size, collapses whitespace/punctuation.
    """
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _PAREN_RE.sub(" ", text)
    text = _BOILERPLATE_RE.sub(" ", text)
    text = _PRICE_RE.sub(" ", text)
    text = _SIZE_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text
