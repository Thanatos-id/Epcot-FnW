# Data ledger

Builds the three pages in `docs/`, all from one snapshot so none of them can
disagree about what is in the database:

| Page | Built by | For |
|---|---|---|
| `index.html` | `build_artifact.py` | Reading: what the crawl found, what changed, how well tested the pipeline is |
| `studio.html` | `build_studio.py` | Correcting: pick a booth, then edit any dish on its menu, attach a photo, place the booth, add what the crawl missed |
| `survey.html` | `build_survey.py` | Walking: one-tap GPS capture per booth, in the park |

`studio.html` replaced `editor.html` and `map.html`, which split one job in
half — correcting a dish meant opening two pages and hand-merging two paste
blocks into two curated files, and neither could attach a photo or add a dish
the crawl never found. `build_artifact.py` deletes both if it finds them, so
a stale copy cannot keep being served by Pages.

## Building

```bash
python tools/data_ledger/export_snapshot.py   # DB  -> epcot_db_snapshot.json
python tools/data_ledger/fetch_images.py      # adds inlined booth + dish photos
python tools/data_ledger/build_artifact.py    # -> docs/index.html, studio.html, survey.html
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

## The studio's shape

Master/detail: a 450px booth rail on the left, one booth's whole menu on the
right, and an empty state until something is picked. A booth is the unit
someone actually works in — 209 dishes in one flat column was a list nobody
could hold in their head, and a dish is only ever judged against the others
on the same menu. It also puts the booth's coordinate at the top of its own
menu instead of repeating it on every dish that inherits it.

Above 900px each pane is pinned and scrolls on its own: 32 booths against a
menu that runs to 21 dishes, and on one page scroll the rail runs out long
before the menu does, so working down a long menu meant losing the booth you
were in. Three consequences worth remembering when editing that block — cards need
`flex: none` or a bounded flex column shrinks them to slivers instead of
overflowing; `.wrap`'s bottom reserve has to come off, or the page gets more
scroll range than the header can absorb and both panes drag off the top; and
`.layout` needs its `min-height`, or the panes shrink to fit, that shortens
the page, that leaves no scroll range to move the header away, and they stay
short forever.

Everything that has to clear the fixed export bar is sized from
`--bar-height`, measured at runtime. The bar is not one height: it wraps to
two rows when the change count grows or the screen narrows (61px against
109px, which is the difference between a clear last card and a covered one)
and it gains the safe-area inset on a phone. `--pane-max` is measured too,
because a `sticky` pane only sits at `--shell-top` once the page has
scrolled far enough to push it there; sizing for the pinned case alone put
the bottom of both lists behind the bar at every other scroll position,
including the one selecting a booth scrolls you to.

Both are re-measured where they change - after `renderCounts`, on resize -
rather than left to a `ResizeObserver` alone, which rides the rendering
steps and does not run while the tab is hidden.

Each pane carries its own filters, because one search box over both lists
reads as a single search and behaves as two. The rail's chips are about a
booth as a whole (*not placed*) or about work done anywhere inside it
(*edited*, *added by hand*) — a booth whose only change is one corrected dish
still has to be findable, or the filter cannot answer the question it exists
to answer. Below 900px the two panes take turns rather than shrinking.

## Photo credit

Every photo on these pages was taken by somebody else, almost all of them by
Disney Food Blog. `pipeline/photo_source.py` traces a served `image_url`
back through provenance to the source that offered it and, where a crawl
found it, the post it ran in. That travels in the snapshot as
`image_source` and renders as the credit line under each thumbnail.

Attribution matches on the value being served, not on
`entity_field_provenance.is_selected`. That flag is not reliable - most
dishes carry a row holding exactly the URL on the dish and still flagged
unselected - and crediting the wrong post is worse than crediting none.

The credit element is a contract another page reads, so it is covered by a
test that fails if the class or the `data-*` attributes move:

```html
<div class="photo-credit"
     data-credit="Disney Food Blog" data-site="www.disneyfoodblog.com"
     data-season="2026" data-page-url="https://…/review-…/"
     data-via="disney_food_blog" data-image-url="https://…/waffle.jpg"
     data-dish="Belgian Waffle" data-booth="Belgium"
     data-public-id="e0838d90-…">Photo: Disney Food Blog · 2026 · source</div>
```

## The studio's changeset

The studio's edits leave as one downloaded file rather than a paste block,
because a photo is bytes and base64 in a textarea is not something anyone can
paste into JSON by hand. `epcot-fw studio apply <file>` reads it back: photos
land in `docs/dish-photos/`, everything else merges into the curated files at
`priority_rank 0`, and the result is staged and re-resolved in one command.
`--dry-run` reports on a file without touching anything.

Rows added by hand come back with `origin = "curated"`. That column exists
for one reason: `pipeline/reconcile.py` retires anything no live crawled page
vouches for, and no crawled page will ever vouch for a dish the sources have
not noticed. Curated rows are skipped by that pass entirely — their
`is_active` comes from the curated file instead, which is how deleting one
works.

## App feedback

`docs/index.html` carries one panel that isn't built from the snapshot: **App
feedback**, a live client-side fetch of GitHub issues labelled
`app-feedback` on this repo. Everything else on these pages is baked in at
build time; this one deliberately isn't, because feedback the ledger can
only show as of the last rebuild defeats the point of surfacing it.

The round trip has no server of this project's own in it. The iOS app files
an issue directly against `POST /repos/Thanatos-id/Epcot-FnW/issues` using a
repo-scoped, `issues: write`-only token (see `FeedbackService.swift` in the
Epcot Events app), and the ledger reads it back with an unauthenticated
`GET` — GitHub's REST API allows anonymous, CORS-enabled reads of a public
repo's issues, so no proxy or credential is needed for this half.

A `bug` or `enhancement` label (GitHub's own defaults) picks the badge
colour; a fetch failure — offline, rate-limited at 60 req/hr per IP — falls
back to a link to view issues directly on GitHub rather than taking the rest
of the page down with it.

## Retired entities

The export counts only `is_active` booths and dishes, matching what
`/api/v1/snapshot` serves. When a new season's lineup lands, anything the
sources have stopped listing is retired by `pipeline/reconcile.py`, so the
booth and menu-item rows in *What changed* can legitimately go **down** at a
season boundary. That is a correction, not data loss — the rows are still in
the database, just no longer part of the running festival.

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
  test harness, so check by loading `docs/index.html` and `docs/studio.html`
  at 320px, 390px, 768px and 1440px and confirming
  `document.documentElement.scrollWidth` never exceeds `clientWidth`. A
  `<select>` is the usual culprit: it is sized by its widest option unless
  told otherwise, and the booth list holds "Additional Festival Locations".
