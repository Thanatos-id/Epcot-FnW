"""resolve/merge.py's cross-field guard: a dish cannot be a non-alcoholic drink
while carrying the contains_alcohol tag.

`category` resolves by source priority and `dietary_tags` by union, so the two
can land in contradiction with nothing else to reconcile them - which is how
Summer in Spain reached the app as a non-alcoholic beverage with a Contains
Alcohol badge.
"""

from epcot_fw.db.models import DietaryTag, MenuItem
from epcot_fw.resolve.merge import _enforce_alcohol_consistency


def _item(category: str, *tag_codes: str) -> MenuItem:
    item = MenuItem(canonical_name="x", category=category)
    item.dietary_tags = [DietaryTag(code=c, label=c) for c in tag_codes]
    return item


def test_alcohol_tag_beats_a_non_alcoholic_category():
    item = _item("non_alcoholic_beverage", "contains_alcohol")
    _enforce_alcohol_consistency(item)
    assert item.category == "alcoholic_beverage"


def test_a_soft_drink_is_left_alone():
    item = _item("non_alcoholic_beverage", "vegetarian")
    _enforce_alcohol_consistency(item)
    assert item.category == "non_alcoholic_beverage"


def test_absence_of_the_tag_is_not_evidence_of_anything():
    """Only one direction is enforced. Plenty of cocktails are named without a
    word dietary_tags.py catches, so an untagged drink keeps whatever category
    resolution gave it rather than being demoted to soft."""
    item = _item("alcoholic_beverage")
    _enforce_alcohol_consistency(item)
    assert item.category == "alcoholic_beverage"


def test_food_is_never_touched():
    item = _item("food", "contains_alcohol")
    _enforce_alcohol_consistency(item)
    assert item.category == "food"
