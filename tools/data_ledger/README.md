# Data ledger

Builds `docs/index.html` — a self-contained page showing the current state of
the crawled festival database, what changed since the previous snapshot, and
how well tested the pipeline producing those numbers is.

## Building

```bash
python tools/data_ledger/export_snapshot.py   # DB  -> epcot_db_snapshot.json
python tools/data_ledger/fetch_images.py      # adds inlined booth photos
python tools/data_ledger/build_artifact.py    # -> docs/index.html
```

`epcot_db_snapshot.json` is gitignored — it is a build input, regenerated from
the database, and carries ~1.3MB of inlined image data.

## Change tracking

`build_artifact.py` records each snapshot's aggregate metrics into
`ledger_history.json` (committed) and renders a **What changed** section
comparing the current snapshot with the previous one. Metric direction is
declared in `metrics.py`: most counts are better when they rise, while
`open_conflicts` is better when it falls, so a drop there renders as a gain
rather than a loss.

Rebuilding without a fresh crawl does not append a duplicate row — an entry
whose metrics match the newest one replaces it in place, so the page never
shows a fabricated "no change" comparison against itself.

The first entry is a **baseline**: with nothing to compare against, the page
says so instead of rendering zero-deltas.

## Dish photos

`fetch_images.py` inlines two kinds of image: the booth-level photo on
`booth.image_url`, and the per-dish photo on each item's `image_url`. Dish
photos come from Disney Food Blog's per-booth "photos of menu items" posts,
which `refresh` discovers and crawls (see
`sources/disney_food_blog.py`). The **Dishes photographed** row in *What
changed* tracks how that coverage moves between crawls.

Expect that row to sit at 0 until the festival is open. Those posts only get
photographed once the booths are serving, and discovery ignores any post
whose slug names a different year — the undated hub keeps serving last
season's line-up until the new one is published, and ingesting it would
attach last year's plates to this year's dishes.

## Pipeline confidence

`pipeline_metrics.json` holds the test-coverage readings shown in the
confidence panel. Refresh the `current` block after a coverage run:

```bash
python -m pytest --cov=src/epcot_fw --cov-report=json:coverage.json -q
python tools/data_ledger/record_pipeline_metrics.py coverage.json <test-count>
```

The `baseline` block is a fixed historical measurement of a specific commit
and is intentionally not recomputed.

## Icons / Add to Home Screen

`assets/icons/` and `assets/manifest.json` are the source of truth; every
build copies them into `docs/` so `docs/` stays a pure build output. The build
fails rather than publishing a page whose `<link>` targets are missing.

Two deliberate choices:

- **Relative paths, not root-absolute.** `docs/` is published at a project
  subpath (`…github.io/Epcot-FnW/`), so `/icons/…` would resolve to the domain
  root and 404. Relative paths also keep the page working opened off disk.
  This is the one change from the icon set's bundled `head-snippet.html`.
- **Real files, not data: URIs.** The rest of the page inlines its images, but
  iOS ignores `data:` URIs for `apple-touch-icon`, which is exactly the tag
  that governs the Add-to-Home-Screen icon.

`apple-touch-icon.png` must stay 180×180 with no alpha channel — iOS fills
transparent pixels with black. To regenerate any size, edit the geometry
constants in `assets/build_icon.py` and run `assets/export_icons.py`; see
`assets/ICONS-README.md` for the artwork notes.

## Layout

The page is responsive and is expected to be read on a phone as well as a
desktop. Two things to preserve when editing the template:

- the `<meta name="viewport">` tag — without it, mobile browsers lay the page
  out at ~980px and scale it down, which is what made the ledger unreadable on
  a phone before;
- no element may exceed the viewport width. `tools/data_ledger` has no browser
  test harness, so check by loading `docs/index.html` at 320px, 390px, 768px
  and 1440px and confirming `document.documentElement.scrollWidth` never
  exceeds `clientWidth`.
