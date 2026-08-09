from epcot_fw.parse.generic_blog import extract_priced_items
from epcot_fw.parse.html_utils import soupify

ARTICLE_HTML = """
<article>
  <h2>The Alps</h2>
  <p>Just a description paragraph with no dollar amount at all.</p>
  <ul>
    <li>Cheese Plate — $8.50</li>
    <li>Vegan Chili Bowl - $6 (vegan, gluten-free)</li>
  </ul>
  <h3>Regal Eagle</h3>
  <ul>
    <li>Smoked Wings - $9 (contains peanuts)</li>
  </ul>
  <h4>{long_heading}</h4>
  <ul>
    <li>Mystery Item - $5</li>
  </ul>
</article>
""".format(long_heading="X" * 85)


def _parse():
    soup = soupify(ARTICLE_HTML)
    return extract_priced_items(soup.find("article"))


def test_skips_headings_and_prose_without_a_price():
    records = _parse()
    assert all(r.entity_type == "menu_item" for r in records)
    assert len(records) == 4


def test_associates_each_item_with_the_nearest_preceding_heading():
    records = _parse()
    by_name = {r.payload["name"]: r for r in records}
    assert by_name["Cheese Plate"].payload["booth_name"] == "The Alps"
    assert by_name["Vegan Chili Bowl"].payload["booth_name"] == "The Alps"
    assert by_name["Smoked Wings"].payload["booth_name"] == "Regal Eagle"


def test_overlong_heading_is_ignored_so_prior_heading_still_applies():
    records = _parse()
    mystery = next(r for r in records if r.payload["name"] == "Mystery Item")
    assert mystery.payload["booth_name"] == "Regal Eagle"


def test_name_is_split_off_before_the_price_marker():
    records = _parse()
    by_name = {r.payload["name"]: r for r in records}
    assert "Cheese Plate" in by_name
    assert "$" not in by_name["Cheese Plate"].payload["name"]


def test_picks_the_lowest_price_when_multiple_prices_appear():
    soup = soupify("<article><ul><li>Combo $12 or single $7</li></ul></article>")
    records = extract_priced_items(soup.find("article"))
    assert records[0].payload["price_usd"] == "7"


def test_dietary_tags_and_category_are_detected_from_the_text():
    records = _parse()
    by_name = {r.payload["name"]: r for r in records}
    vegan_item = by_name["Vegan Chili Bowl"]
    assert set(vegan_item.payload["dietary_tags"]) >= {"vegan", "gluten_free"}
    assert vegan_item.payload["category"] == "food"


def test_category_is_alcoholic_beverage_when_alcohol_tag_detected():
    soup = soupify("<article><ul><li>House Red Wine $9</li></ul></article>")
    records = extract_priced_items(soup.find("article"))
    assert records[0].payload["category"] == "alcoholic_beverage"
    assert "contains_alcohol" in records[0].payload["dietary_tags"]


def test_overlong_text_block_is_skipped_even_with_a_price():
    long_text = "Word " * 100 + "$5"
    soup = soupify(f"<article><ul><li>{long_text}</li></ul></article>")
    records = extract_priced_items(soup.find("article"))
    assert records == []
