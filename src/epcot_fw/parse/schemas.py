from typing import Any, Literal

from pydantic import BaseModel

EntityType = Literal["festival", "booth", "menu_item", "event", "seminar", "review"]


class ExtractedRecordDTO(BaseModel):
    """What a source adapter's parse() returns for one logical record on a page.

    `payload` shape depends on entity_type - see parse/schemas.py usages in each
    adapter for the fields each one populates. `natural_key_hint` is a normalized
    name used for cross-source matching (see normalize/text.py + resolve/matcher.py).
    """

    entity_type: EntityType
    natural_key_hint: str
    payload: dict[str, Any]
