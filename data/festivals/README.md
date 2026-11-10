# Festivals the crawl can't reach yet

The database and `data/manual/` describe one festival: Food & Wine. Each
folder here holds another festival, researched by hand, as files:

| Folder | Edition | Built from |
|---|---|---|
| `festival-of-the-arts/` | 2027 (Jan 15 – Mar 1) | Disney's 2026 Foodie Guide, 2026 prices |
| `flower-and-garden/` | 2027 (Mar 10 – May 31) | Disney's 2026 Foodie Guide, 2026 prices |
| `festival-of-the-holidays/` | 2026 (Nov 27 – Dec 30) | Disney's 2025 Foodie Guide, 2025 prices |

Each is the last edition's menu, standing in until Disney publishes the next
one. The files in each folder:

| File | What it is |
|---|---|
| `festival.json` | Name, dates, the sources the research came from, and what is still unconfirmed |
| `booths.json` | Booths, in the same shape as `data/manual/booth_locations.json`, plus a `public_id` |
| `menu_items.json` | Dishes, in the same shape as `data/manual/menu_items.json`, plus `public_id`, `status`, `stroll` and `sources` |

**Why files rather than a database row.** `epcot_fw.festival.current_festival`
chooses the festival every crawl and every export runs against: the running
one, otherwise the next one to start. A Holidays row seeded now would take
over the daily refresh the morning after Food & Wine closes on Nov 21, and
point the Food & Wine source adapters at it. Nothing here touches the
database, `data/manual/` or the published feed (`docs/v1/`).

## Working on one

- **The Studio** (`docs/studio.html`) shows each folder as a festival in the
  switcher, and you can edit it. Its edits, pins and photos are saved in the
  browser under their own key, so they never mix with Food & Wine's.
- **`epcot-fw studio apply <file>`** reads the changeset's `festival` key and
  writes the changes back into that folder: field edits, renames, added and
  deleted rows, and pins. It publishes photos to `docs/dish-photos/` the same
  way as for Food & Wine. It does not resolve anything. Rebuild the page to
  see the result:
  ```bash
  python tools/data_ledger/build_artifact.py
  ```

## Photos

```bash
epcot-fw festival photos <folder> --confirm-tos --dry-run
```

Reads the Disney Parks Blog Foodie Guides listed under `photo_pages` in
`festival.json`, newest season first. It matches each photo's alt text to a
dish already on the menu, at the pipeline's usual auto-merge confidence, and
writes `image_url` and `image_source` into `menu_items.json`. The photos are
linked rather than copied, and credited to Disney Parks Blog with their
season and guide.

- It never replaces a photo it didn't place, such as one published from the
  Studio.
- It replaces one of its own only when a newer guide has the same dish. When
  Disney publishes the 2026 guide, add it to `photo_pages` and run it again.
- Near misses and photos that match no dish are printed, not guessed at.
  Booth group shots and Disney's occasional mislabelled photo end up there.
- It reads both of the layouts Disney has used: a run of photos above each
  "… Menu" heading, and a card per dish below it.
- `photo_pages` can also list an Internet Archive copy of a past year's
  guide (`https://web.archive.org/web/<timestamp>/<url>`). Disney rewrites one
  guide page per festival each year, so that's the only place last year's
  photos survive. Disney's original image is linked while it still loads, and
  the Archive's copy otherwise. In practice, guides before 2026 (2025 for
  Holidays) show one group photo per booth rather than one per dish, so
  they add nothing. `photo_pages_older` in each `festival.json` records what
  was checked.

Disney Food Blog and AllEars, where the Food & Wine photos came from, now
answer automated requests with a Cloudflare bot challenge. This project
doesn't try to get past that.

## Fields only these files have

- `status` (dishes) says how sure the research is that a dish is on the
  coming festival's menu: `<year>-menu` (it was on that year's menu),
  `likely-<year>` or `confirmed-<year>`. The Studio
  shows it as a label. Change it here by hand when a source confirms a dish;
  nothing in the Studio sets it.
- `stroll` (dishes) marks a dish in the festival's food stroll. The stroll's
  name is `stroll_label` in `festival.json`: Cookie Stroll for Holidays, Garden
  Graze for Flower & Garden, Wonderful Walk for Arts.
- `pinned_from` (booths) says which other festival's booth a coordinate was
  borrowed from. It is dropped as soon as a pin is placed for this booth.
- `sources` lists keys into `festival.json`'s `sources`.
- `image_source` (dishes) is `{credit, site, season, page_url, via}`, the
  shape the database festival's photo credits take.
- `origin` is `curated` on rows added in the Studio. A row without it came
  from the research.
