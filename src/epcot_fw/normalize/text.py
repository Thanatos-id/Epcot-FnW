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
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Normalize a booth/menu-item/artist name into a stable matching key.

    Lowercases, strips accents, drops parenthetical asides and common festival
    boilerplate ("Booth", "Presented by X"), collapses whitespace/punctuation.
    """
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _PAREN_RE.sub(" ", text)
    text = _BOILERPLATE_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text
