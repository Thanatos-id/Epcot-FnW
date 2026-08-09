from epcot_fw.parse.html_utils import soupify
from epcot_fw.parse.images import (
    MIN_DIMENSION,
    extract_captioned_images,
)


def _extract(html: str):
    soup = soupify(f"<article>{html}</article>")
    return extract_captioned_images(soup.find("article"))


def test_extracts_figure_with_figcaption():
    images = _extract(
        '<figure><img src="https://ex.test/raclette.jpg" />'
        "<figcaption>Warm Raclette Swiss Cheese</figcaption></figure>"
    )
    assert len(images) == 1
    assert images[0].url == "https://ex.test/raclette.jpg"
    assert images[0].caption == "Warm Raclette Swiss Cheese"


def test_extracts_classic_wordpress_caption_markup():
    images = _extract(
        '<div class="wp-caption"><img src="https://ex.test/shrimp.jpg" />'
        '<p class="wp-caption-text">Grilled Bush Berry Shrimp</p></div>'
    )
    assert [i.caption for i in images] == ["Grilled Bush Berry Shrimp"]


def test_plain_div_without_wp_caption_class_is_ignored():
    images = _extract(
        '<div><img src="https://ex.test/x.jpg" /><figcaption>Something</figcaption></div>'
    )
    assert images == []


def test_uncaptioned_images_are_dropped():
    images = _extract('<figure><img src="https://ex.test/banner.jpg" /></figure>')
    assert images == []


def test_multiple_figures_preserve_document_order():
    images = _extract(
        '<figure><img src="https://ex.test/a.jpg" /><figcaption>Dish A</figcaption></figure>'
        '<figure><img src="https://ex.test/b.jpg" /><figcaption>Dish B</figcaption></figure>'
    )
    assert [i.caption for i in images] == ["Dish A", "Dish B"]


def test_repeated_image_keeps_only_the_first_caption():
    images = _extract(
        '<figure><img src="https://ex.test/hero.jpg" /><figcaption>The actual dish</figcaption></figure>'
        '<figure><img src="https://ex.test/hero.jpg" /><figcaption>Pin this!</figcaption></figure>'
    )
    assert len(images) == 1
    assert images[0].caption == "The actual dish"


def test_lazy_loaded_src_is_recovered():
    images = _extract(
        '<figure><img data-src="https://ex.test/lazy.jpg" />'
        "<figcaption>Lazy Dish</figcaption></figure>"
    )
    assert images[0].url == "https://ex.test/lazy.jpg"


def test_inline_data_uri_placeholder_is_not_mistaken_for_the_real_src():
    images = _extract(
        '<figure><img src="data:image/gif;base64,R0lGOD" data-lazy-src="https://ex.test/real.jpg" />'
        "<figcaption>Real Dish</figcaption></figure>"
    )
    assert images[0].url == "https://ex.test/real.jpg"


def test_ad_and_widget_images_are_filtered_by_src():
    html = "".join(
        f'<figure><img src="{src}" /><figcaption>Looks like a dish</figcaption></figure>'
        for src in (
            "https://forms.aweber.com/form/displays.htm?id=x",
            "https://dfbguide.lpages.co/thing.png",
            "https://ex.test/Disney-Adults-DFB-Homepage-Button-07-20-25-1.png",
            "https://ex.test/Food-Wine-Festival-Guide-Cover.png",
            "https://ex.test/site-logo.png",
        )
    )
    assert _extract(html) == []


def test_boilerplate_captions_are_rejected():
    html = "".join(
        f'<figure><img src="https://ex.test/{i}.jpg" /><figcaption>{cap}</figcaption></figure>'
        for i, cap in enumerate(["Click here for more", "Advertisement", "Photo credit: DFB"])
    )
    assert _extract(html) == []


def test_declared_small_images_are_treated_as_ui_sprites():
    small = MIN_DIMENSION - 1
    images = _extract(
        f'<figure><img src="https://ex.test/sprite.png" width="{small}" height="{small}" />'
        "<figcaption>Tiny Thing</figcaption></figure>"
    )
    assert images == []


def test_large_declared_images_are_kept():
    big = MIN_DIMENSION + 400
    images = _extract(
        f'<figure><img src="https://ex.test/dish.jpg" width="{big}" height="{big}" />'
        "<figcaption>Big Dish</figcaption></figure>"
    )
    assert len(images) == 1


def test_images_without_declared_dimensions_are_kept():
    images = _extract(
        '<figure><img src="https://ex.test/dish.jpg" /><figcaption>Undeclared Dish</figcaption></figure>'
    )
    assert len(images) == 1


def test_non_numeric_dimension_attributes_do_not_crash():
    images = _extract(
        '<figure><img src="https://ex.test/dish.jpg" width="auto" height="100%" />'
        "<figcaption>Odd Dimensions</figcaption></figure>"
    )
    assert len(images) == 1


def test_overlong_caption_is_rejected_as_prose():
    caption = "word " * 60
    images = _extract(
        f'<figure><img src="https://ex.test/dish.jpg" /><figcaption>{caption}</figcaption></figure>'
    )
    assert images == []


def test_caption_whitespace_is_collapsed():
    images = _extract(
        '<figure><img src="https://ex.test/dish.jpg" />'
        "<figcaption>\n  Spaced   Out\t Dish \n</figcaption></figure>"
    )
    assert images[0].caption == "Spaced Out Dish"


def test_figure_without_an_image_is_skipped():
    assert _extract("<figure><figcaption>Caption only</figcaption></figure>") == []
