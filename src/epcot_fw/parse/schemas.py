from typing import Any, Literal

from pydantic import BaseModel

EntityType = Literal["festival", "booth", "menu_item", "event", "seminar"]


class ExtractedRecordDTO(BaseModel):
    """What a source adapter's parse() returns for one logical record on a page.

    `payload` shape depends on entity_type - see parse/schemas.py usages in each
    adapter for the fields each one populates. `natural_key_hint` is a normalized
    name used for cross-source matching (see normalize/text.py + resolve/matcher.py).

    Build it as `normalize_name(name)` over the *whole* name, never a prefix of
    one. resolve/merge.py scores this hint against candidate keys built by
    `_load_scoped_candidates` from the full canonical name, so anything the hint
    drops that the candidate keeps is scored as a difference. Several adapters
    used to cut the name at 80 characters first, which meant a dish whose name
    ran past 80 could not match *itself*: two byte-identical 137-character names
    scored 78.5 against each other, under the 90 auto-merge threshold, and every
    long-named dish re-resolved as a stranger on each crawl. The column is
    `Text`, so there is nothing to truncate for.
    """

    entity_type: EntityType
    natural_key_hint: str
    payload: dict[str, Any]
