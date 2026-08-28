# Curated data

Hand-surveyed facts that no crawled source publishes, plus corrections and
photo backfills for `docs/editor.html` and `epcot-fw backfill-images` to
write into.

## Dish photos

`data/manual/menu_items.json` holds curated fields for individual dishes -
most often `image_url`. Two ways it gets filled:

- **The editor** (`docs/editor.html`) exports a block here when you correct
  a dish by hand.
- **`epcot-fw backfill-images --confirm-tos`** searches prior seasons of
  Disney Food Blog's per-booth photo posts for photos of dishes still on the
  current menu, and stages confident matches here. `--years N` sets how far
  back to look (default 5); `--dry-run` reports what it would find without
  writing anything. It only ever attaches a photo to a dish already active
  on the current menu - a caption for a dish that hasn't returned this
  season is reported and dropped, never used to invent one - and it never
  touches a booth's photo, only a dish's.

A third way covers photos that need to be reworked, not just found:

- **`epcot-fw images export ./dish-photos`** downloads every active dish's
  current photo into a folder, named by its stable `public_id`, plus a
  `manifest.json`. Run the whole folder through whatever external tool you
  like - an AI pass for a consistent look, a manual crop - and bring the
  results back with **`epcot-fw images import ./dish-photos`**, which
  publishes the processed files into `docs/dish-photos/` (so a normal commit
  + push serves them from GitHub Pages, same as the rest of the ledger) and
  stages their URLs here. Matching is by `public_id` alone, so a rename or a
  changed file extension during processing doesn't break the round trip.
  Unlike the backfill above, this **does** overwrite an existing `image_url`
  - running it is a decision to publish exactly what's in that folder.

Either way, apply what's staged with:

```bash
epcot-fw manual        # stage + re-resolve
```

An entry looks like this:

```json
{
  "menu_items": [
    { "booth_name": "Germany", "name": "Kirschwasser Torte",
      "image_url": "https://example.com/photo.jpg" }
  ]
}
```

Like the booth fields below, an `image_url` already sitting here - typed by
hand or staged by an earlier backfill run - is never overwritten by a later
one. Clear it in the editor first if you want a fresh run to replace it.

## Why the booth fields exist

Sorting booths by distance needs coordinates, and not one of the seven
crawled sources emits a latitude. Booth positions are stable season to
season, so this is worth surveying once and keeping.

## How to survey

Open **`docs/survey.html`** on a phone in the park — published alongside the
ledger, so it's one tap from the home-screen icon. Walk up to a booth, hit
Capture, and the browser's own GPS fix goes into the list. It keeps what you
capture in local storage, so closing the tab or losing signal mid-lap doesn't
lose the morning's work, and Copy JSON at the end gives you exactly the block
below to paste in.

## How to place from a map

No trip to the park needed: open **`docs/map.html`**, pick a booth from the
list, hit **Drop pin**, then click its spot on a real satellite/street map —
lined up against Disney's own released festival map, or just memory of the
layout. Drag a dropped pin any time to nudge it, and Copy JSON at the end
gives you the same block below to paste in. Useful the moment Disney
publishes a new festival map, well before anyone can walk the park to survey
it for real.

By hand, an entry looks like this:

```json
{
  "booths": [
    {
      "name": "The Alps",
      "latitude": 28.370536,
      "longitude": -81.549472,
      "location_precision": "surveyed",
      "location_description": "World Showcase, between Germany and Italy"
    }
  ]
}
```

Then apply it:

```bash
epcot-fw manual        # stage + re-resolve
```

## Three grades of coordinate

`location_precision` records what a number is worth, because very different
things end up in the same column:

- **`surveyed`** — a GPS fix taken standing at the booth. Good to a few
  metres. This is the real thing.
- **`mapped`** — a pin dropped by eye on a real map (`docs/map.html`),
  matched against Disney's own festival map or satellite imagery. Better
  than an anchor — it's actually placed at the booth, not a pavilion
  standing in for it — but still an eyeballed estimate, not a fix.
- **`anchored`** — the published coordinate of the pavilion a booth is named
  after, standing in until someone places or surveys it. Good to 30–50 m:
  enough to put a booth on the right side of World Showcase, not enough to
  order two booths you can see at the same time.

Eight booths ship anchored, from the Wikipedia/Wikidata pavilion coordinates.
Everything else — Refreshment Outpost, Brew-Wing Lab, and every themed kiosk
like Swirled Showcase or Bramblewood Bites — has no coordinate at all,
because nobody publishes one. A better grade always supersedes a worse one:
they all land in the same file, and the more precise value wins on recency.

A client that shows a distance is expected to qualify an anchored one
("about 200 ft, approximate") rather than presenting it as measured.

This also runs automatically at the start of every crawl and refresh, so an
edit is picked up on the next scheduled run either way.

## Rules worth knowing

- **`name` is matched fuzzily** against booths for the current festival,
  exactly the way a crawled record is, so it needn't be byte-identical to the
  canonical name. A name that matches nothing confidently is left alone
  rather than guessed at.
- **Omit what you haven't surveyed.** A missing field stays open for a source
  to fill later; a wrong number wins forever. Nulls are never merged.
- **These values beat every crawled source.** The `manual` source has
  `priority_rank = 0`, so a correction entered here is never overwritten by a
  later refresh — and `/api/v1/booths/{id}/provenance` will show the value
  came from curation.
- **Editing a value supersedes it.** Re-applying an unchanged file is a
  no-op; changing one stages a correction that wins on recency.
- Coordinates are decimal degrees (WGS84). Five decimal places is roughly a
  metre, far more precision than distance-sorting needs.
