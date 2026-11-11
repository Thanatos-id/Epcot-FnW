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

Master/detail: a 320px booth rail on the left, one booth's whole menu on the
right, and an empty state until something is picked. A booth is the unit
someone actually works in — 209 dishes in one flat column was a list nobody
could hold in their head, and a dish is only ever judged against the others
on the same menu. It also puts the booth's coordinate at the top of its own
menu instead of repeating it on every dish that inherits it.

The page is one viewport: `body` is a grid of the top bar, a status line and
the workspace, `height: 100dvh`, and the rail and the detail each scroll on
their own. Nothing is measured at runtime. An earlier version had a fixed
bottom export bar and sized both panes from its measured height; it was
wrong on some device every time the bar wrapped, so the bar became a grid
row at the top and the measuring went. Inside the detail only the dish
toolbar (with the booth's name) is sticky — the booth's own fields scroll
away, because pinned they took a third of a laptop screen from the dishes.

The map is a drawer that slides in from the right, opened from a booth's
**Place on map** / **Edit pin** or from **Map** in the top bar (all booths;
click a pin to open that booth). A pin clicked or dragged there is a draft:
nothing reaches `state.placements` until **Save location**, and Close,
Cancel and Esc (with a confirmation when a draft exists) leave things as
they were.

The top bar switches between Epcot's four festivals. A festival has rows from
one of two places (`festival_catalog` marks it `has_data` and records the
`source`):

- **database**: the festival the snapshot was exported from (Food & Wine).
- **research**: a festival researched by hand into `data/festivals/<key>/`
  (Arts, Flower & Garden, Holidays). `build_artifact.py` reads these through
  `epcot_fw.festival_files`. Each one appears in the switcher with a
  "Research" note above the work and a label on every dish saying how sure
  the research is (*2026 menu*, *Likely 2027*, *Confirmed 2027*), and
  whether it's part of that festival's food stroll (*Cookie Stroll*,
  *Garden Graze*, *Wonderful Walk*).

One page load works on one festival. Its rows, its saved edits
(`epcot-studio-v1:<key>`) and its photo store (`epcot-studio:<key>`) belong
to that festival. The database festival keeps the unsuffixed keys it has
always had. Switching to another festival with rows reloads the page. A
research festival's changeset carries `"festival": "<key>"`, and
`studio apply` writes it back into that folder rather than `data/manual/`.
See `data/festivals/README.md`. A festival with neither source shows an
empty state.

The look is deliberately plain: white and light grey, square corners, 1px
rules instead of shadows, Inter and Inter Tight, and one colour — orange —
reserved for "this has changed" and "this is the pin you are placing".

### Alerts, phones, and the rail

- **Toasts.** Everything the page has to say (a festival's research note,
  publish progress, edits that went live, a storage problem, a newer
  version) arrives as a light-blue toast at the foot of the screen. Each can
  be dismissed. Long ones show three lines with More.
- **What toasts where.** A festival's own notes toast only on that festival.
  Important alerts, like a failed publish or a newer version, toast wherever
  you are.
- **Staying clear of the work.** The panes scroll far enough to bring their
  last row above any toast, the open map drawer hides them, and on a phone
  they sit above the rail's Add booth button.
- **The bell.** Every alert stays listed under the bell in the top bar until
  cleared, including dismissed ones (with a Show button). The bell goes blue
  for anything unread and blue with an orange dot for something important.
  The list is kept across the reload a festival switch does, so it's
  `notify()` in the page script, stored under `epcot-studio-alerts-v1`.
- **Phones (≤ 640px).** The top bar becomes two rows: the edit count and
  actions, then the festival switcher across the full width (Arts, F&G, F&W,
  Holidays). Map and Assistant move into the ⋯ menu. The menu toolbar scrolls
  away instead of pinning, and so it does on any screen under 560px tall,
  such as a phone held sideways. Dialogs always scroll within the screen.
- **The rail.** Hovering a booth turns its row black with white text. The
  open booth keeps its own look, so the two never read the same. Hover only
  applies where a pointer can hover, so a tap on a phone doesn't leave a row
  stuck black.

### Publishing from the page

**Publish** (the primary button once a GitHub token is saved under ⋯ →
Connections) previews every change, then pushes one branch,
`studio/publish-<id>`, holding the changeset. `.github/workflows/studio-publish.yml`
checks it, tests the result and commits it to `main`. The page tracks the run
and reads the outcome from a comment the workflow leaves on the request's
commit. `studio/dryrun-<id>` runs the checks only; `studio/revert-<sha>` undoes
one publish. See `docs/WORKFLOW.md`.

Because the page can now hold a token:

- Leaflet is vendored (`assets/vendor/leaflet/`, copied to `docs/vendor/`), so
  the page runs no script from another host.
- A Content-Security-Policy meta tag limits requests to this site, GitHub's
  API and Anthropic's. Images (photos, map tiles) may come from any https host.
- Secrets live under their own storage key, `epcot-studio-secrets-v1`, apart
  from the edits. `thanatos-id.github.io` is one origin shared by every Pages
  site on the account, so another of the account's own sites could read them.

### The assistant

With a Claude API key saved under ⋯ → Connections, an **Assistant** button
opens four jobs:

- **Audit**: wrong category or drink kind, missing tags, duplicates, names
  that carry a description, and odd prices.
- **Import a menu**: paste a menu, or a link Claude reads with web fetch. It
  proposes returning, changed, new and removed dishes, and sets a researched
  festival's menu status.
- **Bulk edit**: one instruction becomes the edits it implies.
- **Photos & copy**: checks each photo shows its dish, and tidies descriptions.

Claude proposes; you decide. Each proposal is checked against the page before
it is shown: the booth and dish must exist, the edit must change something,
and the price and status must be ones the festival uses. Anything that fails
is listed with its reason. Accepting a proposal goes through the same
`setValue` / Add / `removeRow` paths a hand edit does, so it becomes an
ordinary pending edit: orange, revertable, in the Publish preview, and live
only once published. Claude's text reaches the page only as text.

How it calls Claude:

- **Direct from the browser:** raw HTTP to `api.anthropic.com` with the
  browser-access header. No SDK, because the page has no build step.
- **Model and output:** `claude-opus-5-5`, streamed, with structured output
  (`output_config.format`). Audit and import run at effort high, the other
  two at medium.
- **Refusals:** a declined request retries on Anthropic's recommended
  fallback model (`fallbacks: "default"`).
- **Caching:** the festival's catalogue is cached, so a second run on the
  same festival reads it at a tenth of the price. The panel shows each run's
  approximate cost.

A researched dish's menu status is now an editable field (the small select
beside its labels), and changesets carry it.

### As an installed app

The studio installs from Chrome as **Epcot Studio**, a standalone app with
its own window: open it, then use the install icon in the address bar or
**⋯ → Install as app**. It has its own manifest (`assets/studio.webmanifest`,
so it opens on the studio rather than the ledger) and a service worker
(`assets/studio-sw.js`, which Chrome requires before it offers Install).
`build_artifact.py` copies both into `docs/`.

The worker is network first and scoped to the studio's own files. Every
launch fetches the current `studio.html`, so a rebuild (or, for the Pages
copy, a merge to main) is what the app shows next; its cached copy is only
used when the server cannot be reached. A window left open notices a newer
build on focus and offers **Reload** — edits are saved as they are made, so
nothing is lost by taking it.

An app installed from `localhost:8123` and one installed from GitHub Pages
are different origins, and so keep separate unexported edits.

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
