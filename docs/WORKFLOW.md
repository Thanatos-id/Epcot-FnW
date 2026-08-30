# Correcting the database

The loop from opening `studio.html` to seeing the change on the published
site. Everything here runs from the repo root with the project's venv
active:

```bash
cd /path/to/Epcot
source .venv/bin/activate
```

Without the venv, `epcot-fw` is not on your PATH and none of the commands
below resolve.

## 1. Work in the studio

Open `docs/studio.html` — off disk, or the published copy. Pick a booth on
the left and its whole menu opens on the right: titles, descriptions,
prices, categories and dietary tags editable in place, a photo attachable
per dish, the booth placeable on the map, and dishes or booths addable by
hand where the crawl found none.

Edits stay in the browser until exported, so the list can be worked through
across several sittings. Photos are held in IndexedDB rather than
localStorage — a handful of camera-roll shots is past that quota — which
means clearing site data for the page loses anything not yet exported.

Finish with **Export changeset** → **Download changeset**. The file lands in
`~/Downloads` as `epcot-changeset-<timestamp>.json`.

## 2. Look before applying

```bash
epcot-fw studio apply --dry-run "$(ls -t ~/Downloads/epcot-changeset-*.json | head -1)"
```

Picks the newest changeset and writes nothing. Worth reading for the
`skipped` lines — see [When something doesn't land](#when-something-doesnt-land).

## 3. Apply it

```bash
epcot-fw studio apply "$(ls -t ~/Downloads/epcot-changeset-*.json | head -1)"
```

Decodes attached photos into `docs/dish-photos/`, rewrites their URLs to the
published Pages path, merges the rest into `data/manual/menu_items.json` and
`data/manual/booth_locations.json`, then stages and re-resolves.

**`epcot-fw manual` is not needed afterwards** — this command already does
it. Everything lands under the `manual` source at `priority_rank 0`, so it
beats every crawled source and survives the next refresh.

## 4. Let this season's photos win

```bash
epcot-fw images promote
```

`backfill-images` stages photos found in prior seasons into the curated file
at rank 0, which outranks every later observation permanently. That is free
while the current season has no photos of its own and stops being free the
moment it does: the dish shows last year's plate while an actual photo of
what is being served today sits underneath it, selected against.

This clears the historical value wherever a current-season one has arrived,
and only then. A photo published from the studio is left alone whatever the
crawl finds — that is an answer, not a stand-in. Safe to run every time; it
reports `0` when there is nothing to do.

## 5. Rebuild the pages

Three commands, in this order:

```bash
python tools/data_ledger/export_snapshot.py
python tools/data_ledger/fetch_images.py
python tools/data_ledger/build_artifact.py
```

**The middle one is not optional.** `export_snapshot` writes a snapshot with
no image data, `fetch_images` inlines the photos, `build_artifact` renders
the pages. Skipping it strips every photo from the studio and the ledger and
takes the page from megabytes to a couple of hundred kilobytes — which looks
like a successful build.

## 6. Check what changed

```bash
git status --short
```

A normal round touches:

| Path | Why |
|---|---|
| `data/manual/menu_items.json` | dish corrections and photo URLs |
| `data/manual/booth_locations.json` | pins and booth fields |
| `docs/dish-photos/` | photos attached in the studio (new on the first one) |
| `docs/index.html`, `docs/studio.html`, `docs/survey.html` | rebuilt pages |
| `docs/v1/snapshot.json` | the feed the phone app reads |
| `tools/data_ledger/ledger_history.json` | one row per snapshot whose metrics moved |

`tools/data_ledger/epcot_db_snapshot.json` is gitignored — it is a build
input, regenerated from the database, and carries megabytes of inlined
image data.

## 7. Commit and publish

```bash
git add data/manual docs tools/data_ledger/ledger_history.json
git commit -m "Studio: what you corrected"
git push
```

GitHub Pages serves **`main`**, so work done on a branch is not published
until it gets there — merge it, or open a pull request and merge that. Pages
takes a minute or so, then the change is live at
`https://thanatos-id.github.io/Epcot-FnW/studio.html`.

Add paths explicitly rather than `git add -A`: the repo root can hold a
`dish-photos/` working folder from `epcot-fw images export`, which is a
staging area for external photo processing and not something to commit.

## When something doesn't land

**`skipped … missing booth_name or name`** — a dish is only identified by
the pair, so one without both cannot be matched to anything. Usually a
hand-added dish saved without picking a booth.

**A caption-shaped dish appeared on a menu** — shouldn't happen; records
from review posts are `attach_only` and can attach a photo to a dish but
never create one. Worth reporting if it does.

**A hand-added dish disappeared after a crawl** — also shouldn't happen.
Anything added by hand carries `origin = 'curated'`, which is what excludes
it from `pipeline/reconcile.py`'s retirement pass.

**A photo you cleared came back** — clearing writes an explicit `null`,
which is an assertion and not an omission. If a later crawl supplies a new
one, clear it again, or attach your own: a studio photo always wins.

**Photos look like last year's** — run step 4, then step 5.

## The rest of the cycle

A refresh runs **daily at 03:00** (`scripts/launchd/com.epcot.foodwine.refresh.plist`).
It updates the database only; `docs/` is a build output and stays as it was
until steps 5–7 are run, which is deliberate — rebuilding rewrites
`ledger_history.json` and dirties `docs/`, and that is a thing to review and
push rather than something a 3am job should decide.

Two commands worth knowing between rounds:

```bash
epcot-fw backfill-reviews --max-pages 3   # sweep the season's DFB reviews for photos
epcot-fw ingest <url>                     # read one post you found yourself
```

Both are polite about it and stop early when the site starts returning
errors. Disney Food Blog answers a burst with 429, and pressing on is how a
source that rate-limits you becomes one that blocks you outright —
`allears.net` is what that looks like from the other side.

See also [`../data/manual/README.md`](../data/manual/README.md) for what the
curated files mean, and [`../tools/data_ledger/README.md`](../tools/data_ledger/README.md)
for how the pages are built.
