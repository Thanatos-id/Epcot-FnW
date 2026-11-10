"""Renders docs/studio.html - one page for correcting the database.

Replaces docs/editor.html and docs/map.html, which split one job in half.
Correcting a dish used to mean opening the editor, opening the map, and
hand-merging two paste blocks into two curated files; and neither page could
do the two things most often wanted - attach a photo you took yourself, and
add a dish the crawl never found.

The page is master/detail: a rail of booths on the left, and the whole
of one booth on the right - its own editable fields, where it sits, and every
dish on its menu. A booth is the unit a person actually works in. 209 dishes
in one flat column was a list nobody could hold in their head, and a dish is
only ever judged against the others on the same menu anyway; scoping to a
booth also means its coordinate is stated once, at the top, instead of
repeated on every row that inherits it.

What this adds over the two pages it replaces:

  * every dish shows its photo, or an explicit empty state, and a photo can
    be attached from the camera roll on the spot;
  * a booth is placed on the map from a drawer that slides over its menu,
    holds the new pin as a draft until Save, and leaves everything where it
    was on Close;
  * a dish or booth can be added by hand. Those carry `new: true`, which
    resolve/merge.py turns into `origin = 'curated'`, which is what stops
    pipeline/reconcile.py retiring them on the next crawl.

Edits leave as a single downloaded changeset file rather than a paste block.
A photo is bytes, and base64 in a textarea is not something anyone can paste
into JSON by hand; `epcot-fw studio apply` reads the file back, writes the
photos into docs/dish-photos/, and merges the rest into the same curated
files at priority_rank 0 that the editor wrote to.

Rendered by build_artifact.py from the same snapshot as the ledger, so the
two can never disagree about what is in the database. `render()` is pure -
snapshot in, HTML out - so it is testable without a browser. The page needs
the network at view time only for Leaflet and map tiles; everything else,
photos included, is inlined.
"""

from __future__ import annotations

import json
from typing import Any

from snapshot_rows import AGGREGATE_BOOTH_NAME, studio_rows

CATEGORIES = ("food", "alcoholic_beverage", "non_alcoholic_beverage")

TAGS = (
    "vegetarian",
    "vegan",
    "gluten_free",
    "plant_based",
    "contains_alcohol",
    "spicy",
    "contains_nuts",
    "contains_shellfish",
)

# A separate vocabulary from the dietary one above, kept apart here for the
# same reason the feed keeps them apart: what a dish tastes like and what a
# guest has to avoid are different questions.
FLAVOUR_TAGS = ("sweet", "savory")

# One per alcoholic drink, or none. Cider is its own value rather than filed
# under beer - see normalize/alcohol_kind.py.
ALCOHOL_KINDS = ("beer", "wine", "liquor", "cider")

# World Showcase's rough centre - every booth sits within a few hundred
# metres of it, so it is a fine default view regardless of what is placed.
DEFAULT_CENTER = [28.3689, -81.5493]
DEFAULT_ZOOM = 18

# Epcot's four festivals, in calendar order. The database and the curated
# files describe one festival at a time, so only the one this snapshot was
# built from is editable; the others render as an honest empty state rather
# than a switcher that pretends. `match` is what identifies a festival from
# the snapshot's own name.
FESTIVALS = (
    {"key": "festival-of-the-arts", "name": "Festival of the Arts", "short": "Arts",
     "season": "January – February", "match": "festival of the arts"},
    {"key": "flower-and-garden", "name": "Flower & Garden Festival", "short": "Flower & Garden",
     "season": "March – June", "match": "flower & garden"},
    {"key": "food-and-wine", "name": "Food & Wine Festival", "short": "Food & Wine",
     "season": "August – November", "match": "food & wine"},
    {"key": "festival-of-the-holidays", "name": "Festival of the Holidays", "short": "Holidays",
     "season": "November – December", "match": "festival of the holidays"},
)


def festival_catalog(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """The four festivals, with `has_data` on the one this snapshot is from.

    Matched on the festival's name because that is all the snapshot carries;
    "EPCOT International Food & Wine Festival" contains "food & wine". A
    snapshot from no recognisable festival marks none, and the page then
    refuses edits everywhere rather than guessing which one they belong to.
    """
    name = ((snapshot.get("festival") or {}).get("name") or "").lower().replace(" and ", " & ")
    return [
        {k: v for k, v in festival.items() if k != "match"} | {"has_data": festival["match"] in name}
        for festival in FESTIVALS
    ]

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light" />
<meta name="description" content="Curation studio for the Epcot festival database - correct a dish, attach a photo, place a booth on the map, or add what the crawl missed, and export the result as curated overrides." />
<title>Studio — Epcot Festivals</title>
<link rel="manifest" href="studio.webmanifest" />
<link rel="icon" href="icons/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="icons/icon.svg" />
<link rel="apple-touch-icon" sizes="180x180" href="icons/apple-touch-icon.png" />
<meta name="apple-mobile-web-app-title" content="Studio" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="theme-color" content="#ffffff" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="" />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Inter+Tight:wght@600;700&display=swap" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
<style>
/* One light palette, flat and square. Separation comes from 1px rules and
   white on grey, never from shadow or rounding; colour is reserved for one
   job - the orange that says "this has changed" or "this pin is the one you
   are placing" - so it is never decoration. */
:root {
  --bg: #f5f5f4; --surface: #ffffff; --surface-2: #fafaf9;
  --line: #e5e5e4; --line-strong: #d4d4d2;
  --ink: #111111; --ink-2: #525252; --ink-3: #8a8a88;
  --accent: #111111; --signal: #e85d04; --signal-soft: #fff4ec;
  --good: #2f7d4f; --warn: #b42318;
  --radius: 0;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px;
  /* One size for everything you can click or type into. Buttons, inputs,
     selects and toggles all share these, so a row of mixed controls lines
     up on both edges and nothing reads as more or less important by size. */
  --control: 32px;
  --control-px: 12px;
  --control-radius: 4px;
  --control-font: 13px;
  --control-min: 64px;
  --bar: 56px;
  --rail: 320px;
  --font: "Inter", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
  --font-head: "Inter Tight", "Inter", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
@media (pointer: coarse) { :root { --control: 40px; } }

* { box-sizing: border-box; border-radius: var(--radius); }
html, body { margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  background: var(--bg); color: var(--ink);
  font-family: var(--font); font-size: 14px; line-height: 1.5;
  -webkit-font-smoothing: antialiased; font-feature-settings: "cv11", "ss01";
}
h1, h2, h3 { font-family: var(--font-head); font-weight: 600; letter-spacing: -0.015em; margin: 0; }
a { color: var(--ink); text-underline-offset: 2px; }
.mono, .num { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.label {
  font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-3);
}
.hidden { display: none !important; }

/* ---------- controls ---------- */
button, input, select, textarea { font: inherit; color: var(--ink); }
button, .tag-toggle, .tag-edit {
  height: var(--control); min-width: var(--control-min); padding: 0 var(--control-px);
  border: 1px solid var(--line-strong); border-radius: var(--control-radius);
  background: var(--surface); cursor: pointer; font-size: var(--control-font); font-weight: 500;
  display: inline-flex; align-items: center; justify-content: center; gap: var(--s2);
  white-space: nowrap; line-height: 1;
}
/* Icon-only buttons are square at the same height rather than stretched to
   the minimum width. */
button.icon { min-width: 0; width: var(--control); padding: 0; }
button:hover { border-color: var(--ink); }
button:disabled { opacity: 0.4; cursor: default; border-color: var(--line-strong); }
button.primary { background: var(--ink); border-color: var(--ink); color: #fff; }
button.primary:hover { background: #000; }
button.quiet { border-color: transparent; background: transparent; color: var(--ink-2); }
button.quiet:hover { color: var(--ink); border-color: transparent; text-decoration: underline; }
button.danger { color: var(--warn); }
button.chip { color: var(--ink-2); }
button.chip.active { background: var(--ink); border-color: var(--ink); color: #fff; }
.linkish, .tag-done { color: var(--ink-2); }
.linkish:hover, .tag-done:hover { color: var(--ink); }
input[type="search"], input[type="text"], input[type="number"], input[type="date"], select, textarea {
  height: var(--control); border: 1px solid var(--line-strong); border-radius: var(--control-radius);
  background: var(--surface); padding: 0 var(--control-px); font-size: var(--control-font); min-width: 0;
}
textarea { height: auto; min-height: calc(var(--control) * 2); padding: var(--s2) var(--control-px); resize: vertical; line-height: 1.45; }
select { max-width: 100%; }
input:focus, select:focus, textarea:focus, button:focus-visible {
  outline: 2px solid var(--ink); outline-offset: -1px;
}
input[type="file"] { display: none; }

/* ---------- shell ----------
   One viewport, two scrollers, nothing measured. The bar is a grid row, so
   nothing in the panes has to know how tall it is; the rail and the detail
   each scroll on their own, so the list you choose from stays beside the
   list you are working through. */
body.shell {
  display: grid; grid-template-rows: var(--bar) auto minmax(0, 1fr);
  height: 100vh; height: 100dvh; overflow: hidden;
}
.bar {
  display: flex; align-items: center; gap: var(--s4); padding: 0 var(--s4);
  background: var(--surface); border-bottom: 1px solid var(--line); min-width: 0;
}
.wordmark { font-family: var(--font-head); font-weight: 700; font-size: 18px; letter-spacing: -0.02em; }
.festivals {
  display: flex; border: 1px solid var(--line-strong); border-radius: var(--control-radius);
  min-width: 0; overflow-x: auto; overflow-y: hidden;
}
/* A segmented group is one control: the outer box carries the height and the
   radius, and the segments are square inside it. */
.festivals button, .segmented button {
  border: none; border-right: 1px solid var(--line-strong); border-radius: 0;
  height: calc(var(--control) - 2px); min-width: 0; color: var(--ink-2);
}
.festivals button:last-child, .segmented button:last-child { border-right: none; }
.festivals button[aria-pressed="true"] { background: var(--ink); color: #fff; }
.festivals button .dot { width: 5px; height: 5px; background: currentColor; opacity: 0.5; }
.bar .spacer { flex: 1 1 auto; }
.bar .count { font-size: 13px; color: var(--ink-2); white-space: nowrap; }
.bar .count b { color: var(--signal); font-weight: 600; }
.menu { position: relative; }
.menu-list {
  position: absolute; right: 0; top: calc(100% + 4px); z-index: 1200; min-width: 220px;
  background: var(--surface); border: 1px solid var(--ink); display: flex; flex-direction: column;
  border-radius: var(--control-radius); overflow: hidden;
}
.menu-list button, .menu-list a {
  border: none; border-bottom: 1px solid var(--line); border-radius: 0; min-width: 0;
  height: 36px; justify-content: flex-start;
  padding: 0 var(--s3); font-size: 13px; text-decoration: none; display: flex; align-items: center;
  background: var(--surface); color: var(--ink);
}
.menu-list > :last-child { border-bottom: none; }
.menu-list button:hover, .menu-list a:hover { background: var(--surface-2); }

.status { display: flex; flex-direction: column; }
.status-line {
  display: flex; align-items: center; gap: var(--s3); padding: 6px var(--s4);
  font-size: 12.5px; border-bottom: 1px solid var(--line); background: var(--surface);
}
.status-line.warn { color: var(--warn); }
.status-line .spacer { flex: 1 1 auto; }

.workspace { display: grid; grid-template-columns: var(--rail) minmax(0, 1fr); min-height: 0; }
.rail {
  display: flex; flex-direction: column; min-height: 0; background: var(--surface);
  border-right: 1px solid var(--line);
}
.rail-head { padding: var(--s4) var(--s4) var(--s3); display: grid; gap: var(--s2); border-bottom: 1px solid var(--line); }
.rail-title { display: flex; align-items: baseline; justify-content: space-between; }
.rail-title h2 { font-size: 15px; }
.count { font-size: 12px; color: var(--ink-3); white-space: nowrap; font-variant-numeric: tabular-nums; }
.rail-head input[type="search"] { width: 100%; }
.chips { display: flex; gap: var(--s1); flex-wrap: wrap; }
.booth-list, .detail {
  overflow-y: auto; overscroll-behavior: contain; min-height: 0; scrollbar-gutter: stable;
}
.booth-list { flex: 1 1 auto; }
.rail-foot { border-top: 1px solid var(--line); padding: var(--s2) var(--s4); }
.rail-foot button { width: 100%; justify-content: center; }

.booth-item {
  width: 100%; height: auto; display: grid; grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px var(--s2); text-align: left; padding: 10px var(--s4); border: none;
  border-bottom: 1px solid var(--line); border-left: 2px solid transparent; background: var(--surface);
  font-weight: 400; white-space: normal; min-width: 0; border-radius: 0; line-height: 1.5;
}
.booth-item:hover { background: var(--surface-2); }
.booth-item.selected { background: var(--bg); border-left-color: var(--ink); }
.booth-item.deleted { opacity: 0.45; }
.booth-item-name { font-weight: 500; font-size: 13.5px; overflow-wrap: anywhere; }
.booth-item-count { font-size: 12px; color: var(--ink-3); font-variant-numeric: tabular-nums; display: flex; align-items: center; gap: 6px; }
.booth-item-meta { grid-column: 1 / -1; font-size: 11.5px; color: var(--ink-3); display: flex; gap: var(--s2); flex-wrap: wrap; }
.changed-dot { width: 6px; height: 6px; background: var(--signal); display: inline-block; }

/* ---------- detail ---------- */
.detail { background: var(--bg); }
.detail-empty, .festival-empty {
  height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: var(--s6); color: var(--ink-2); gap: var(--s2);
}
.detail-empty h2, .festival-empty h2 { font-size: 22px; color: var(--ink); }
.detail-empty p, .festival-empty p { margin: 0; max-width: 44ch; }
.festival-empty .stats { display: flex; gap: 0; margin-top: var(--s4); border: 1px solid var(--line); background: var(--surface); }
.festival-empty .stats div { padding: var(--s3) var(--s5); border-right: 1px solid var(--line); }
.festival-empty .stats div:last-child { border-right: none; }
.festival-empty .stats b { display: block; font-family: var(--font-head); font-size: 22px; color: var(--ink); }

.detail-head { background: var(--surface); border-bottom: 1px solid var(--line); }
.back-to-booths { display: none; margin: var(--s3) var(--s4) 0; }
.booth-panel { padding: var(--s4) var(--s5) var(--s3); display: grid; gap: var(--s3); }
.booth-title { display: flex; align-items: baseline; gap: var(--s3); flex-wrap: wrap; }
.booth-title h2 { font-size: 24px; letter-spacing: -0.02em; overflow-wrap: anywhere; }
.booth-fields {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: var(--s2) var(--s4);
}
.booth-fields .field { display: grid; gap: 2px; }
.booth-fields .field.wide { grid-column: 1 / -1; }
.inline { display: flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }
.location {
  display: flex; align-items: center; gap: var(--s3); flex-wrap: wrap;
  padding-top: var(--s3); border-top: 1px solid var(--line); font-size: 12.5px; color: var(--ink-2);
}
.location .mono { color: var(--ink); font-size: 12px; }
.booth-actions { display: flex; gap: var(--s3); }

/* The one thing pinned while a menu scrolls: which booth this is, and the
   controls for narrowing its dishes. The booth's own fields scroll away -
   pinned, they took a third of a laptop screen from the dishes. */
.toolbar {
  position: sticky; top: 0; z-index: 5;
  display: flex; gap: var(--s2); flex-wrap: wrap; align-items: center;
  padding: var(--s2) var(--s5); border-bottom: 1px solid var(--line); background: var(--surface-2);
}
.toolbar-title { font-family: var(--font-head); font-weight: 600; font-size: 14px; letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px; }
.toolbar input[type="search"] { flex: 1 1 200px; }
.toolbar .spacer { flex: 1 1 auto; }

/* Status words rather than coloured pills: one small uppercase label, and
   colour only where it carries meaning. */
.pill {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--ink-3); white-space: nowrap; border: 1px solid var(--line-strong); padding: 1px 6px;
}
.pill.surveyed { color: var(--good); border-color: currentColor; }
.pill.mapped { color: var(--ink); border-color: currentColor; }
.pill.unplaced, .pill.opens-later { color: var(--signal); border-color: currentColor; }
.pill.deleted { color: var(--warn); border-color: currentColor; }
.pill.curated { color: var(--ink); }

/* ---------- dish rows: a ruled list, not a stack of cards ---------- */
.rows { display: flex; flex-direction: column; padding: 0 0 var(--s6); }
.row {
  display: grid; grid-template-columns: 128px minmax(0, 1fr); gap: var(--s4);
  padding: var(--s4) var(--s5); background: var(--surface); border-bottom: 1px solid var(--line);
  border-left: 3px solid transparent;
}
.row.edited { border-left-color: var(--signal); }
.row.deleted { opacity: 0.5; }
.thumb {
  width: 128px; aspect-ratio: 1; overflow: hidden; background: var(--bg);
  border: 1px solid var(--line); display: flex; align-items: center; justify-content: center; position: relative;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-empty-label { color: var(--ink-3); font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase; }
.thumb .badge {
  position: absolute; left: 0; bottom: 0; right: 0; font-size: 10px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; padding: 2px 6px; background: var(--signal); color: #fff;
}
.photo-actions { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s1); margin-top: var(--s2); }
.photo-actions button { min-width: 0; padding: 0; }
.photo-actions button:first-of-type { grid-column: 1 / -1; }
.photo-credit { margin-top: 6px; font-size: 10.5px; line-height: 1.35; color: var(--ink-3); overflow-wrap: anywhere; }
.photo-credit .season { font-variant-numeric: tabular-nums; }

.fields { display: grid; gap: var(--s2); min-width: 0; align-content: start; }
.field-row { display: flex; gap: var(--s2); flex-wrap: wrap; align-items: center; }
.row-head { display: flex; align-items: center; gap: var(--s2); }
/* Element-qualified so it outranks the generic input[type] rule above. A
   light rule on every field says "editable" without shouting it. */
input.cell-input, textarea.cell-input, select.cell-input {
  width: 100%; border: 1px solid var(--line); border-radius: var(--control-radius);
  background: var(--surface); padding: 0 var(--control-px);
  height: var(--control); font-size: var(--control-font);
}
input.cell-input:hover, textarea.cell-input:hover, select.cell-input:hover { border-color: var(--line-strong); }
textarea.cell-input { height: auto; min-height: calc(var(--control) * 2); padding: var(--s2) var(--control-px); color: var(--ink-2); }
input.cell-input[placeholder="Dish name"] { font-weight: 600; }
input.cell-input.changed, textarea.cell-input.changed, select.cell-input.changed { border-color: var(--signal); background: var(--signal-soft); }
input.price { flex: 0 0 112px; width: 112px; font-family: var(--mono); }
select.cell-input { width: auto; }
/* Every dropdown draws its own chevron. The native arrow ignores padding and
   sits hard against the right edge; this one sits the same 12px in that the
   text does on the left, with room left for the text so it never runs under
   it. Longhands only, after every rule that sets a select's background, so
   the edited-field tint keeps its colour and the chevron both. */
select, select.cell-input, select.cell-input.changed {
  -webkit-appearance: none; appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23525252' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right var(--control-px) center;
  background-size: 10px 6px;
  padding-right: calc(var(--control-px) + 10px + var(--s2));
}

.attrs { display: flex; flex-wrap: wrap; gap: var(--s2) var(--s4); align-items: center; }
.tag-cell { cursor: pointer; }
.tag-summary, .tag-picker, .new-cell, .geo { display: flex; flex-wrap: wrap; gap: var(--s1); align-items: center; font-size: var(--control-font); color: var(--ink-3); }
.tag-none { color: var(--ink-3); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; margin-right: 2px; }
.tag-edit { color: var(--ink-2); }
.tag-empty { color: var(--ink-3); padding: 0 var(--s1); }
.tag-toggle { color: var(--ink-2); }
.tag-toggle.on { background: var(--ink); border-color: var(--ink); color: #fff; }
.tag-toggle.changed { box-shadow: inset 0 -2px 0 var(--signal); }
.row-actions { display: flex; gap: var(--s2); justify-content: flex-end; }
.empty-state { padding: var(--s6) var(--s4); text-align: center; color: var(--ink-3); font-size: 13px; }

/* ---------- map drawer ----------
   The map is a tool you pick up, not a region of the page. It slides over
   from the right with the booth it is about, holds a draft pin until Save,
   and puts everything back where it was on Close. */
.scrim {
  position: fixed; inset: 0; background: rgba(17,17,17,0.24); z-index: 1300;
  opacity: 0; pointer-events: none; transition: opacity 220ms ease-out;
}
.scrim.open { opacity: 1; pointer-events: auto; }
.drawer {
  position: fixed; top: 0; right: 0; bottom: 0; width: min(720px, 100vw); z-index: 1400;
  background: var(--surface); border-left: 1px solid var(--ink);
  display: grid; grid-template-rows: auto minmax(0, 1fr) auto;
  transform: translateX(100%); transition: transform 220ms ease-out;
  box-shadow: -1px 0 0 rgba(0,0,0,0.04), -12px 0 32px rgba(0,0,0,0.06);
}
.drawer.open { transform: none; }
.drawer-head { padding: var(--s4) var(--s5); border-bottom: 1px solid var(--line); display: grid; gap: var(--s2); }
.drawer-title { display: flex; align-items: center; gap: var(--s3); }
.drawer-title h2 { font-size: 20px; flex: 1 1 auto; overflow-wrap: anywhere; }
.drawer-meta { display: flex; align-items: center; gap: var(--s3); flex-wrap: wrap; font-size: 12.5px; color: var(--ink-2); }
.drawer-meta .spacer { flex: 1 1 auto; }
.segmented {
  display: inline-flex; border: 1px solid var(--line-strong); border-radius: var(--control-radius); overflow: hidden;
}
.segmented button[aria-pressed="true"] { background: var(--ink); color: #fff; }
.drawer-body { position: relative; min-height: 0; background: var(--bg); }
#map { position: absolute; inset: 0; }
#map.placing, #map.placing .leaflet-container { cursor: crosshair; }
.drawer-hint {
  position: absolute; left: var(--s4); bottom: var(--s5); z-index: 500; background: var(--surface);
  border: 1px solid var(--ink); border-radius: var(--control-radius);
  padding: var(--s2) var(--control-px); font-size: var(--control-font); max-width: calc(100% - 32px);
}
.drawer-offline { padding: var(--s5); color: var(--warn); }
.drawer-foot {
  display: flex; align-items: center; gap: var(--s2); padding: var(--s3) var(--s5);
  border-top: 1px solid var(--line); flex-wrap: wrap;
}
.drawer-foot .spacer { flex: 1 1 auto; }
.tallies { display: flex; flex-wrap: wrap; gap: 0; border: 1px solid var(--line); }
.tally { padding: 4px var(--s3); font-size: 12px; color: var(--ink-2); border-right: 1px solid var(--line); }
.tally:last-child { border-right: none; }
.tally b { color: var(--ink); font-family: var(--mono); font-weight: 500; }

.leaflet-container { font-family: var(--font); background: var(--bg); }
.leaflet-bar { border: 1px solid var(--ink) !important; box-shadow: none !important; border-radius: var(--control-radius) !important; overflow: hidden; }
.leaflet-bar a {
  color: var(--ink) !important; border-bottom-color: var(--line) !important; border-radius: 0 !important;
  width: var(--control) !important; height: var(--control) !important; line-height: var(--control) !important;
}
.leaflet-control-attribution { background: rgba(255,255,255,0.8) !important; font-size: 10px; }
.booth-pin span { display: block; width: 12px; height: 12px; border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(0,0,0,0.5); }
.booth-pin.dim span { opacity: 0.55; }
.booth-pin.active span { width: 18px; height: 18px; background: var(--signal) !important; box-shadow: 0 0 0 1px #000; }
.booth-pin.draft span { width: 18px; height: 18px; background: var(--signal) !important; border-color: #000; }
.leaflet-tooltip.booth-tooltip {
  background: var(--surface); color: var(--ink); border: 1px solid var(--ink); border-radius: 0;
  font-size: 11px; font-weight: 500; padding: 1px 6px; box-shadow: none;
}
.leaflet-tooltip.booth-tooltip::before { display: none; }

/* ---------- dialogs ---------- */
dialog {
  border: 1px solid var(--ink); background: var(--surface); color: var(--ink);
  max-width: min(560px, 92vw); width: 100%; padding: 0;
}
dialog::backdrop { background: rgba(17,17,17,0.32); }
.dialog-body { padding: var(--s5); }
.dialog-body h2 { font-size: 20px; margin-bottom: var(--s2); }
.dialog-body p { margin: 0 0 var(--s3); font-size: 13px; color: var(--ink-2); }
.dialog-body code { font-family: var(--mono); font-size: 12px; }
.dialog-body label { display: block; margin: var(--s3) 0 var(--s1); }
.dialog-body input[type="text"], .dialog-body input[type="number"], .dialog-body select, .dialog-body textarea { width: 100%; }
.dialog-actions { display: flex; gap: var(--s2); justify-content: flex-end; flex-wrap: wrap; margin-top: var(--s5); }
.summary { list-style: none; padding: 0; margin: 0 0 var(--s4); font-size: 13px; border-top: 1px solid var(--line); }
.summary li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--line); }
.summary b { font-family: var(--mono); font-weight: 500; }
pre.cmd { background: var(--bg); border: 1px solid var(--line); padding: var(--s3); font-family: var(--mono); font-size: 12px; overflow-x: auto; margin: 0; }
.help ol { margin: 0 0 var(--s3); padding-left: 18px; color: var(--ink-2); font-size: 13px; }
.help li { margin-bottom: var(--s2); }
.help .meta { font-size: 12px; color: var(--ink-3); margin-top: var(--s3); }

/* ---------- narrow screens: the panes take turns ---------- */
@media (max-width: 900px) {
  :root { --rail: 100%; }
  .bar { gap: var(--s2); padding: 0 var(--s3); }
  .bar .count { display: none; }
  .workspace { grid-template-columns: minmax(0, 1fr); }
  .workspace.picked .rail { display: none; }
  .workspace:not(.picked) .detail { display: none; }
  .back-to-booths { display: inline-flex; }
  .booth-panel, .toolbar, .row { padding-left: var(--s4); padding-right: var(--s4); }
  .booth-fields { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 640px) {
  .wordmark, .bar > .spacer { display: none; }
  /* The switcher takes the room the wordmark gave up and scrolls sideways
     rather than shrinking to nothing. */
  .festivals { flex: 1 1 auto; }
  .festivals button { flex: none; }
  .row { grid-template-columns: 104px minmax(0, 1fr); gap: var(--s3); }
  .thumb { width: 104px; }
  #map-btn { display: none; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body class="shell">
<header class="bar">
  <span class="wordmark">Studio</span>
  <nav class="festivals" id="festivals" aria-label="Festival"></nav>
  <span class="spacer"></span>
  <span class="count" id="edit-count"></span>
  <button type="button" id="map-btn">Map</button>
  <button type="button" class="primary" id="export" disabled>Export</button>
  <div class="menu">
    <button type="button" class="icon" id="menu-btn" aria-haspopup="true" aria-expanded="false" aria-label="More">⋯</button>
    <div class="menu-list hidden" id="menu-list" role="menu">
      <button type="button" role="menuitem" class="hidden" id="install-btn">Install as app</button>
      <button type="button" role="menuitem" id="help-btn">How this works</button>
      <a role="menuitem" href="index.html">Open the ledger</a>
      <a role="menuitem" href="survey.html">In-park GPS survey</a>
      <button type="button" role="menuitem" class="danger" id="discard">Discard all changes</button>
    </div>
  </div>
</header>

<div class="status">
  <div class="status-line hidden" id="update-line">
    <span>A newer version of the Studio is ready. Your edits are saved and carry over.</span><span class="spacer"></span>
    <button type="button" class="primary" id="update-reload">Reload</button>
  </div>
  <div class="status-line warn hidden" id="storage-note"></div>
  <div class="status-line hidden" id="settled-line">
    <span id="settled-note"></span><span class="spacer"></span>
    <button type="button" class="quiet" id="settled-dismiss">Dismiss</button>
  </div>
</div>

<main class="workspace" id="layout">
  <aside class="rail">
    <div class="rail-head">
      <div class="rail-title"><h2>Booths</h2><span class="count" id="booth-count"></span></div>
      <input type="search" id="booth-search" placeholder="Filter booths…" autocomplete="off" />
      <div class="chips">
        <button type="button" class="chip" id="chip-unplaced">Not placed</button>
        <button type="button" class="chip" id="chip-edited">Edited</button>
        <button type="button" class="chip" id="chip-added">Added by hand</button>
      </div>
    </div>
    <div class="booth-list" id="booth-list"></div>
    <div class="rail-foot"><button type="button" id="add-booth-btn">Add booth</button></div>
  </aside>

  <section class="detail" id="detail">
    <div class="detail-empty" id="detail-empty">
      <h2>Select a booth</h2>
      <p>Its menu opens here: every dish with its photo, price, description and tags, and where the booth sits on the map.</p>
    </div>

    <div id="detail-body" class="hidden">
      <div class="detail-head">
        <button type="button" class="chip back-to-booths" id="back-to-booths">← All booths</button>
        <div id="booth-detail"></div>
      </div>
      <div class="toolbar">
          <span class="toolbar-title" id="toolbar-title"></span>
          <input type="search" id="dish-search" placeholder="Search this menu…" autocomplete="off" />
          <select id="filter-cat">
            <option value="">All categories</option>
            <option value="food">Food</option>
            <option value="alcoholic_beverage">Alcoholic</option>
            <option value="non_alcoholic_beverage">Non-alcoholic</option>
          </select>
          <button type="button" class="chip" id="chip-nophoto">Needs a photo</button>
          <button type="button" class="chip" id="chip-new">New this year</button>
          <span class="spacer"></span>
          <span class="count" id="dish-count"></span>
          <button type="button" id="add-dish-btn">Add dish</button>
      </div>
      <div class="rows" id="dish-list"></div>
    </div>
  </section>
</main>

<main class="festival-empty hidden" id="festival-empty"></main>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="map-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" inert>
  <div class="drawer-head">
    <div class="drawer-title">
      <h2 id="drawer-title">Map</h2>
      <button type="button" class="quiet" id="drawer-close" aria-label="Close map">Close</button>
    </div>
    <div class="drawer-meta">
      <span id="drawer-position"></span>
      <span class="spacer"></span>
      <div class="segmented" id="layer-toggle">
        <button type="button" data-layer="sat" aria-pressed="true">Satellite</button>
        <button type="button" data-layer="streets" aria-pressed="false">Streets</button>
      </div>
    </div>
    <div class="tallies" id="tallies"></div>
  </div>
  <div class="drawer-body">
    <div class="drawer-hint hidden" id="drawer-hint"></div>
    <div class="drawer-offline hidden" id="offline-note">
      Map tiles need an internet connection. Everything else on this page works offline.
    </div>
    <div id="map"></div>
  </div>
  <div class="drawer-foot">
    <button type="button" class="quiet danger hidden" id="drawer-remove">Remove staged pin</button>
    <span class="spacer"></span>
    <button type="button" id="drawer-cancel">Cancel</button>
    <button type="button" class="primary" id="drawer-save" disabled>Save location</button>
  </div>
</aside>

<dialog id="help-dialog">
  <div class="dialog-body help">
    <h2>How this works</h2>
    <ol>
      <li><b>Nothing here writes to the database.</b> Edits and photos stay in this browser until you export them, so you can work across several sittings.</li>
      <li>Pick a booth, then correct its dishes in place. A changed field is marked in orange; the count in the top bar is what an export will carry.</li>
      <li>Use <b>Place on map</b> on a booth to open the map, click its spot, and <b>Save location</b>. Pins stage as <code>location_precision: "mapped"</code>.</li>
      <li><b>Export</b> downloads one changeset. <code>epcot-fw studio apply</code> publishes its photos and merges the rest into the curated files that override the crawl.</li>
      <li>A dish's <b>name</b> is how a correction finds it again, so a rename travels as a rename, with both names.</li>
    </ol>
    <p class="meta">Snapshot built __GENERATED_AT__. Prices are US dollars; a blank price means no source has published one.</p>
    <div class="dialog-actions"><button type="button" class="primary" id="help-close">Done</button></div>
  </div>
</dialog>

<dialog id="add-dialog">
  <form class="dialog-body" id="add-form" method="dialog">
    <h2>Add by hand</h2>
    <p>
      For something the crawl never found. It comes back as <code>origin: "curated"</code>, which
      stops the next crawl retiring it, and the <b>Added by hand</b> filter finds it later.
    </p>
    <div id="add-item-fields">
      <label class="label" for="add-booth">Booth</label>
      <select id="add-booth"></select>
      <label class="label" for="add-name">Dish name</label>
      <input type="text" id="add-name" autocomplete="off" />
      <label class="label" for="add-desc">Description</label>
      <textarea id="add-desc" rows="2"></textarea>
      <label class="label" for="add-price">Price (USD)</label>
      <input type="number" id="add-price" step="0.01" min="0" />
      <label class="label" for="add-cat">Category</label>
      <select id="add-cat"></select>
    </div>
    <div id="add-booth-fields" class="hidden">
      <label class="label" for="add-booth-name">Booth name</label>
      <input type="text" id="add-booth-name" autocomplete="off" />
      <label class="label" for="add-booth-loc">Location description</label>
      <input type="text" id="add-booth-loc" autocomplete="off" />
      <p style="margin-top:12px">Place it on the map once it's added.</p>
    </div>
    <p class="hidden" id="add-error" style="color:var(--warn)"></p>
    <div class="dialog-actions">
      <button type="button" id="add-cancel">Cancel</button>
      <button type="button" class="primary" id="add-confirm">Add</button>
    </div>
  </form>
</dialog>

<dialog id="export-dialog">
  <div class="dialog-body">
    <h2>Export</h2>
    <p>Download the changeset, then apply it from the repo root:</p>
    <ul class="summary" id="export-summary"></ul>
    <pre class="cmd" id="export-cmd">epcot-fw studio apply ~/Downloads/epcot-changeset.json</pre>
    <p style="margin-top:12px">
      That writes any attached photos into <code>docs/dish-photos/</code>, merges the rest into
      <code>data/manual/menu_items.json</code> and <code>data/manual/booth_locations.json</code>,
      and re-resolves. Commit and push those to publish.
    </p>
    <div class="dialog-actions">
      <button type="button" id="export-close">Close</button>
      <button type="button" class="primary" id="export-download">Download changeset</button>
    </div>
  </div>
</dialog>

<dialog id="ask-dialog">
  <form class="dialog-body" method="dialog" id="ask-form">
    <h2 id="ask-title"></h2>
    <p id="ask-message"></p>
    <input type="text" id="ask-input" autocomplete="off" spellcheck="false" style="width:100%">
    <div class="dialog-actions">
      <button type="button" id="ask-cancel">Cancel</button>
      <button type="submit" class="primary" id="ask-ok">OK</button>
    </div>
  </form>
</dialog>

<script id="studio-data" type="application/json">__DATA_JSON__</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById('studio-data').textContent);
  var CATEGORIES = __CATEGORIES__;
  var TAGS = __TAGS__;
  var FLAVOUR_TAGS = __FLAVOUR_TAGS__;
  var ALCOHOL_KINDS = __ALCOHOL_KINDS__;
  var FESTIVALS = __FESTIVALS__;
  var CENTER = __CENTER_JSON__;
  var ZOOM = __ZOOM__;
  // A heading covering dishes sold in several places at once, not somewhere
  // a person can stand. Never offered for placement - see snapshot_rows.py.
  var AGGREGATE_BOOTH_NAME = __AGGREGATE_BOOTH_NAME__;

  var STORE_KEY = 'epcot-studio-v1';
  var DB_NAME = 'epcot-studio';
  var DB_STORE = 'photos';
  // Downscaled before anything else touches it. A modern phone camera
  // produces 3-4MB per shot and a lap of the festival is dozens of dishes;
  // at that size the changeset stops being a file anyone can move around,
  // and nothing downstream shows a dish photo bigger than a card anyway.
  var MAX_EDGE = 1280;
  var JPEG_QUALITY = 0.82;

  var state = {
    selected: null,                    // booth name whose menu is open on the right
    edits: { items: {}, booths: {} },
    placements: {},                    // boothName -> {latitude, longitude, placed_at}
    added: { items: [], booths: [] },  // rows typed in here, not in any snapshot
    deleted: { items: {}, booths: {} },// curated rows already in the DB, staged inactive
    // Two search boxes, each sitting in the pane it filters. One box over
    // both lists reads as a single search and behaves as two, which is worse
    // than either.
    boothQ: '', dishQ: '', category: '',
    noPhotoOnly: false, unplacedOnly: false, editedOnly: false, addedOnly: false,
    newOnly: false,
    expandedTags: null,
    festival: null,                    // key into FESTIVALS; null = the one with data
    drawer: null                       // {booth, draft} while the map drawer is open
  };

  // Photo bytes never go in localStorage: a handful of shots is past its ~5MB
  // quota, and the failure mode is a silent QuotaExceededError halfway
  // through a lap. IndexedDB holds them; this is the in-memory mirror
  // everything renders from.
  var photos = {};

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // Today as YYYY-MM-DD, compared as strings against opens_at rather than
  // through Date parsing - Date('2026-10-02') reads as UTC midnight, which
  // is the previous day in some local time zones. String comparison on two
  // values already in this exact shape has no time zone to get wrong.
  function todayISO() {
    var d = new Date();
    var pad = function (n) { return n < 10 ? '0' + n : String(n); };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  // null once the date has arrived or passed, or was never set - the "open
  // now" case every booth was in before this field existed. Otherwise the
  // raw YYYY-MM-DD, for a caller to format.
  function opensAtIfFuture(row) {
    var raw = valueOf(row, 'opens_at');
    return raw && raw > todayISO() ? raw : null;
  }

  function formatOpeningDate(iso) {
    // Parsed at local midnight, not UTC, for the same reason todayISO()
    // compares as strings: new Date('2026-10-02') can print as Oct 1 west
    // of Greenwich.
    var d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function warn(message) {
    var el = document.getElementById('storage-note');
    el.textContent = message;
    el.classList.remove('hidden');
  }

  // ---------- persistence ----------
  function load() {
    try {
      var raw = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
      state.edits = { items: (raw.edits || {}).items || {}, booths: (raw.edits || {}).booths || {} };
      state.placements = raw.placements || {};
      state.added = { items: (raw.added || {}).items || [], booths: (raw.added || {}).booths || [] };
      state.deleted = { items: (raw.deleted || {}).items || {}, booths: (raw.deleted || {}).booths || {} };
      state.selected = raw.selected || null;
      state.festival = raw.festival || null;
    } catch (e) {
      // Private mode, storage off - start clean rather than refusing to run.
    }
  }
  function save() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        edits: state.edits, placements: state.placements,
        added: state.added, deleted: state.deleted,
        // Kept so a reload drops you back on the menu you were working
        // through rather than at the empty state.
        selected: state.selected,
        // Older builds ignore it, so the store stays readable both ways.
        festival: state.festival
      }));
    } catch (e) {
      warn('This browser refused to save your edits — they will be lost on reload. Export before you close the tab.');
    }
  }

  // ---------- settling what has already shipped ----------
  // Edits live in this browser until they are exported, and nothing here
  // ever learned when one had been applied: `studio apply` and a rebuild put
  // the value into DATA, but the stored edit stayed, so every edit ever made
  // went on counting as a change - 72 of them, all already live - and every
  // export re-sent the lot. On each load, anything the rebuilt page already
  // says is dropped, and only what is genuinely still pending survives.
  //
  // Only ever removes an edit whose value DATA now carries, so the worst a
  // wrong answer here can do is leave something counted that need not be.
  // An edit that disagrees with DATA - including one DATA has since moved
  // past, like a kind somebody corrected again later - is kept and shown.
  function sameValue(a, b) {
    if (Array.isArray(a) || Array.isArray(b)) {
      return JSON.stringify((a || []).slice().sort()) === JSON.stringify((b || []).slice().sort());
    }
    var blankA = a === null || a === undefined || a === '';
    var blankB = b === null || b === undefined || b === '';
    if (blankA || blankB) return blankA && blankB;
    // A price is "13.00" in DATA and 13 once typed into a number field.
    if (typeof a === 'number' || typeof b === 'number') {
      var na = Number(a), nb = Number(b);
      if (isFinite(na) && isFinite(nb)) return na === nb;
    }
    return String(a) === String(b);
  }

  // The fields of `edit` DATA's row already has, removed in place. A rename
  // is settled when a row by the new name exists; the old key then points at
  // nothing, so the rest of the edit is checked against the renamed row.
  function settleEdit(edit, row) {
    var n = 0;
    Object.keys(edit).forEach(function (key) {
      if (key === 'name') return;
      if (Object.prototype.hasOwnProperty.call(row, key) && sameValue(edit[key], row[key])) {
        delete edit[key];
        n++;
      }
    });
    if (Object.prototype.hasOwnProperty.call(edit, 'name') && sameValue(edit.name, row.name)) {
      delete edit.name;
      n++;
    }
    return n;
  }

  function settle() {
    // Counted by row, to read the same as the "rows changed" count it is
    // emptying - a row with a tag and a photo both settled is one row.
    var touched = {};
    var itemsByKey = {}, boothsByName = {}, byPhotoKey = {};
    DATA.items.forEach(function (row) {
      itemsByKey[rowKey(row)] = row;
      if (row.public_id) byPhotoKey[row.public_id] = row;
    });
    DATA.booths.forEach(function (row) { boothsByName[row.name] = row; });

    // Dish and booth edits.
    [['items', function (k, e) {
      if (itemsByKey[k]) return itemsByKey[k];
      if (!e.name || k.indexOf('new:') === 0) return null;
      try { return itemsByKey[JSON.stringify([JSON.parse(k)[0], e.name])] || null; } catch (err) { return null; }
    }], ['booths', function (k) { return boothsByName[k] || null; }]].forEach(function (pair) {
      var bucket = state.edits[pair[0]];
      Object.keys(bucket).forEach(function (k) {
        var row = pair[1](k, bucket[k]);
        if (!row) return;
        if (settleEdit(bucket[k], row)) touched[pair[0] + k] = true;
        if (!Object.keys(bucket[k]).length) delete bucket[k];
      });
    });

    // Rows typed in here that the database now has. Whatever was typed and
    // still differs carries over onto the real row as an ordinary edit, and
    // so does an attached photo, so nothing pending is lost in the handover.
    state.added.items = state.added.items.filter(function (row) {
      var e = state.edits.items['new:' + row._id] || {};
      var live = itemsByKey[JSON.stringify([row.booth, e.name || row.name])];
      if (!live) return true;
      var pending = {};
      ['description', 'price', 'category', 'tags', 'flavor_tags', 'alcohol_kind', 'is_new_this_year', 'image_url']
        .forEach(function (key) {
          var typed = Object.prototype.hasOwnProperty.call(e, key) ? e[key] : row[key];
          // A blank Add-form field means nobody said, not "make it empty" -
          // the export treats it the same way.
          if (typed === null || typed === undefined || typed === '' || typed === false ||
              (Array.isArray(typed) && !typed.length)) return;
          if (!sameValue(typed, live[key])) pending[key] = typed;
        });
      if (Object.keys(pending).length) {
        var k = rowKey(live);
        state.edits.items[k] = Object.assign(pending, state.edits.items[k] || {});
      }
      var photo = photos[photoKey(row)];
      if (photo && !live.image_url && !photos[photoKey(live)]) {
        putPhoto(Object.assign({}, photo, { key: photoKey(live) }));
      }
      if (photo) dropPhoto(photo.key);
      delete state.edits.items['new:' + row._id];
      touched['items' + rowKey(live)] = true;
      return false;
    });
    state.added.booths = state.added.booths.filter(function (row) {
      var e = state.edits.booths['new:' + row._id] || {};
      if (!boothsByName[e.name || row.name]) return true;
      delete state.edits.booths['new:' + row._id];
      touched['booths' + (e.name || row.name)] = true;
      return false;
    });

    // Photos `studio apply` has published: the dish's image_url now points at
    // the file it wrote, which is named by the same key the photo is stored
    // under here.
    Object.keys(photos).forEach(function (key) {
      var row = byPhotoKey[key];
      if (row && row.image_url && row.image_url.indexOf('/dish-photos/' + key + '.') !== -1) {
        dropPhoto(key);
        touched['items' + rowKey(row)] = true;
      }
    });

    // Pins DATA already has, to the precision a click can mean anything.
    Object.keys(state.placements).forEach(function (name) {
      var booth = boothsByName[name], pin = state.placements[name];
      if (booth && booth.latitude != null && booth.longitude != null &&
          Math.abs(booth.latitude - pin.latitude) < 1e-6 &&
          Math.abs(booth.longitude - pin.longitude) < 1e-6) {
        delete state.placements[name];
        touched['booths' + name] = true;
      }
    });

    // Deletes: DATA carries only live rows, so a deleted row it no longer
    // lists is a delete that landed.
    Object.keys(state.deleted.items).forEach(function (k) {
      if (k.indexOf('new:') !== 0 && !itemsByKey[k]) { delete state.deleted.items[k]; touched['items' + k] = true; }
    });
    Object.keys(state.deleted.booths).forEach(function (k) {
      if (k.indexOf('new:') !== 0 && !boothsByName[k]) { delete state.deleted.booths[k]; touched['booths' + k] = true; }
    });

    var cleared = Object.keys(touched).length;
    if (cleared) {
      save();
      var note = document.getElementById('settled-note');
      note.textContent = 'Cleared ' + cleared + (cleared === 1 ? ' row' : ' rows') +
        ' whose changes this build already includes — they were applied, so there is nothing left to export for them.';
      document.getElementById('settled-line').classList.remove('hidden');
    }
    return cleared;
  }

  var dbPromise = null;
  function db() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      if (!window.indexedDB) { reject(new Error('no indexedDB')); return; }
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        if (!req.result.objectStoreNames.contains(DB_STORE)) req.result.createObjectStore(DB_STORE);
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
    return dbPromise;
  }
  function dbRun(mode, fn) {
    return db().then(function (conn) {
      return new Promise(function (resolve, reject) {
        var tx = conn.transaction(DB_STORE, mode);
        var req = fn(tx.objectStore(DB_STORE));
        tx.oncomplete = function () { resolve(req && req.result); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }
  function loadPhotos() {
    return dbRun('readonly', function (store) { return store.getAll(); }).then(function (all) {
      (all || []).forEach(function (rec) { if (rec && rec.key) photos[rec.key] = rec; });
    }).catch(function () {
      warn('This browser will not store photos between visits — anything you attach now has to be exported before you close the tab.');
    });
  }
  function putPhoto(rec) {
    photos[rec.key] = rec;
    return dbRun('readwrite', function (store) { return store.put(rec, rec.key); }).catch(function () {});
  }
  function dropPhoto(key) {
    delete photos[key];
    return dbRun('readwrite', function (store) { return store.delete(key); }).catch(function () {});
  }
  function dropAllPhotos() {
    photos = {};
    return dbRun('readwrite', function (store) { return store.clear(); }).catch(function () {});
  }

  // ---------- row identity ----------
  // A dish is identified by booth + name; five booths sell a "Beer Flight".
  // JSON rather than a delimiter: any separator that can appear in a name
  // makes ('A B', 'C') and ('A', 'B C') the same key.
  function isItem(row) { return Object.prototype.hasOwnProperty.call(row, 'booth'); }
  function rowKey(row) {
    if (row._id) return 'new:' + row._id;
    return isItem(row) ? JSON.stringify([row.booth, row.name]) : row.name;
  }
  function bucketFor(row) { return state.edits[isItem(row) ? 'items' : 'booths']; }
  function deletedBucket(row) { return state.deleted[isItem(row) ? 'items' : 'booths']; }

  // Photos are filed under the dish's public_id where there is one - the one
  // identifier stable across a rename and a full re-resolution, and the same
  // thing `epcot-fw images export` names its files by. A row typed in here
  // has no public_id yet, so it brings its own uuid.
  function photoKey(row) { return row.public_id || row._id || rowKey(row); }

  function itemRows() { return DATA.items.concat(state.added.items); }
  function boothRows() { return DATA.booths.concat(state.added.booths); }
  function dishesOf(boothName) {
    return itemRows().filter(function (i) { return i.booth === boothName; });
  }

  function boothByName(name) {
    var all = boothRows();
    for (var i = 0; i < all.length; i++) if (all[i].name === name) return all[i];
    return null;
  }

  // ---------- edit state ----------
  function edited(row, key) {
    var e = bucketFor(row)[rowKey(row)];
    return e && Object.prototype.hasOwnProperty.call(e, key) ? e : null;
  }
  function valueOf(row, key) {
    var e = edited(row, key);
    return e ? e[key] : row[key];
  }
  function isDeleted(row) { return !!deletedBucket(row)[rowKey(row)]; }
  function isAdded(row) { return !!row._id || row.origin === 'curated'; }
  function hasPhoto(row) { return !!photos[photoKey(row)]; }
  function isRowChanged(row) {
    var e = bucketFor(row)[rowKey(row)];
    if (e && Object.keys(e).length) return true;
    if (hasPhoto(row) || isDeleted(row) || row._id) return true;
    return !isItem(row) && !!state.placements[row.name];
  }

  function setValue(row, key, value) {
    var store = bucketFor(row);
    var k = rowKey(row);
    var original = row[key];
    var same = Array.isArray(value)
      ? JSON.stringify(value) === JSON.stringify(original || [])
      : String(value === null || value === undefined ? '' : value) ===
        String(original === null || original === undefined ? '' : original);

    if (same) {
      if (store[k]) {
        delete store[k][key];
        if (!Object.keys(store[k]).length) delete store[k];
      }
    } else {
      store[k] = store[k] || {};
      store[k][key] = value;
    }
    save();
    renderCounts();
  }

  function revert(row) {
    var k = rowKey(row);
    delete bucketFor(row)[k];
    delete deletedBucket(row)[k];
    if (!isItem(row)) delete state.placements[row.name];
    dropPhoto(photoKey(row));
    save();
    render();
  }

  function removeRow(row) {
    if (row._id) {
      // Never applied anywhere, so there is nothing to retire - it just goes.
      var list = isItem(row) ? state.added.items : state.added.booths;
      var at = list.indexOf(row);
      if (at !== -1) list.splice(at, 1);
      delete bucketFor(row)[rowKey(row)];
      dropPhoto(photoKey(row));
    } else {
      deletedBucket(row)[rowKey(row)] = true;
    }
    save();
    render();
  }
  function undelete(row) {
    delete deletedBucket(row)[rowKey(row)];
    save();
    render();
  }

  // A row typed in here and never exported just goes - there is nothing to
  // undo and nothing downstream has heard of it. Deleting a dish that is
  // already in the database is a different act: it travels as a curated
  // `is_active: false`, which beats the crawl that keeps listing it, so it
  // stays gone until somebody says otherwise. Worth one question.
  // In-page stand-ins for prompt() and confirm(). Native dialogs are not a
  // given: the desktop app's preview pane throws on prompt() and answers
  // confirm() with an instant `false` without drawing anything, so URL,
  // Delete and Discard all each did nothing at all - no dialog, no error, no
  // change. A <dialog> works everywhere the Add and Export dialogs already
  // do, and it answers asynchronously, so callers take the result in .then.
  //
  // `value` as a string asks for text and resolves to it, or null on cancel.
  // Without one it is a yes/no and resolves to true or false.
  var askDialog = document.getElementById('ask-dialog');
  var askForm = document.getElementById('ask-form');
  var askInput = document.getElementById('ask-input');
  var askCancel = document.getElementById('ask-cancel');
  function ask(opts) {
    return new Promise(function (resolve) {
      var wantsText = typeof opts.value === 'string';
      document.getElementById('ask-title').textContent = opts.title || '';
      var message = document.getElementById('ask-message');
      message.textContent = opts.message || '';
      message.hidden = !opts.message;
      askInput.hidden = !wantsText;
      askInput.value = wantsText ? opts.value : '';
      askInput.placeholder = opts.placeholder || '';
      document.getElementById('ask-ok').textContent = opts.okLabel || 'OK';
      askCancel.textContent = opts.cancelLabel || 'Cancel';

      var settled = false;
      function finish(answer) {
        if (settled) return;
        settled = true;
        askForm.removeEventListener('submit', onSubmit);
        askCancel.removeEventListener('click', onCancel);
        askDialog.removeEventListener('cancel', onCancel);
        if (askDialog.open) askDialog.close();
        resolve(answer);
      }
      function onSubmit(ev) {
        ev.preventDefault();
        finish(wantsText ? askInput.value : true);
      }
      // Covers the Cancel button and Esc, which fires `cancel` on a modal.
      function onCancel(ev) {
        if (ev) ev.preventDefault();
        finish(wantsText ? null : false);
      }
      askForm.addEventListener('submit', onSubmit);
      askCancel.addEventListener('click', onCancel);
      askDialog.addEventListener('cancel', onCancel);

      if (askDialog.showModal) askDialog.showModal(); else askDialog.setAttribute('open', '');
      if (wantsText) { askInput.focus(); askInput.select(); }
    });
  }

  function deleteDish(row) {
    if (row._id) { removeRow(row); return; }
    var name = valueOf(row, 'name') || 'this dish';
    ask({
      title: 'Delete "' + name + '"?',
      message: 'It stops showing in the app once you export this changeset and apply it, ' +
               'and stays gone through future crawls. Undo is right here until you export.',
      okLabel: 'Delete',
    }).then(function (yes) { if (yes) removeRow(row); });
  }

  function changeCount() {
    var n = 0;
    itemRows().forEach(function (r) { if (isRowChanged(r)) n++; });
    boothRows().forEach(function (r) { if (isRowChanged(r)) n++; });
    return n;
  }

  // ---------- photos ----------
  function currentImage(row) {
    var p = photos[photoKey(row)];
    if (p) return { src: p.dataUrl, attached: true };
    var url = valueOf(row, 'image_url');
    if (url === null || url === undefined || url === '') return null;
    // An edited URL has no inlined copy in this build, so the page has to go
    // and fetch it; an unedited one shows the copy fetch_images.py inlined.
    if (edited(row, 'image_url')) return { src: url, attached: false };
    return { src: row.image || url, attached: false };
  }

  function attachFile(row, file) {
    var reader = new FileReader();
    reader.onload = function () {
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height));
        var canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        var dataUrl;
        try {
          dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
        } catch (e) {
          warn('That image could not be read — try a JPEG or PNG from the camera roll.');
          return;
        }
        putPhoto({ key: photoKey(row), mime: 'image/jpeg', dataUrl: dataUrl }).then(render);
      };
      img.onerror = function () { warn('That file is not an image this browser can read.'); };
      img.src = reader.result;
    };
    reader.onerror = function () { warn('That file could not be read.'); };
    reader.readAsDataURL(file);
  }

  function clearPhoto(row) {
    dropPhoto(photoKey(row)).then(function () {
      // An explicit null, not a deletion: the crawl put a photo on this dish
      // and only a curated value that says "no photo" can take it back off.
      setValue(row, 'image_url', null);
      render();
    });
  }

  function useUrl(row) {
    ask({
      title: 'Image URL',
      message: 'Paste the address of a photo of ' + (valueOf(row, 'name') || 'this dish') +
               '. Leave it empty to remove the current one.',
      value: valueOf(row, 'image_url') || '',
      placeholder: 'Paste an image address',
      okLabel: 'Use this photo',
    }).then(function (url) {
      if (url === null) return;
      url = url.trim();
      dropPhoto(photoKey(row)).then(function () {
        setValue(row, 'image_url', url || null);
        render();
      });
    });
  }

  // ---------- map drawer ----------
  // The map is a tool you pick up for one booth at a time, so it lives in a
  // drawer rather than a region of the page. A pin dropped or dragged in it
  // is a draft: nothing reaches state.placements - and so nothing reaches
  // the export - until Save location. Close, Cancel and Esc leave everything
  // as it was.

  // A dropped pin beats whatever the database already had for that booth.
  function positionOf(booth) {
    if (!booth) return null;
    var p = state.placements[booth.name];
    if (p) return { lat: p.latitude, lon: p.longitude, precision: 'mapped' };
    var lat = booth.latitude;
    if (lat === null || lat === undefined) return null;
    return { lat: Number(lat), lon: Number(booth.longitude), precision: booth.location_precision || 'anchored' };
  }

  var PIN_COLOR = { mapped: 'var(--ink)', anchored: 'var(--ink-3)', surveyed: 'var(--good)' };
  function pinIcon(precision, mode) {
    return L.divIcon({
      className: 'booth-pin' + (mode ? ' ' + mode : ''),
      html: '<span style="background:' + (PIN_COLOR[precision] || 'var(--ink-3)') + '"></span>',
      iconSize: [18, 18], iconAnchor: [9, 9]
    });
  }

  var haveLeaflet = typeof L !== 'undefined';
  var map = null, markers = {}, draftMarker = null, layers = {};
  var drawerEl = document.getElementById('map-drawer');
  var scrimEl = document.getElementById('scrim');

  function initMap() {
    if (map || !haveLeaflet) return;
    map = L.map('map').setView(CENTER, ZOOM);
    layers.sat = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 20, maxNativeZoom: 19, attribution: 'Tiles &copy; Esri' }
    );
    layers.streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    });
    layers.sat.addTo(map);

    map.on('click', function (e) {
      if (!state.drawer || !state.drawer.booth || !festivalEditable()) return;
      setDraft(e.latlng.lat, e.latlng.lng);
    });
  }

  function setLayer(name) {
    if (!map) return;
    Object.keys(layers).forEach(function (k) {
      if (k === name) { if (!map.hasLayer(layers[k])) layers[k].addTo(map); }
      else if (map.hasLayer(layers[k])) map.removeLayer(layers[k]);
    });
    Array.prototype.forEach.call(document.querySelectorAll('#layer-toggle button'), function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-layer') === name ? 'true' : 'false');
    });
  }

  function setDraft(lat, lon) {
    if (!state.drawer) return;
    state.drawer.draft = { latitude: Number(lat.toFixed(6)), longitude: Number(lon.toFixed(6)) };
    renderDrawer();
  }

  // One marker per placed booth, created once then updated in place, so
  // dragging and re-renders don't fight each other. With a booth in the
  // drawer its own pin is the only one that moves; the rest are context.
  function syncMarkers() {
    if (!map) return;
    var focus = state.drawer && state.drawer.booth;
    var draft = state.drawer && state.drawer.draft;
    boothRows().forEach(function (booth) {
      var pos = isDeleted(booth) ? null : positionOf(booth);
      var isFocus = focus === booth.name;
      // While a draft exists the booth's saved pin steps aside for it.
      if (isFocus && draft) pos = null;
      var existing = markers[booth.name];
      if (!pos) {
        if (existing) { map.removeLayer(existing); delete markers[booth.name]; }
        return;
      }
      var mode = focus ? (isFocus ? 'active' : 'dim') : '';
      var draggable = isFocus && festivalEditable();
      if (!existing) {
        existing = L.marker([pos.lat, pos.lon], { icon: pinIcon(pos.precision, mode), draggable: true });
        existing.bindTooltip(booth.name, { permanent: false, direction: 'top', offset: [0, -10], className: 'booth-tooltip' });
        existing.on('dragend', function () {
          var ll = existing.getLatLng();
          setDraft(ll.lat, ll.lng);
        });
        // In the overview a pin is a way into its booth.
        existing.on('click', function () {
          if (state.drawer && !state.drawer.booth) focusBooth(booth.name);
        });
        existing.addTo(map);
        markers[booth.name] = existing;
      }
      existing.setLatLng([pos.lat, pos.lon]);
      existing.setIcon(pinIcon(pos.precision, mode));
      if (existing.dragging) { draggable ? existing.dragging.enable() : existing.dragging.disable(); }
    });

    if (draft) {
      if (!draftMarker) {
        draftMarker = L.marker([draft.latitude, draft.longitude], { icon: pinIcon('mapped', 'draft'), draggable: true });
        draftMarker.on('dragend', function () {
          var ll = draftMarker.getLatLng();
          setDraft(ll.lat, ll.lng);
        });
        draftMarker.addTo(map);
      }
      draftMarker.setLatLng([draft.latitude, draft.longitude]);
    } else if (draftMarker) {
      map.removeLayer(draftMarker);
      draftMarker = null;
    }
    document.getElementById('map').classList.toggle('placing', !!focus && festivalEditable());
  }

  function renderDrawer() {
    if (!state.drawer) return;
    var name = state.drawer.booth;
    var booth = name ? boothByName(name) : null;
    var draft = state.drawer.draft;
    var pos = booth ? positionOf(booth) : null;

    document.getElementById('drawer-title').textContent = booth ? valueOf(booth, 'name') : 'All booths';
    var where = document.getElementById('drawer-position');
    if (!booth) {
      where.textContent = 'Click a pin to open that booth.';
    } else if (draft) {
      where.innerHTML = '<span class="mono">' + draft.latitude.toFixed(5) + ', ' + draft.longitude.toFixed(5) +
        '</span> <span class="pill unplaced">Unsaved</span>';
    } else if (pos) {
      where.innerHTML = '<span class="mono">' + pos.lat.toFixed(5) + ', ' + pos.lon.toFixed(5) +
        '</span> <span class="pill ' + pos.precision + '">' + esc(pos.precision) + '</span>';
    } else {
      where.innerHTML = '<span class="pill unplaced">Not placed</span>';
    }

    var hint = document.getElementById('drawer-hint');
    hint.classList.toggle('hidden', !booth || !haveLeaflet);
    hint.textContent = draft ? 'Drag the orange pin to fine-tune it, then Save location.'
      : pos ? 'Click the map, or drag the pin, to move ' + valueOf(booth, 'name') + '.'
      : 'Click the map where ' + (booth ? valueOf(booth, 'name') : 'the booth') + ' stands.';

    document.getElementById('tallies').classList.toggle('hidden', !!booth);
    document.getElementById('drawer-save').disabled = !draft || !festivalEditable();
    document.getElementById('drawer-save').classList.toggle('hidden', !booth);
    document.getElementById('drawer-remove').classList.toggle('hidden', !booth || !state.placements[name] || !!draft);
    document.getElementById('drawer-cancel').textContent = booth ? 'Cancel' : 'Close';
    renderTallies();
    syncMarkers();
  }

  function openDrawer(name) {
    var wasOpen = !!state.drawer;
    state.drawer = { booth: name || null, draft: null };
    drawerEl.classList.add('open');
    scrimEl.classList.add('open');
    drawerEl.removeAttribute('inert');
    document.getElementById('offline-note').classList.toggle('hidden', haveLeaflet);
    initMap();
    renderDrawer();
    // Leaflet measures its container when it is created and again only when
    // told to; one built mid-slide comes out as a single grey tile.
    var settleMap = function () {
      if (!map) return;
      map.invalidateSize();
      var booth = name ? boothByName(name) : null;
      var pos = booth ? positionOf(booth) : null;
      if (pos) map.setView([pos.lat, pos.lon], Math.max(map.getZoom(), 19));
      else if (!name) map.setView(CENTER, ZOOM);
    };
    if (wasOpen) settleMap(); else setTimeout(settleMap, 240);
    document.getElementById('drawer-close').focus();
  }

  // From a pin in the overview: open that booth on the left and switch the
  // drawer to placing it, without closing anything.
  function focusBooth(name) {
    select(name);
    openDrawer(name);
  }

  function shutDrawer() {
    state.drawer = null;
    drawerEl.classList.remove('open');
    scrimEl.classList.remove('open');
    drawerEl.setAttribute('inert', '');
    syncMarkers();
    render();
  }

  function closeDrawer() {
    if (!state.drawer) return;
    if (!state.drawer.draft) { shutDrawer(); return; }
    ask({
      title: 'Discard this pin?',
      message: 'The new position for ' + state.drawer.booth + ' has not been saved.',
      okLabel: 'Discard pin',
      cancelLabel: 'Keep editing',
    }).then(function (yes) { if (yes) shutDrawer(); });
  }

  function saveDrawer() {
    var d = state.drawer;
    if (!d || !d.booth || !d.draft || !festivalEditable()) return;
    state.placements[d.booth] = {
      latitude: d.draft.latitude,
      longitude: d.draft.longitude,
      placed_at: new Date().toISOString()
    };
    save();
    shutDrawer();
  }

  function removeStagedPin() {
    var d = state.drawer;
    if (!d || !d.booth) return;
    delete state.placements[d.booth];
    save();
    renderDrawer();
    render();
  }

  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
  document.getElementById('drawer-cancel').addEventListener('click', closeDrawer);
  document.getElementById('drawer-save').addEventListener('click', saveDrawer);
  document.getElementById('drawer-remove').addEventListener('click', removeStagedPin);
  scrimEl.addEventListener('click', closeDrawer);
  Array.prototype.forEach.call(document.querySelectorAll('#layer-toggle button'), function (b) {
    b.addEventListener('click', function () { setLayer(b.getAttribute('data-layer')); });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !state.drawer) return;
    // Esc inside one of the dialogs belongs to that dialog.
    if (document.querySelector('dialog[open]')) return;
    closeDrawer();
  });

  // ---------- filtering ----------
  // The rail's chips are about a booth as a whole ("not placed"), or about
  // work done anywhere inside it ("edited", "added by hand") - a booth whose
  // only change is one corrected dish still has to be findable, or the
  // filter cannot answer the question it exists to answer.
  function visibleBooths() {
    return boothRows().filter(function (booth) {
      var dishes = dishesOf(booth.name);
      if (state.unplacedOnly && positionOf(booth)) return false;
      if (state.editedOnly && !isRowChanged(booth) && !dishes.some(isRowChanged)) return false;
      if (state.addedOnly && !isAdded(booth) && !dishes.some(isAdded)) return false;
      if (state.boothQ) {
        var hay = [valueOf(booth, 'name'), valueOf(booth, 'location_description')]
          .join(' ').toLowerCase();
        if (hay.indexOf(state.boothQ) === -1) return false;
      }
      return true;
    });
  }

  function visibleDishes() {
    if (!state.selected) return [];
    return dishesOf(state.selected).filter(function (row) {
      if (state.editedOnly && !isRowChanged(row)) return false;
      if (state.addedOnly && !isAdded(row)) return false;
      if (state.category && valueOf(row, 'category') !== state.category) return false;
      if (state.noPhotoOnly && currentImage(row)) return false;
      if (state.newOnly && !valueOf(row, 'is_new_this_year')) return false;
      if (state.dishQ) {
        var hay = [valueOf(row, 'name'), valueOf(row, 'description')].join(' ').toLowerCase();
        if (hay.indexOf(state.dishQ) === -1) return false;
      }
      return true;
    });
  }

  // A selection can go stale: the booth it named may have been filtered out
  // of existence by a discard, or removed outright if it was one typed in
  // here. Falling back to the empty state is the honest answer.
  function selectedBooth() {
    return state.selected ? boothByName(state.selected) : null;
  }

  function select(name) {
    state.selected = name;
    state.expandedTags = null;
    save();
    render();
    // The dish pane is one element reused for every booth, so without this
    // opening a booth after scrolling through a long menu lands you halfway
    // down the new one. Filtering within a booth deliberately does not reset
    // it - that would throw away your place on every keystroke.
    document.getElementById('detail').scrollTop = 0;
  }

  // ---------- field widgets ----------
  function makeInput(row, key, kind, placeholder) {
    var value = valueOf(row, key);
    var el;
    if (kind === 'textarea') {
      el = document.createElement('textarea');
      el.rows = 2;
    } else if (kind === 'select') {
      el = document.createElement('select');
      CATEGORIES.forEach(function (c) {
        var o = document.createElement('option');
        o.value = c;
        o.textContent = c.replace(/_/g, ' ');
        el.appendChild(o);
      });
    } else if (kind === 'price') {
      el = document.createElement('input');
      el.type = 'number';
      el.step = '0.01';
      el.min = '0';
    } else if (kind === 'date') {
      el = document.createElement('input');
      el.type = 'date';
      // <input type="date">'s own value is already plain YYYY-MM-DD - the
      // exact shape date.isoformat() writes and date.fromisoformat() reads
      // on the way back in, so this kind needs no special-casing below.
    } else {
      el = document.createElement('input');
      el.type = 'text';
    }
    el.value = value === null || value === undefined ? (kind === 'select' ? 'food' : '') : value;
    if (placeholder) el.placeholder = placeholder;
    el.className = 'cell-input' + (edited(row, key) ? ' changed' : '') + (kind === 'price' ? ' price' : '');
    el.addEventListener('change', function () {
      var next = el.value;
      if (kind === 'price') next = el.value === '' ? null : Number(el.value);
      else if (next === '') next = null;
      setValue(row, key, next);
      el.classList.toggle('changed', !!edited(row, key));
      markRow(el, row);
    });
    return el;
  }

  function makeTagCell(row) {
    var cell = document.createElement('div');
    cell.className = 'tag-cell';
    var key = rowKey(row);

    function paint() {
      cell.innerHTML = '';
      if (state.expandedTags === key) { cell.appendChild(makeTagPicker(row, paint)); return; }
      var summary = document.createElement('div');
      summary.className = 'tag-summary';
      var current = valueOf(row, 'tags') || [];
      var label = document.createElement('span');
      label.className = 'tag-none';
      label.textContent = 'dietary';
      summary.appendChild(label);
      if (!current.length) {
        var none = document.createElement('span');
        none.className = 'tag-empty';
        none.textContent = 'none';
        summary.appendChild(none);
      }
      current.forEach(function (tag) {
        var chip = document.createElement('span');
        chip.className = 'tag-toggle on' + (edited(row, 'tags') ? ' changed' : '');
        chip.textContent = tag.replace(/_/g, ' ');
        summary.appendChild(chip);
      });
      var edit = document.createElement('span');
      edit.className = 'tag-edit';
      edit.textContent = 'edit';
      summary.appendChild(edit);
      summary.addEventListener('click', function () { state.expandedTags = key; paint(); });
      cell.appendChild(summary);
    }
    paint();
    return cell;
  }

  // Sweet and savoury, as two independent chips rather than a choice: a dish
  // can be both (candied pecans on a plate of fries) and most drinks are
  // neither, so there is nothing here to force.
  function makeFlavourCell(row) {
    var cell = document.createElement('div');
    cell.className = 'new-cell';

    var label = document.createElement('span');
    label.className = 'tag-none';
    label.textContent = 'flavour';
    cell.appendChild(label);

    FLAVOUR_TAGS.forEach(function (code) {
      var btn = document.createElement('button');
      btn.type = 'button';

      function paint() {
        var on = (valueOf(row, 'flavor_tags') || []).indexOf(code) !== -1;
        btn.className = 'tag-toggle' + (on ? ' on' : '') +
          (edited(row, 'flavor_tags') ? ' changed' : '');
        btn.textContent = code;
      }

      btn.addEventListener('click', function () {
        var next = (valueOf(row, 'flavor_tags') || []).slice();
        var at = next.indexOf(code);
        if (at === -1) next.push(code); else next.splice(at, 1);
        next.sort();
        setValue(row, 'flavor_tags', next);
        // Repaint both chips: the `changed` outline belongs to the field, not
        // to whichever one was clicked.
        Array.prototype.forEach.call(cell.querySelectorAll('button'), function (b) {
          if (b.repaint) b.repaint();
        });
        markRow(btn, row);
      });

      btn.repaint = paint;
      paint();
      cell.appendChild(btn);
    });

    return cell;
  }

  // Only on a drink the menu calls alcoholic - "Kirschwasser Torte" is a cake
  // and "Beer-braised Beef" is a plate of beef, and neither wants this.
  function makeAlcoholCell(row) {
    var cell = document.createElement('div');
    cell.className = 'geo';
    if (valueOf(row, 'category') !== 'alcoholic_beverage') return cell;

    var label = document.createElement('span');
    label.className = 'tag-none';
    label.textContent = 'kind';
    cell.appendChild(label);

    var sel = document.createElement('select');
    sel.className = 'cell-input' + (edited(row, 'alcohol_kind') ? ' changed' : '');
    [''].concat(ALCOHOL_KINDS).forEach(function (k) {
      var o = document.createElement('option');
      o.value = k;
      o.textContent = k || 'not set';
      sel.appendChild(o);
    });
    sel.value = valueOf(row, 'alcohol_kind') || '';
    sel.addEventListener('change', function () {
      setValue(row, 'alcohol_kind', sel.value === '' ? null : sel.value);
      sel.classList.toggle('changed', !!edited(row, 'alcohol_kind'));
      markRow(sel, row);
    });
    cell.appendChild(sel);
    return cell;
  }

  // One chip, on or off, styled as a dietary tag is - but stored as its own
  // field, not as a tag. "New this year" is a fact about the festival's
  // line-up, and a diet filter is not where anyone would look for it.
  function makeNewCell(row) {
    var cell = document.createElement('div');
    cell.className = 'new-cell';
    var btn = document.createElement('button');
    btn.type = 'button';

    function paint() {
      var on = !!valueOf(row, 'is_new_this_year');
      btn.className = 'tag-toggle' + (on ? ' on' : '') +
        (edited(row, 'is_new_this_year') ? ' changed' : '');
      btn.textContent = 'New this year';
    }

    btn.addEventListener('click', function () {
      setValue(row, 'is_new_this_year', !valueOf(row, 'is_new_this_year'));
      paint();
      markRow(btn, row);
    });

    paint();
    cell.appendChild(btn);
    return cell;
  }

  function makeTagPicker(row, repaint) {
    var wrap = document.createElement('div');
    wrap.className = 'tag-picker';
    TAGS.forEach(function (tag) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tag-toggle';
      btn.textContent = tag.replace(/_/g, ' ');
      btn.addEventListener('click', function () {
        var next = (valueOf(row, 'tags') || []).slice();
        var at = next.indexOf(tag);
        if (at === -1) next.push(tag); else next.splice(at, 1);
        next.sort();
        setValue(row, 'tags', next);
        paintToggles(wrap, row);
        markRow(wrap, row);
      });
      wrap.appendChild(btn);
    });
    var done = document.createElement('button');
    done.type = 'button';
    done.className = 'tag-done';
    done.textContent = 'done';
    done.addEventListener('click', function () { state.expandedTags = null; if (repaint) repaint(); });
    wrap.appendChild(done);
    paintToggles(wrap, row);
    return wrap;
  }

  // Only the toggles. The picker also holds a "done" button, and walking
  // every child by index repaints that one as TAGS[7] - an undefined tag,
  // which turns the button into a dead chip on the first toggle.
  function paintToggles(wrap, row) {
    var current = valueOf(row, 'tags') || [];
    var changed = !!edited(row, 'tags');
    var buttons = wrap.querySelectorAll('button.tag-toggle');
    Array.prototype.forEach.call(buttons, function (btn, i) {
      btn.className = 'tag-toggle' + (current.indexOf(TAGS[i]) !== -1 ? ' on' : '') + (changed ? ' changed' : '');
    });
  }

  function markRow(el, row) {
    var card = el.closest ? el.closest('.row') : null;
    if (card) card.classList.toggle('edited', isRowChanged(row));
    // The rail summarises what has been touched inside each booth, so an
    // edit made over here has to show up over there. Cheap: 32 buttons, and
    // focus is in the detail pane, not in what gets rebuilt.
    renderRail();
  }

  // ---------- rendering ----------
  var boothList = document.getElementById('booth-list');
  var dishList = document.getElementById('dish-list');

  function button(label, cls, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
  }

  function renderThumb(row) {
    var col = document.createElement('div');
    var thumb = document.createElement('div');
    var img = currentImage(row);
    thumb.className = 'thumb' + (img ? '' : ' empty');
    if (img) {
      var el = document.createElement('img');
      el.src = img.src;
      el.alt = '';
      el.loading = 'lazy';
      thumb.appendChild(el);
      if (img.attached) {
        var badge = document.createElement('span');
        badge.className = 'badge';
        badge.textContent = 'attached';
        thumb.appendChild(badge);
      }
    } else {
      var label = document.createElement('span');
      label.className = 'thumb-empty-label';
      label.textContent = 'No photo';
      thumb.appendChild(label);
    }
    col.appendChild(thumb);

    var actions = document.createElement('div');
    actions.className = 'photo-actions';
    var picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/*';
    picker.addEventListener('change', function () {
      if (picker.files && picker.files[0]) attachFile(row, picker.files[0]);
      picker.value = '';
    });
    actions.appendChild(picker);
    actions.appendChild(button(img ? 'Replace' : 'Add photo', '', function () { picker.click(); }));
    actions.appendChild(button('URL', '', function () { useUrl(row); }));
    if (img) actions.appendChild(button('Clear', '', function () { clearPhoto(row); }));
    col.appendChild(actions);
    col.appendChild(renderCredit(row, img));
    return col;
  }

  // The credit line, and the element another page reads this out of. Every
  // fact is on the element as a data-* attribute as well as in the text, so
  // a consumer never has to parse the sentence back apart.
  function renderCredit(row, img) {
    var el = document.createElement('div');
    el.className = 'photo-credit';
    if (!img) return el;

    // An attached photo has not been exported yet, so the snapshot's source
    // is about whatever it is replacing, not about this picture.
    var src = img.attached ? { credit: 'Added by hand', site: null, season: null, page_url: null, via: 'studio' }
                           : (row.image_source || {});
    var credit = src.credit || 'Unknown';

    el.setAttribute('data-credit', credit);
    if (src.site) el.setAttribute('data-site', src.site);
    if (src.season) el.setAttribute('data-season', src.season);
    if (src.page_url) el.setAttribute('data-page-url', src.page_url);
    if (src.via) el.setAttribute('data-via', src.via);
    var url = valueOf(row, 'image_url');
    if (url) el.setAttribute('data-image-url', url);
    el.setAttribute('data-dish', valueOf(row, 'name') || '');
    el.setAttribute('data-booth', row.booth || '');
    if (row.public_id) el.setAttribute('data-public-id', row.public_id);

    var parts = ['Photo: ' + esc(credit)];
    if (src.season) parts.push('<span class="season">' + esc(src.season) + '</span>');
    el.innerHTML = parts.join(' · ');
    if (src.page_url) {
      var a = document.createElement('a');
      a.href = src.page_url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = 'source';
      el.appendChild(document.createTextNode(' · '));
      el.appendChild(a);
    }
    return el;
  }

  function renderItemRow(row) {
    var card = document.createElement('div');
    card.className = 'row' + (isRowChanged(row) ? ' edited' : '') +
      (isAdded(row) ? ' added' : '') + (isDeleted(row) ? ' deleted' : '');

    card.appendChild(renderThumb(row));

    var fields = document.createElement('div');
    fields.className = 'fields';

    // No booth label: these rows only ever appear under that booth's own
    // heading, and repeating it 209 times was noise even when they didn't.
    // A deleted row says so whatever its origin - a crawled dish dimmed to
    // 55% and nothing else would read as a rendering glitch.
    if (isAdded(row) || isDeleted(row)) {
      var head = document.createElement('div');
      head.className = 'row-head';
      var pill = document.createElement('span');
      pill.className = isDeleted(row) ? 'pill deleted' : 'pill curated';
      pill.textContent = isDeleted(row) ? 'Deleted' : 'Added by hand';
      head.appendChild(pill);
      fields.appendChild(head);
    }

    fields.appendChild(makeInput(row, 'name', 'text', 'Dish name'));
    fields.appendChild(makeInput(row, 'description', 'textarea', 'Description'));

    var line = document.createElement('div');
    line.className = 'field-row';
    line.appendChild(makeInput(row, 'price', 'price', 'Price'));
    line.appendChild(makeInput(row, 'category', 'select'));
    fields.appendChild(line);

    var attrs = document.createElement('div');
    attrs.className = 'attrs';
    attrs.appendChild(makeTagCell(row));
    attrs.appendChild(makeFlavourCell(row));
    attrs.appendChild(makeAlcoholCell(row));
    attrs.appendChild(makeNewCell(row));
    fields.appendChild(attrs);

    var actions = document.createElement('div');
    actions.className = 'row-actions';
    if (isRowChanged(row) && !row._id) actions.appendChild(button('Revert', 'linkish', function () { revert(row); }));
    // Every dish, not only the hand-added ones: the crawl lists the same dish
    // twice under two spellings often enough, and a wrong row nobody can
    // remove is a wrong row the app goes on showing.
    actions.appendChild(isDeleted(row)
      ? button('Undo delete', 'linkish', function () { undelete(row); })
      : button('Delete', 'linkish', function () { deleteDish(row); }));
    if (actions.childNodes.length) fields.appendChild(actions);

    card.appendChild(fields);
    return card;
  }

  // The rail row: enough to choose by, and nothing to edit. Everything
  // editable about a booth lives in the detail pane, so the whole list stays
  // scannable in one narrow column.
  function renderBoothItem(booth) {
    var dishes = dishesOf(booth.name);
    var pos = positionOf(booth);
    var changed = isRowChanged(booth) || dishes.some(isRowChanged);

    var card = document.createElement('button');
    card.type = 'button';
    card.className = 'booth-item' + (state.selected === booth.name ? ' selected' : '') +
      (isDeleted(booth) ? ' deleted' : '');
    card.setAttribute('aria-pressed', state.selected === booth.name ? 'true' : 'false');

    var withPhoto = dishes.filter(function (d) { return currentImage(d); }).length;
    var meta = [];
    if (dishes.length) meta.push(withPhoto + '/' + dishes.length + ' photographed');
    if (booth.name !== AGGREGATE_BOOTH_NAME) {
      meta.push(pos ? esc(pos.precision) : '<span style="color:var(--signal)">not placed</span>');
    }
    if (isAdded(booth)) meta.push(isDeleted(booth) ? 'deleted' : 'by hand');
    var opensAt = opensAtIfFuture(booth);
    if (opensAt) meta.push('opens ' + esc(formatOpeningDate(opensAt)));

    card.innerHTML =
      '<span class="booth-item-name">' + esc(valueOf(booth, 'name')) + '</span>' +
      '<span class="booth-item-count">' +
        (changed ? '<span class="changed-dot" title="Has unexported changes"></span>' : '') +
        dishes.length +
      '</span>' +
      '<span class="booth-item-meta">' + meta.join(' · ') + '</span>';

    card.addEventListener('click', function () { select(booth.name); });
    return card;
  }

  function fieldBlock(labelText, control, wide) {
    var wrap = document.createElement('div');
    wrap.className = 'field' + (wide ? ' wide' : '');
    var label = document.createElement('span');
    label.className = 'label';
    label.textContent = labelText;
    wrap.appendChild(label);
    wrap.appendChild(control);
    return wrap;
  }

  // The detail pane's header: the same booth, now editable, with where it
  // stands one click from the map.
  function renderBoothDetail(row) {
    var card = document.createElement('div');
    card.className = 'booth-panel' + (isDeleted(row) ? ' deleted' : '');

    var pos = positionOf(row);
    var head = document.createElement('div');
    head.className = 'booth-title';
    var live = dishesOf(row.name).length;
    head.innerHTML = '<h2>' + esc(valueOf(row, 'name')) + '</h2>' +
      '<span class="count">' + live + (live === 1 ? ' dish' : ' dishes') + '</span>';
    if (isAdded(row)) {
      var pill = document.createElement('span');
      pill.className = isDeleted(row) ? 'pill deleted' : 'pill curated';
      pill.textContent = isDeleted(row) ? 'Deleted' : 'Added by hand';
      head.appendChild(pill);
    }
    var openingPill = null;
    var futureAt = opensAtIfFuture(row);
    if (futureAt) {
      openingPill = document.createElement('span');
      openingPill.className = 'pill opens-later';
      openingPill.textContent = 'Opens ' + formatOpeningDate(futureAt);
      head.appendChild(openingPill);
    }
    card.appendChild(head);

    var fields = document.createElement('div');
    fields.className = 'booth-fields';
    fields.appendChild(fieldBlock('Category', makeInput(row, 'category', 'text', 'Category')));

    // When this isn't set, or is today or earlier, the booth reads as open
    // now - the case every booth was in before this field existed, so
    // nothing needs to be entered for the common case.
    var opening = document.createElement('div');
    opening.className = 'inline';
    var openingInput = makeInput(row, 'opens_at', 'date');
    openingInput.style.width = 'auto';
    opening.appendChild(openingInput);

    // A date is far easier to set than to unset: the native control offers no
    // clear of its own on every browser, so a date typed by mistake had no way
    // back except retyping something wrong. Stages an explicit null, which is
    // what erases the field rather than leaving it open for a later source
    // (see NULLABLE_BOOTH_FIELDS).
    var openingClear = button('Clear', '', function () {
      setValue(row, 'opens_at', null);
      openingInput.value = '';
      openingInput.classList.toggle('changed', !!edited(row, 'opens_at'));
      markRow(openingInput, row);
      syncOpening();
    });
    opening.appendChild(openingClear);

    // The header's pill is a preview, not a form field, so only it needs a
    // nudge - re-rendering the pane would lose whatever was mid-edit below.
    function syncOpening() {
      openingClear.style.display = valueOf(row, 'opens_at') ? '' : 'none';
      if (openingPill) { openingPill.remove(); openingPill = null; }
      var stillFuture = opensAtIfFuture(row);
      if (stillFuture) {
        openingPill = document.createElement('span');
        openingPill.className = 'pill opens-later';
        openingPill.textContent = 'Opens ' + formatOpeningDate(stillFuture);
        head.appendChild(openingPill);
      }
    }
    openingInput.addEventListener('change', syncOpening);
    openingClear.style.display = valueOf(row, 'opens_at') ? '' : 'none';
    fields.appendChild(fieldBlock('Opening', opening));
    fields.appendChild(fieldBlock('Location description',
      makeInput(row, 'location_description', 'text', 'Where to find it'), true));
    card.appendChild(fields);

    var location = document.createElement('div');
    location.className = 'location';
    var label = document.createElement('span');
    label.className = 'label';
    label.textContent = 'Location';
    location.appendChild(label);
    var coords = document.createElement('span');
    coords.innerHTML = pos
      ? '<span class="mono">' + pos.lat.toFixed(5) + ', ' + pos.lon.toFixed(5) + '</span> ' +
        '<span class="pill ' + pos.precision + '">' + esc(pos.precision) + '</span>'
      : '<span class="pill unplaced">Not placed</span>';
    location.appendChild(coords);
    if (row.name !== AGGREGATE_BOOTH_NAME) {
      location.appendChild(button(pos ? 'Edit pin' : 'Place on map', '',
        function () { openDrawer(row.name); }));
    }
    var spacer = document.createElement('span');
    spacer.style.flex = '1 1 auto';
    location.appendChild(spacer);

    var actions = document.createElement('span');
    actions.className = 'booth-actions';
    if (isRowChanged(row) && !row._id) actions.appendChild(button('Revert booth', 'linkish', function () { revert(row); }));
    if (isAdded(row)) {
      actions.appendChild(isDeleted(row)
        ? button('Undo delete', 'linkish', function () { undelete(row); })
        : button('Delete booth', 'linkish', function () { removeRow(row); }));
    }
    location.appendChild(actions);
    card.appendChild(location);
    return card;
  }

  function renderTallies() {
    var surveyed = 0, mapped = 0, anchored = 0, unplaced = 0, all = boothRows();
    all.forEach(function (b) {
      var pos = positionOf(b);
      if (!pos) unplaced++;
      else if (pos.precision === 'surveyed') surveyed++;
      else if (pos.precision === 'mapped') mapped++;
      else anchored++;
    });
    document.getElementById('tallies').innerHTML =
      '<span class="tally">Booths <b>' + all.length + '</b></span>' +
      '<span class="tally">Surveyed <b>' + surveyed + '</b></span>' +
      '<span class="tally">Mapped <b>' + mapped + '</b></span>' +
      '<span class="tally">Anchored <b>' + anchored + '</b></span>' +
      '<span class="tally">Not placed <b>' + unplaced + '</b></span>';
  }

  function renderCounts() {
    var n = changeCount();
    document.getElementById('edit-count').innerHTML =
      n === 0 ? 'No changes' : '<b>' + n + '</b> changed';
    document.getElementById('export').disabled = n === 0 || !festivalEditable();
    document.getElementById('map-btn').disabled = !festivalEditable();
  }

  // ---------- festivals ----------
  // Four festivals, one database. Only the festival this snapshot was built
  // from can be edited: the curated files and `studio apply` know about one
  // festival, so a dish typed under any other would be exported into this
  // one. The rest are shown, honestly empty, so the switcher is ready for
  // the day they are crawled.
  function currentFestival() {
    var withData = null, picked = null;
    FESTIVALS.forEach(function (f) {
      if (f.has_data && !withData) withData = f;
      if (f.key === state.festival) picked = f;
    });
    return picked || withData || FESTIVALS[0];
  }
  function liveFestival() {
    return FESTIVALS.filter(function (f) { return f.has_data; })[0] || null;
  }
  function festivalEditable() {
    var f = currentFestival();
    return !!(f && f.has_data);
  }

  function renderFestivals() {
    var nav = document.getElementById('festivals');
    var current = currentFestival();
    nav.innerHTML = '';
    FESTIVALS.forEach(function (f) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('aria-pressed', f.key === current.key ? 'true' : 'false');
      b.title = f.name + ' · ' + f.season + (f.has_data ? '' : ' · no data yet');
      b.textContent = f.short;
      b.addEventListener('click', function () {
        if (state.festival === f.key) return;
        if (state.drawer) shutDrawer();
        state.festival = f.key;
        save();
        render();
      });
      nav.appendChild(b);
    });
  }

  function renderFestivalEmpty() {
    var f = currentFestival();
    document.getElementById('festival-empty').innerHTML =
      '<span class="label">' + esc(f.season) + '</span>' +
      '<h2>' + esc(f.name) + '</h2>' +
      '<p>No menu data yet. This festival hasn’t been crawled, so there is nothing here to correct. ' +
      (liveFestival() ? 'Your ' + esc(liveFestival().short) + ' edits are untouched.' : '') + '</p>' +
      '<div class="stats">' +
        '<div><b>0</b><span class="label">Booths</span></div>' +
        '<div><b>0</b><span class="label">Dishes</span></div>' +
        '<div><b>0</b><span class="label">Photos</span></div>' +
      '</div>';
  }

  function emptyNote(text) {
    var el = document.createElement('div');
    el.className = 'empty-state';
    el.textContent = text;
    return el;
  }

  function renderRail() {
    var booths = visibleBooths();
    boothList.innerHTML = '';
    if (!booths.length) {
      boothList.appendChild(emptyNote(
        state.editedOnly ? 'Nothing changed yet.' : 'No booth matches those filters.'
      ));
    }
    booths.forEach(function (booth) { boothList.appendChild(renderBoothItem(booth)); });
    document.getElementById('booth-count').textContent =
      booths.length + ' of ' + boothRows().length;
  }

  function renderDetail() {
    var booth = selectedBooth();
    var layout = document.getElementById('layout');
    layout.classList.toggle('picked', !!booth);
    document.getElementById('detail-empty').classList.toggle('hidden', !!booth);
    document.getElementById('detail-body').classList.toggle('hidden', !booth);

    var header = document.getElementById('booth-detail');
    header.innerHTML = '';
    dishList.innerHTML = '';
    if (!booth) {
      // A selection can name a booth that no longer exists - one typed in
      // here and then removed. Clear it rather than leaving a dead pane.
      if (state.selected) { state.selected = null; save(); }
      return;
    }

    header.appendChild(renderBoothDetail(booth));
    document.getElementById('toolbar-title').textContent = valueOf(booth, 'name');

    var dishes = visibleDishes();
    if (!dishes.length) {
      dishList.appendChild(emptyNote(
        dishesOf(booth.name).length
          ? 'No dish on this menu matches those filters.'
          : 'No dishes here yet. Add one by hand if the crawl missed them.'
      ));
    }
    dishes.forEach(function (row) { dishList.appendChild(renderItemRow(row)); });

    var total = dishesOf(booth.name).length;
    document.getElementById('dish-count').textContent =
      dishes.length === total
        ? total + (total === 1 ? ' dish' : ' dishes')
        : dishes.length + ' of ' + total;
  }

  function render() {
    renderFestivals();
    var editable = festivalEditable();
    document.getElementById('layout').classList.toggle('hidden', !editable);
    document.getElementById('festival-empty').classList.toggle('hidden', editable);
    if (!editable) renderFestivalEmpty();
    renderRail();
    renderDetail();
    renderCounts();
    if (state.drawer) renderDrawer(); else syncMarkers();
  }

  // ---------- export ----------
  // Only what changed. A changeset listing every dish would freeze the whole
  // menu against the crawl at priority_rank 0, so a later price correction
  // from a source could never land.
  function stripDataPrefix(dataUrl) {
    var at = dataUrl.indexOf(',');
    return at === -1 ? dataUrl : dataUrl.slice(at + 1);
  }

  function buildChangeset() {
    var menu_items = [], booths = [];

    itemRows().forEach(function (row) {
      var key = rowKey(row);
      var e = state.edits.items[key] || {};
      var photo = photos[photoKey(row)];
      var gone = isDeleted(row);
      var isNew = !!row._id;
      if (!isNew && !Object.keys(e).length && !photo && !gone) return;

      var entry = { booth_name: row.booth, name: row.name };
      if (isNew) {
        // Nothing in the database to find, so the whole row travels rather
        // than a diff against it.
        entry.name = valueOf(row, 'name');
        entry['new'] = true;
        entry.category = valueOf(row, 'category') || 'food';
        // Only when tags were actually ticked. An empty list is not "no tags
        // yet" downstream - it is a curated statement that none apply, it
        // wins at priority_rank 0, and it *replaces* whatever the crawl
        // detected rather than adding to it. Exported blindly from the Add
        // form's empty default, it silently stripped the alcohol tag off four
        // drinks that plainly said Bourbon and Vodka in their own names.
        var newTags = valueOf(row, 'tags') || [];
        if (newTags.length) entry.dietary_tags = newTags;
        var newFlavours = valueOf(row, 'flavor_tags') || [];
        if (newFlavours.length) entry.flavor_tags = newFlavours;
        if (valueOf(row, 'alcohol_kind')) entry.alcohol_kind = valueOf(row, 'alcohol_kind');
        if (valueOf(row, 'is_new_this_year')) entry.is_new_this_year = true;
        // Only what was actually filled in. A null here is read downstream as
        // "this field should be empty", which is not what a blank Add form
        // means - it means nobody has said yet.
        var description = valueOf(row, 'description');
        if (description) entry.description = description;
        var price = valueOf(row, 'price');
        if (price !== null && price !== undefined && price !== '') entry.price_usd = price;
      } else {
        if (Object.prototype.hasOwnProperty.call(e, 'name')) entry.rename_to = e.name;
        if (Object.prototype.hasOwnProperty.call(e, 'description')) entry.description = e.description;
        if (Object.prototype.hasOwnProperty.call(e, 'price')) entry.price_usd = e.price;
        if (Object.prototype.hasOwnProperty.call(e, 'category')) entry.category = e.category;
        if (Object.prototype.hasOwnProperty.call(e, 'tags')) entry.dietary_tags = e.tags;
        if (Object.prototype.hasOwnProperty.call(e, 'flavor_tags')) entry.flavor_tags = e.flavor_tags;
        if (Object.prototype.hasOwnProperty.call(e, 'alcohol_kind')) entry.alcohol_kind = e.alcohol_kind;
        // Exported even when false: false is the whole point of touching this
        // one by hand - it is how a blog calling a returning dish new gets
        // taken back, and nothing but curation can say it.
        if (Object.prototype.hasOwnProperty.call(e, 'is_new_this_year')) {
          entry.is_new_this_year = !!e.is_new_this_year;
        }
      }
      if (Object.prototype.hasOwnProperty.call(e, 'image_url')) entry.image_url = e.image_url;
      if (photo) {
        entry.photo = { id: photoKey(row), mime: photo.mime, data_base64: stripDataPrefix(photo.dataUrl) };
      }
      if (gone) entry.is_active = false;
      menu_items.push(entry);
    });

    boothRows().forEach(function (row) {
      var key = rowKey(row);
      var e = state.edits.booths[key] || {};
      var placed = state.placements[row.name];
      var gone = isDeleted(row);
      var isNew = !!row._id;
      if (!isNew && !Object.keys(e).length && !placed && !gone) return;

      var entry = { name: isNew ? valueOf(row, 'name') : row.name };
      if (isNew) entry['new'] = true;
      if (placed) {
        entry.latitude = placed.latitude;
        entry.longitude = placed.longitude;
        entry.location_precision = 'mapped';
      }
      if (Object.prototype.hasOwnProperty.call(e, 'category')) entry.category = e.category;
      if (Object.prototype.hasOwnProperty.call(e, 'location_description')) {
        entry.location_description = e.location_description;
      }
      if (Object.prototype.hasOwnProperty.call(e, 'opens_at')) entry.opens_at = e.opens_at;
      if (gone) entry.is_active = false;
      booths.push(entry);
    });

    return { version: 1, generated_at: new Date().toISOString(), menu_items: menu_items, booths: booths };
  }

  function changesetFilename() {
    return 'epcot-changeset-' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.json';
  }

  var exportDialog = document.getElementById('export-dialog');
  var pendingName = null;

  document.getElementById('export').addEventListener('click', function () {
    if (!festivalEditable()) return;
    var changeset = buildChangeset();
    var photoCount = changeset.menu_items.filter(function (i) { return i.photo; }).length;
    var addedCount = changeset.menu_items.filter(function (i) { return i['new']; }).length +
                     changeset.booths.filter(function (b) { return b['new']; }).length;
    var pinCount = changeset.booths.filter(function (b) { return b.latitude !== undefined; }).length;
    var deletedCount = changeset.menu_items.filter(function (i) { return i.is_active === false; }).length +
                       changeset.booths.filter(function (b) { return b.is_active === false; }).length;

    var rowsHtml = [
      ['Dishes changed', changeset.menu_items.length],
      ['Booths changed', changeset.booths.length],
      ['Photos attached', photoCount],
      ['Pins dropped', pinCount],
      ['Added by hand', addedCount],
      ['Marked deleted', deletedCount]
    ].map(function (pair) {
      return '<li><span>' + pair[0] + '</span><b>' + pair[1] + '</b></li>';
    }).join('');
    document.getElementById('export-summary').innerHTML = rowsHtml;

    pendingName = changesetFilename();
    document.getElementById('export-cmd').textContent = 'epcot-fw studio apply ~/Downloads/' + pendingName;
    if (exportDialog.showModal) exportDialog.showModal(); else exportDialog.setAttribute('open', '');
  });

  document.getElementById('export-download').addEventListener('click', function () {
    var blob = new Blob([JSON.stringify(buildChangeset(), null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = pendingName || changesetFilename();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  });

  document.getElementById('export-close').addEventListener('click', function () {
    if (exportDialog.close) exportDialog.close(); else exportDialog.removeAttribute('open');
  });

  document.getElementById('discard').addEventListener('click', function () {
    closeMenu();
    if (!changeCount()) return;
    ask({
      title: 'Discard all changes?',
      message: 'Every edit, pin and attached photo on this device goes. This cannot be undone.',
      okLabel: 'Discard all',
    }).then(function (yes) {
      if (!yes) return;
      state.edits = { items: {}, booths: {} };
      state.placements = {};
      state.added = { items: [], booths: [] };
      state.deleted = { items: {}, booths: {} };
      save();
      dropAllPhotos().then(render);
    });
  });

  // ---------- adding by hand ----------
  var addDialog = document.getElementById('add-dialog');
  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    // Only reached on an older browser; good enough to name a file by and to
    // tell two rows typed in the same session apart.
    return 'x' + Date.now().toString(16) + Math.random().toString(16).slice(2, 10);
  }

  // What is being added is now a property of which button was pressed rather
  // than of which tab happened to be open.
  var addingDish = true;
  function openAddDialog(dish) {
    addingDish = dish;
    document.getElementById('add-item-fields').classList.toggle('hidden', !dish);
    document.getElementById('add-booth-fields').classList.toggle('hidden', dish);
    document.getElementById('add-error').classList.add('hidden');
    // The booth whose menu is open is overwhelmingly the one being added to.
    if (dish && state.selected) document.getElementById('add-booth').value = state.selected;
    if (addDialog.showModal) addDialog.showModal(); else addDialog.setAttribute('open', '');
    (dish ? document.getElementById('add-name') : document.getElementById('add-booth-name')).focus();
  }
  document.getElementById('add-dish-btn').addEventListener('click', function () { openAddDialog(true); });
  document.getElementById('add-booth-btn').addEventListener('click', function () { openAddDialog(false); });
  document.getElementById('add-cancel').addEventListener('click', function () {
    if (addDialog.close) addDialog.close(); else addDialog.removeAttribute('open');
  });

  document.getElementById('add-confirm').addEventListener('click', function () {
    var err = document.getElementById('add-error');
    if (addingDish) {
      var name = document.getElementById('add-name').value.trim();
      var booth = document.getElementById('add-booth').value;
      if (!name || !booth) {
        err.textContent = 'A dish needs a name and a booth — a dish name on its own cannot be matched to anything.';
        err.classList.remove('hidden');
        return;
      }
      var price = document.getElementById('add-price').value;
      state.added.items.push({
        _id: newId(), booth: booth, name: name, origin: 'curated',
        description: document.getElementById('add-desc').value.trim() || null,
        price: price === '' ? null : Number(price),
        category: document.getElementById('add-cat').value,
        tags: [], image_url: null, image: null
      });
      document.getElementById('add-name').value = '';
      document.getElementById('add-desc').value = '';
      document.getElementById('add-price').value = '';
    } else {
      var boothName = document.getElementById('add-booth-name').value.trim();
      if (!boothName) {
        err.textContent = 'A booth needs a name.';
        err.classList.remove('hidden');
        return;
      }
      state.added.booths.push({
        _id: newId(), name: boothName, origin: 'curated',
        category: null, item_count: 0,
        location_description: document.getElementById('add-booth-loc').value.trim() || null,
        latitude: null, longitude: null, location_precision: null
      });
      document.getElementById('add-booth-name').value = '';
      document.getElementById('add-booth-loc').value = '';
      refreshBoothOptions();
      // Nothing is in it yet and the next thing anyone does is add its first
      // dish, so open it rather than leaving it to be hunted for in the rail.
      state.selected = boothName;
    }
    save();
    if (addDialog.close) addDialog.close(); else addDialog.removeAttribute('open');
    render();
  });

  // ---------- controls ----------
  function refreshBoothOptions() {
    var picker = document.getElementById('add-booth');
    picker.innerHTML = '';
    boothRows().forEach(function (b) {
      var o = document.createElement('option');
      o.value = b.name;
      o.textContent = b.name;
      picker.appendChild(o);
    });
  }

  function chip(id, key) {
    var btn = document.getElementById(id);
    btn.addEventListener('click', function () {
      state[key] = !state[key];
      btn.classList.toggle('active', state[key]);
      render();
    });
  }
  chip('chip-nophoto', 'noPhotoOnly');
  chip('chip-new', 'newOnly');
  chip('chip-unplaced', 'unplacedOnly');
  chip('chip-edited', 'editedOnly');
  chip('chip-added', 'addedOnly');

  document.getElementById('back-to-booths').addEventListener('click', function () { select(null); });

  document.getElementById('map-btn').addEventListener('click', function () {
    if (festivalEditable()) openDrawer(null);
  });

  var menuBtn = document.getElementById('menu-btn');
  var menuList = document.getElementById('menu-list');
  function closeMenu() {
    menuList.classList.add('hidden');
    menuBtn.setAttribute('aria-expanded', 'false');
  }
  menuBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    var open = menuList.classList.toggle('hidden') === false;
    menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('click', function (e) {
    if (!menuList.contains(e.target)) closeMenu();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });

  var helpDialog = document.getElementById('help-dialog');
  document.getElementById('help-btn').addEventListener('click', function () {
    closeMenu();
    if (helpDialog.showModal) helpDialog.showModal(); else helpDialog.setAttribute('open', '');
  });
  document.getElementById('help-close').addEventListener('click', function () {
    if (helpDialog.close) helpDialog.close(); else helpDialog.removeAttribute('open');
  });
  document.getElementById('settled-dismiss').addEventListener('click', function () {
    document.getElementById('settled-line').classList.add('hidden');
  });
  document.getElementById('filter-cat').addEventListener('change', function (e) {
    state.category = e.target.value;
    renderDetail();
    renderCounts();
  });
  document.getElementById('booth-search').addEventListener('input', function (e) {
    state.boothQ = e.target.value.trim().toLowerCase();
    renderRail();
  });
  document.getElementById('dish-search').addEventListener('input', function (e) {
    state.dishQ = e.target.value.trim().toLowerCase();
    renderDetail();
    renderCounts();
  });

  // ---------- boot ----------
  var addCat = document.getElementById('add-cat');
  CATEGORIES.forEach(function (c) {
    var o = document.createElement('option');
    o.value = c;
    o.textContent = c.replace(/_/g, ' ');
    addCat.appendChild(o);
  });

  load();
  refreshBoothOptions();
  loadPhotos().then(settle).then(render, render);

  // ---------- as an installed app ----------
  // Chrome offers to install a page that has a manifest and a service
  // worker; this is the worker (assets/studio-sw.js), scoped to the Studio's
  // own files. It fetches the network first, so the app always opens on the
  // latest build and only falls back to its last copy when the server
  // cannot be reached. Not on file://, where service workers do not exist.
  if ('serviceWorker' in navigator && location.protocol !== 'file:') {
    navigator.serviceWorker.register('studio-sw.js', { scope: './studio' }).catch(function () {});
  }

  // Chrome's own install icon sits in the address bar, which an app window
  // does not have; the menu item is the same prompt from inside the page.
  var installPrompt = null;
  var installBtn = document.getElementById('install-btn');
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    installPrompt = e;
    installBtn.classList.remove('hidden');
  });
  window.addEventListener('appinstalled', function () {
    installPrompt = null;
    installBtn.classList.add('hidden');
  });
  installBtn.addEventListener('click', function () {
    closeMenu();
    if (!installPrompt) return;
    installPrompt.prompt();
    installPrompt.userChoice.then(function () {
      installPrompt = null;
      installBtn.classList.add('hidden');
    });
  });

  // An app window stays open for days, so a rebuild has to announce itself
  // rather than wait for a reload nobody thinks to do. The server's ETag or
  // Last-Modified for studio.html is the version: taken once on load, then
  // compared whenever the window comes back into focus and every few
  // minutes. Edits are saved as they are made, so Reload loses nothing.
  var loadedVersion = null;
  function serverVersion() {
    return fetch('studio.html', { method: 'HEAD', cache: 'no-store' })
      .then(function (r) { return r.ok ? (r.headers.get('etag') || r.headers.get('last-modified')) : null; })
      .catch(function () { return null; });
  }
  function checkForUpdate() {
    if (location.protocol === 'file:') return;
    serverVersion().then(function (v) {
      if (!v) return;
      if (loadedVersion === null) { loadedVersion = v; return; }
      if (v !== loadedVersion) document.getElementById('update-line').classList.remove('hidden');
    });
  }
  checkForUpdate();
  window.addEventListener('focus', checkForUpdate);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) checkForUpdate(); });
  setInterval(checkForUpdate, 5 * 60 * 1000);
  document.getElementById('update-reload').addEventListener('click', function () { location.reload(); });
})();
</script>
</body>
</html>
"""


def render(snapshot: dict[str, Any], *, generated_at: str = "") -> str:
    """Snapshot in, complete self-contained page out."""
    rows = studio_rows(snapshot)
    # `</` is broken up because the blob sits inside a <script> element, where
    # the HTML parser ends the element at the first `</script>` regardless of
    # what the JSON quoting thinks.
    payload = json.dumps(rows, default=str).replace("</", "<\\/")
    return (
        TEMPLATE.replace("__CATEGORIES__", json.dumps(list(CATEGORIES)))
        .replace("__TAGS__", json.dumps(list(TAGS)))
        .replace("__FLAVOUR_TAGS__", json.dumps(list(FLAVOUR_TAGS)))
        .replace("__ALCOHOL_KINDS__", json.dumps(list(ALCOHOL_KINDS)))
        .replace("__FESTIVALS__", json.dumps(festival_catalog(snapshot)).replace("</", "<\\/"))
        .replace("__CENTER_JSON__", json.dumps(DEFAULT_CENTER))
        .replace("__ZOOM__", str(DEFAULT_ZOOM))
        .replace("__AGGREGATE_BOOTH_NAME__", json.dumps(AGGREGATE_BOOTH_NAME))
        .replace("__GENERATED_AT__", generated_at or "")
        .replace("__DATA_JSON__", payload)
    )
