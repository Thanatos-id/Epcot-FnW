"""Renders docs/studio.html - one page for correcting the database.

Replaces docs/editor.html and docs/map.html, which split one job in half.
Correcting a dish used to mean opening the editor, opening the map, and
hand-merging two paste blocks into two curated files; and neither page could
do the two things most often wanted - attach a photo you took yourself, and
add a dish the crawl never found.

The page is master/detail: a 450px rail of booths on the left, and the whole
of one booth on the right - its own editable fields, where it sits, and every
dish on its menu. A booth is the unit a person actually works in. 209 dishes
in one flat column was a list nobody could hold in their head, and a dish is
only ever judged against the others on the same menu anyway; scoping to a
booth also means its coordinate is stated once, at the top, instead of
repeated on every row that inherits it.

What this adds over the two pages it replaces:

  * every dish shows its photo, or an explicit empty state, and a photo can
    be attached from the camera roll on the spot;
  * a booth is placed on the map from the same pane as its menu, so nothing
    is lost by going to look;
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
)

# World Showcase's rough centre - every booth sits within a few hundred
# metres of it, so it is a fine default view regardless of what is placed.
DEFAULT_CENTER = [28.3689, -81.5493]
DEFAULT_ZOOM = 18

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light dark" />
<meta name="description" content="Curation studio for the crawled Epcot Food &amp; Wine Festival database - correct a dish, attach a photo, place a booth on the map, or add what the crawl missed, and export the result as curated overrides." />
<title>Studio — Epcot Food &amp; Wine</title>

<link rel="manifest" href="manifest.json" />
<link rel="icon" href="icons/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="icons/icon.svg" />
<link rel="apple-touch-icon" sizes="180x180" href="icons/apple-touch-icon.png" />
<meta name="apple-mobile-web-app-title" content="Studio" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="theme-color" content="#efe8d8" media="(prefers-color-scheme: light)" />
<meta name="theme-color" content="#1b1510" media="(prefers-color-scheme: dark)" />

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
<style>
:root {
  --bg: #efe8d8; --surface: #fbf7ee; --surface-2: #f3ebd8; --ink: #241c16;
  --ink-muted: #6b5d4f; --accent: #7a2036; --accent-soft: #f0dce0; --gold: #a9752b;
  --gold-soft: #f1e2c4; --border: #ddd0b5; --good: #4f7a45; --good-soft: #e1ebdb;
  --warn: #bb5a2c; --warn-soft: #f3e1d2;
  --shadow: 0 1px 2px rgba(36,28,22,0.06), 0 8px 24px rgba(36,28,22,0.06);
  /* What the pinned panes are inset by: a little air at the top, and enough
     at the bottom to clear the fixed export bar (40px of button plus its
     padding) whatever the theme does to it. */
  --shell-top: 12px;
  --shell-bottom: 88px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #1b1510; --surface: #241d16; --surface-2: #2c231a; --ink: #f3ecdd;
    --ink-muted: #b8aa93; --accent: #e0899c; --accent-soft: #3a2029; --gold: #d9a24b;
    --gold-soft: #3a2e18; --border: #3a2f23; --good: #8fc97f; --good-soft: #24301f;
    --warn: #e0935c; --warn-soft: #3a2618;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }
}
:root[data-theme="dark"] {
  --bg: #1b1510; --surface: #241d16; --surface-2: #2c231a; --ink: #f3ecdd;
  --ink-muted: #b8aa93; --accent: #e0899c; --accent-soft: #3a2029; --gold: #d9a24b;
  --gold-soft: #3a2e18; --border: #3a2f23; --good: #8fc97f; --good-soft: #24301f;
  --warn: #e0935c; --warn-soft: #3a2618;
  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.5; -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}
.wrap { max-width: 1500px; margin: 0 auto; padding: clamp(18px, 4vw, 34px) clamp(12px, 3vw, 22px) 130px; }
.display { font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif; }
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; }

.eyebrow {
  display: inline-flex; align-items: center; gap: 8px; font-size: 11px;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent);
  font-weight: 600; margin-bottom: 10px;
}
.eyebrow::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
h1 { font-size: clamp(22px, 5vw, 31px); margin: 0 0 8px; font-weight: 600; letter-spacing: -0.01em; }
.subtitle { color: var(--ink-muted); font-size: 14.5px; max-width: 74ch; }
.subtitle a, .panel a { color: var(--accent); }

.panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  box-shadow: var(--shadow); padding: 13px 15px; margin: 16px 0;
  font-size: 13.5px; color: var(--ink-muted);
}
.panel b { color: var(--ink); }
.panel.note { background: var(--surface-2); }
.panel.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
.panel.armed { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); font-weight: 600; }

/* ---------- toolbar ---------- */
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 18px 0 10px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
input[type="search"], select, input[type="text"], input[type="number"], textarea {
  font: inherit; font-size: 14px; color: var(--ink); background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 11px;
}
input[type="search"] { flex: 1 1 220px; min-width: 0; }
/* A <select> is sized by its widest option unless told otherwise, and the
   booth list holds "Additional Festival Locations". Left alone that pushes
   the toolbar past a 320px viewport. */
select { max-width: 100%; }
.toolbar select { flex: 1 1 150px; min-width: 0; }
input[type="search"]:focus, select:focus, textarea:focus, .cell-input:focus, input:focus {
  outline: 2px solid var(--accent); outline-offset: -1px;
}
button {
  font: inherit; font-size: 14px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); padding: 8px 13px; cursor: pointer;
  min-height: 40px;
}
button:disabled { opacity: 0.5; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
button.tab.active, button.chip.active {
  background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 600;
}
button.chip { min-height: 34px; padding: 5px 11px; font-size: 12.5px; }
button.small { min-height: 32px; padding: 4px 10px; font-size: 12.5px; }
.spacer { flex: 1 1 auto; }
.count { font-size: 13px; color: var(--ink-muted); white-space: nowrap; }

/* ---------- map ---------- */
.tallies { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 8px; }
.tally {
  background: var(--surface); border: 1px solid var(--border); border-radius: 20px;
  padding: 5px 12px; font-size: 12.5px; color: var(--ink-muted);
}
.tally b { color: var(--ink); font-family: ui-monospace, Menlo, monospace; }
#map {
  width: 100%; height: min(52vh, 460px); border-radius: 10px; border: 1px solid var(--border);
  box-shadow: var(--shadow); margin: 12px 0; background: var(--surface-2);
}
#map.armed, #map.armed .leaflet-container { cursor: crosshair; }
.leaflet-control-layers, .leaflet-bar a { background: var(--surface) !important; color: var(--ink) !important; border-color: var(--border) !important; }
.leaflet-control-attribution { background: rgba(255,255,255,0.75) !important; font-size: 10px; }
.booth-pin span { display: block; width: 16px; height: 16px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.5); }
.leaflet-tooltip.booth-tooltip {
  background: var(--surface); color: var(--ink); border: 1px solid var(--border);
  border-radius: 6px; font-size: 12px; font-weight: 600; padding: 2px 7px; box-shadow: var(--shadow);
}
.leaflet-tooltip.booth-tooltip::before { display: none; }

/* ---------- master / detail ----------

   The booth list is the way in: 32 booths against 209 dishes, and a dish is
   only ever understood next to the others on the same menu. 450px is enough
   for the longest booth name plus its pills without letting the rail eat the
   half of the screen the dishes need.

   Below RAIL_BREAKPOINT the two panes cannot sit side by side, so they take
   turns: the rail until a booth is picked, the detail (with a way back)
   after. `.picked` on the layout is what switches them. */
.layout { display: grid; grid-template-columns: 450px minmax(0, 1fr); gap: 18px; align-items: start; }
.rail, .detail { min-width: 0; }

.rail-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.rail-head h2 { font-size: 18px; margin: 0; font-weight: 600; }
.rail-controls { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.rail-controls input[type="search"] { width: 100%; flex: none; }
.booth-list { display: flex; flex-direction: column; gap: 6px; }

.booth-item {
  width: 100%; text-align: left; display: block; cursor: pointer; flex: none;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 12px; min-height: 0; font: inherit; color: var(--ink);
}
.booth-item:hover { border-color: var(--accent); }
.booth-item.selected { background: var(--accent-soft); border-color: var(--accent); }
.booth-item.edited { box-shadow: inset 3px 0 0 var(--gold); }
.booth-item.deleted { opacity: 0.55; }
.booth-item-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.booth-item-name { font-weight: 600; font-size: 14.5px; overflow-wrap: anywhere; min-width: 0; }
.booth-item-meta { color: var(--ink-muted); font-size: 12px; margin-top: 3px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.booth-item.selected .booth-item-meta { color: var(--accent); }

.detail-empty { padding: clamp(28px, 7vw, 56px) 22px; text-align: center; }
.detail-empty h2 { font-size: 19px; margin: 0 0 8px; color: var(--ink); font-weight: 600; }
.detail-empty p { margin: 0 auto; max-width: 46ch; }
.back-to-booths { display: none; margin-bottom: 12px; }

/* Each pane scrolls on its own.

   Two lists of very different lengths share this screen - 32 booths against
   a menu that runs to 21 dishes - and on one page scroll the rail runs out
   long before the menu does, so working down a long menu means losing the
   booth you are in. Pinning both and giving each its own scroller keeps the
   list you are choosing from next to the list you are working through.

   `max-height` rather than `height`: a short menu keeps its natural size
   instead of a card floating in an empty viewport-tall box, and leaving the
   pane shorter than its container is also what gives `sticky` something to
   travel through. The bottom reserve clears the fixed export bar.

   Only above the breakpoint where the two panes are side by side. Below it
   they take turns, and a touch device should scroll the way every other
   page does rather than trapping a finger in a nested scroller. */
@media (min-width: 901px) {
  /* The 130px reserve exists to keep the last card clear of the fixed export
     bar while the page scrolls as one. Pinned panes clear it themselves via
     --shell-bottom, and leaving the reserve in would give the page more
     scroll range than the header can absorb - which is scroll range spent
     dragging both panes off the top of the screen. */
  .wrap { padding-bottom: 24px; }
  .rail, .detail {
    position: sticky;
    top: var(--shell-top);
    max-height: calc(100vh - var(--shell-top) - var(--shell-bottom));
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .rail-head, .rail-controls, #booth-detail, .detail .toolbar, .detail-empty { flex: none; }
  #detail-body { display: flex; flex-direction: column; min-height: 0; flex: 1 1 auto; }
  .booth-list, .rows {
    overflow-y: auto;
    /* Reaching the end of a menu should stop, not start scrolling the page
       out from under it. */
    overscroll-behavior: contain;
    scrollbar-gutter: stable;
    flex: 1 1 auto;
    min-height: 0;
    /* Room for the scrollbar and for the cards' focus outline and inset
       edited marker, which a flush overflow edge would clip. */
    padding: 2px 4px 2px 3px;
  }
}

@media (max-width: 900px) {
  .layout { grid-template-columns: minmax(0, 1fr); }
  .layout.picked .rail { display: none; }
  .layout:not(.picked) .detail { display: none; }
  .back-to-booths { display: inline-flex; }
}

/* ---------- rows ---------- */
.rows { display: flex; flex-direction: column; gap: 10px; }
.row {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  box-shadow: var(--shadow); padding: 12px; display: grid; gap: 12px;
  grid-template-columns: 132px minmax(0, 1fr);
  /* Both lists are flex columns, and a flex column with a bounded height
     shrinks its items to fit rather than overflowing. Once these panes
     scroll, that is every card squashed to a sliver instead of a scrollbar. */
  flex: none;
}
@media (max-width: 560px) { .row { grid-template-columns: 96px minmax(0, 1fr); } }
.row.edited { border-color: var(--gold); box-shadow: inset 3px 0 0 var(--gold), var(--shadow); }
.row.added { border-color: var(--accent); }
.row.deleted { opacity: 0.55; }
.row.booth-row { grid-template-columns: minmax(0, 1fr); margin-bottom: 4px; }
.row.booth-row h2 { font-size: 20px; margin: 0; font-weight: 600; overflow-wrap: anywhere; }

.thumb {
  width: 100%; aspect-ratio: 4 / 3; border-radius: 8px; overflow: hidden;
  background: var(--surface-2); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center; position: relative;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb.empty { border-style: dashed; }
.thumb-empty-label {
  color: var(--ink-muted); font-size: 11px; letter-spacing: 0.04em;
  text-transform: uppercase; text-align: center; padding: 4px;
}
.thumb .badge {
  position: absolute; top: 5px; left: 5px; font-size: 9.5px; font-weight: 700;
  letter-spacing: 0.04em; text-transform: uppercase; padding: 2px 6px; border-radius: 20px;
  background: var(--gold-soft); color: var(--gold); border: 1px solid var(--gold);
}
.photo-actions { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.photo-actions button { min-height: 28px; padding: 3px 8px; font-size: 11.5px; }
input[type="file"] { display: none; }

.fields { display: grid; gap: 8px; min-width: 0; }
.field-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.field-row > .grow { flex: 1 1 200px; min-width: 0; }
.row-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.booth-name { color: var(--ink-muted); font-size: 12.5px; font-weight: 600; }
.pill {
  font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 20px; white-space: nowrap;
}
.pill.surveyed { background: var(--good-soft); color: var(--good); }
.pill.mapped { background: var(--accent-soft); color: var(--accent); }
.pill.anchored { background: var(--gold-soft); color: var(--gold); }
.pill.unplaced { background: var(--surface-2); color: var(--ink-muted); }
.pill.curated { background: var(--accent-soft); color: var(--accent); }
.geo { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: var(--ink-muted); }

.cell-input {
  font: inherit; font-size: 13.5px; width: 100%; color: var(--ink);
  background: transparent; border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 8px; resize: vertical;
}
.cell-input.changed { background: var(--gold-soft); border-color: var(--gold); }
textarea.cell-input { min-height: 40px; line-height: 1.4; }
input.price { flex: 0 0 108px; width: 108px; }
select.cell-input { width: auto; max-width: 100%; }

.tag-cell { cursor: pointer; min-height: 28px; }
.tag-summary { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.tag-none { color: var(--ink-muted); font-size: 12px; font-style: italic; }
.tag-edit { color: var(--ink-muted); font-size: 11px; margin-left: 2px; text-decoration: underline; }
.tag-picker { display: flex; flex-wrap: wrap; gap: 4px; }
.tag-toggle {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.02em;
  padding: 3px 8px; border-radius: 20px; cursor: pointer;
  border: 1px solid var(--border); background: transparent; color: var(--ink-muted); min-height: 0;
}
.tag-toggle.on { background: var(--gold-soft); border-color: var(--gold); color: var(--gold); }
.tag-toggle.changed { outline: 1px dashed var(--gold); outline-offset: 1px; }
.linkish, .tag-done {
  border: none; background: transparent; color: var(--accent); cursor: pointer;
  font-size: 12px; padding: 4px 2px; min-height: 0; text-decoration: underline;
}
.empty-state { padding: 34px 16px; text-align: center; color: var(--ink-muted); }

/* ---------- drawers ---------- */
.sticky {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000;
  background: var(--surface); border-top: 1px solid var(--border);
  padding: 10px clamp(12px, 3vw, 22px) calc(10px + env(safe-area-inset-bottom));
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  box-shadow: 0 -4px 20px rgba(0,0,0,0.07);
}
.sticky .count b { color: var(--accent); }
dialog {
  border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  color: var(--ink); max-width: min(680px, 92vw); width: 100%; padding: 0;
  box-shadow: 0 12px 48px rgba(0,0,0,0.3);
}
dialog::backdrop { background: rgba(20,14,10,0.5); }
.dialog-body { padding: 18px 20px 20px; }
.dialog-body h2 { margin: 0 0 6px; font-size: 19px; }
.dialog-body p { margin: 0 0 12px; font-size: 13.5px; color: var(--ink-muted); }
.dialog-body code { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; }
.dialog-body label { display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-muted); margin: 10px 0 3px; font-weight: 700; }
.dialog-body input[type="text"], .dialog-body input[type="number"], .dialog-body select, .dialog-body textarea { width: 100%; }
.dialog-actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-top: 16px; }
.summary { list-style: none; padding: 0; margin: 0 0 14px; font-size: 13.5px; }
.summary li { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid var(--border); }
.summary b { font-family: ui-monospace, Menlo, monospace; }
pre.cmd {
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px; font-size: 12px; overflow-x: auto; margin: 0;
}
footer { margin-top: 26px; color: var(--ink-muted); font-size: 12.5px; }
footer a { color: var(--accent); }
.hidden { display: none !important; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">Curation studio</div>
    <h1 class="display">Studio</h1>
    <p class="subtitle">
      Pick a booth on the left and its whole menu opens on the right, each dish with its photo,
      editable in place. Correct what's wrong, attach a photo, place a booth on the map, or add
      what the crawl missed — then <b>Export</b> a changeset and apply it.
      <a href="index.html">Back to the ledger</a> · <a href="survey.html">In-park GPS survey →</a>
    </p>
  </header>

  <div class="panel">
    <b>Nothing here writes to the database.</b> Edits and photos live in this browser until you
    export them, so you can work through the list across several sittings. Export downloads one
    changeset file; <code>epcot-fw studio apply</code> reads it back, publishes the photos and
    merges the rest into the curated files that override the crawl. A dish's <b>name</b> is how a
    correction finds it again, so renaming one is recorded as a rename — both names go into the
    export.
  </div>

  <div class="panel warn hidden" id="storage-note"></div>

  <section id="map-panel" class="hidden">
    <div class="panel warn hidden" id="offline-note">
      Map tiles need an internet connection — this part of the page isn't usable offline the way
      the survey tool is.
    </div>
    <div class="panel note" id="armed-banner">
      Hit <b>Place on map</b> on a booth to start, then click its spot on the map.
    </div>
    <div id="map"></div>
    <div class="tallies" id="tallies"></div>
  </section>

  <div class="layout" id="layout">
    <aside class="rail">
      <div class="rail-head">
        <h2 class="display">Booths</h2>
        <span class="count" id="booth-count"></span>
      </div>
      <div class="rail-controls">
        <input type="search" id="booth-search" placeholder="Filter booths…" autocomplete="off" />
        <div class="chips" style="margin: 0;">
          <button type="button" class="chip" id="chip-unplaced">Not placed</button>
          <button type="button" class="chip" id="chip-edited">Edited</button>
          <button type="button" class="chip" id="chip-added">Added by hand</button>
        </div>
        <div class="chips" style="margin: 0;">
          <button type="button" class="chip" id="toggle-map">Show map</button>
          <button type="button" class="chip" id="add-booth-btn">+ Add booth</button>
        </div>
      </div>
      <div class="booth-list" id="booth-list"></div>
    </aside>

    <section class="detail" id="detail">
      <div class="panel detail-empty" id="detail-empty">
        <h2 class="display">Select a booth</h2>
        <p>
          Everything that lives inside it opens here — every dish on its menu with its photo or
          an empty state, its price, description and dietary tags, and where the booth sits on
          the Epcot map.
        </p>
      </div>

      <div id="detail-body" class="hidden">
        <button type="button" class="chip back-to-booths" id="back-to-booths">← All booths</button>
        <div id="booth-detail"></div>
        <div class="toolbar">
          <input type="search" id="dish-search" placeholder="Search this menu…" autocomplete="off" />
          <select id="filter-cat">
            <option value="">All categories</option>
            <option value="food">Food</option>
            <option value="alcoholic_beverage">Alcoholic</option>
            <option value="non_alcoholic_beverage">Non-alcoholic</option>
          </select>
          <button type="button" class="chip" id="chip-nophoto">Needs a photo</button>
          <button type="button" class="chip" id="add-dish-btn">+ Add dish</button>
          <span class="spacer"></span>
          <span class="count" id="dish-count"></span>
        </div>
        <div class="rows" id="dish-list"></div>
      </div>
    </section>
  </div>

  <footer>
    Snapshot built __GENERATED_AT__ · Prices are US dollars; a blank price means no source has
    published one. Pins dropped here stage as <code class="mono">location_precision: "mapped"</code> —
    better than a pavilion-anchor stand-in, not as good as a GPS fix taken standing at the booth.
  </footer>
</div>

<div class="sticky">
  <span class="count" id="edit-count"></span>
  <span class="spacer"></span>
  <button type="button" id="discard">Discard all</button>
  <button type="button" class="primary" id="export" disabled>Export changeset</button>
</div>

<dialog id="add-dialog">
  <form class="dialog-body" id="add-form" method="dialog">
    <h2 class="display">Add by hand</h2>
    <p>
      For something the crawl never found. It comes back as
      <code>origin: "curated"</code>, which is what stops the next crawl retiring it — and what
      the <b>Added by hand</b> filter finds when you want to change or delete it later.
    </p>
    <div id="add-item-fields">
      <label for="add-booth">Booth</label>
      <select id="add-booth"></select>
      <label for="add-name">Dish name</label>
      <input type="text" id="add-name" autocomplete="off" />
      <label for="add-desc">Description</label>
      <textarea id="add-desc" rows="2"></textarea>
      <label for="add-price">Price (USD)</label>
      <input type="number" id="add-price" step="0.01" min="0" />
      <label for="add-cat">Category</label>
      <select id="add-cat"></select>
    </div>
    <div id="add-booth-fields" class="hidden">
      <label for="add-booth-name">Booth name</label>
      <input type="text" id="add-booth-name" autocomplete="off" />
      <label for="add-booth-loc">Location description</label>
      <input type="text" id="add-booth-loc" autocomplete="off" />
      <p style="margin-top:10px">Place it on the map once it's added.</p>
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
    <h2 class="display">Export</h2>
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

<script id="studio-data" type="application/json">__DATA_JSON__</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById('studio-data').textContent);
  var CATEGORIES = __CATEGORIES__;
  var TAGS = __TAGS__;
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
    expandedTags: null,
    armed: null,
    mapOpen: false
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
        selected: state.selected
      }));
    } catch (e) {
      warn('This browser refused to save your edits — they will be lost on reload. Export before you close the tab.');
    }
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
    var url = prompt('Image URL for this dish:', valueOf(row, 'image_url') || '');
    if (url === null) return;
    url = url.trim();
    dropPhoto(photoKey(row)).then(function () {
      setValue(row, 'image_url', url || null);
      render();
    });
  }

  // ---------- map ----------
  // A dropped pin beats whatever the database already had for that booth.
  function positionOf(booth) {
    if (!booth) return null;
    var p = state.placements[booth.name];
    if (p) return { lat: p.latitude, lon: p.longitude, precision: 'mapped' };
    var lat = booth.latitude;
    if (lat === null || lat === undefined) return null;
    return { lat: Number(lat), lon: Number(booth.longitude), precision: booth.location_precision || 'anchored' };
  }

  var PIN_COLOR = { mapped: 'var(--accent)', anchored: 'var(--gold)', surveyed: 'var(--good)' };
  function pinIcon(precision) {
    return L.divIcon({
      className: 'booth-pin',
      html: '<span style="background:' + (PIN_COLOR[precision] || 'var(--ink-muted)') + '"></span>',
      iconSize: [16, 16], iconAnchor: [8, 8]
    });
  }

  var haveLeaflet = typeof L !== 'undefined';
  var map = null, markers = {};

  function initMap() {
    if (map || !haveLeaflet) return;
    map = L.map('map').setView(CENTER, ZOOM);
    var sat = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 20, maxNativeZoom: 19, attribution: 'Tiles &copy; Esri' }
    );
    var streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    });
    sat.addTo(map);
    L.control.layers({ Satellite: sat, Streets: streets }).addTo(map);

    map.on('click', function (e) {
      if (!state.armed) return;
      state.placements[state.armed] = {
        latitude: Number(e.latlng.lat.toFixed(6)),
        longitude: Number(e.latlng.lng.toFixed(6)),
        placed_at: new Date().toISOString()
      };
      state.armed = null;
      save();
      render();
    });
  }

  // One marker per placed booth, created once then moved in place, so
  // dragging and re-renders don't fight each other.
  function syncMarkers() {
    if (!map) return;
    boothRows().forEach(function (booth) {
      var pos = isDeleted(booth) ? null : positionOf(booth);
      var existing = markers[booth.name];
      if (!pos) {
        if (existing) { map.removeLayer(existing); delete markers[booth.name]; }
        return;
      }
      var draggable = !!state.placements[booth.name];
      if (existing) {
        existing.setLatLng([pos.lat, pos.lon]);
        existing.setIcon(pinIcon(pos.precision));
        if (existing.dragging) { draggable ? existing.dragging.enable() : existing.dragging.disable(); }
        return;
      }
      var marker = L.marker([pos.lat, pos.lon], { icon: pinIcon(pos.precision), draggable: draggable });
      marker.bindTooltip(booth.name, { permanent: true, direction: 'top', offset: [0, -8], className: 'booth-tooltip' });
      marker.on('dragend', function () {
        var ll = marker.getLatLng();
        state.placements[booth.name] = {
          latitude: Number(ll.lat.toFixed(6)),
          longitude: Number(ll.lng.toFixed(6)),
          placed_at: new Date().toISOString()
        };
        save();
        render();
      });
      marker.addTo(map);
      markers[booth.name] = marker;
    });
  }

  function openMap() {
    state.mapOpen = true;
    document.getElementById('map-panel').classList.remove('hidden');
    document.getElementById('toggle-map').classList.add('active');
    document.getElementById('toggle-map').textContent = 'Hide map';
    if (!haveLeaflet) {
      document.getElementById('offline-note').classList.remove('hidden');
      return;
    }
    initMap();
    // Leaflet measures the container on creation; one built inside a hidden
    // panel comes out a single grey tile until it is told to look again.
    setTimeout(function () { if (map) map.invalidateSize(); }, 0);
    syncMarkers();
  }
  function closeMap() {
    state.mapOpen = false;
    document.getElementById('map-panel').classList.add('hidden');
    document.getElementById('toggle-map').classList.remove('active');
    document.getElementById('toggle-map').textContent = 'Show map';
  }

  function arm(name) {
    state.armed = (state.armed === name) ? null : name;
    if (state.armed) {
      openMap();
      document.getElementById('map-panel').scrollIntoView({ block: 'start' });
    }
    render();
  }

  function centerOn(booth) {
    var pos = positionOf(booth);
    if (!map || !pos) return;
    openMap();
    map.setView([pos.lat, pos.lon], Math.max(map.getZoom(), 19));
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && state.armed) { state.armed = null; render(); }
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
    dishList.scrollTop = 0;
    if (name) document.getElementById('detail').scrollIntoView({ block: 'nearest' });
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
      if (!current.length) {
        var none = document.createElement('span');
        none.className = 'tag-none';
        none.textContent = 'no tags';
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
    actions.appendChild(button(img ? 'Replace' : 'Add photo', 'small', function () { picker.click(); }));
    actions.appendChild(button('URL', 'small', function () { useUrl(row); }));
    if (img) actions.appendChild(button('Clear', 'small', function () { clearPhoto(row); }));
    col.appendChild(actions);
    return col;
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
    if (isAdded(row)) {
      var head = document.createElement('div');
      head.className = 'row-head';
      var pill = document.createElement('span');
      pill.className = 'pill curated';
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

    fields.appendChild(makeTagCell(row));

    var actions = document.createElement('div');
    actions.className = 'field-row';
    if (isRowChanged(row) && !row._id) actions.appendChild(button('Revert', 'linkish', function () { revert(row); }));
    if (isAdded(row)) {
      actions.appendChild(isDeleted(row)
        ? button('Undo delete', 'linkish', function () { undelete(row); })
        : button('Delete', 'linkish', function () { removeRow(row); }));
    }
    if (actions.childNodes.length) fields.appendChild(actions);

    card.appendChild(fields);
    return card;
  }

  // The rail card: enough to choose by, and nothing to edit. Everything
  // editable about a booth lives in the detail pane, so 32 of these stay
  // scannable in a 450px column.
  function renderBoothItem(booth) {
    var dishes = dishesOf(booth.name);
    var pos = positionOf(booth);
    var changed = isRowChanged(booth) || dishes.some(isRowChanged);

    var card = document.createElement('button');
    card.type = 'button';
    card.className = 'booth-item' + (state.selected === booth.name ? ' selected' : '') +
      (changed ? ' edited' : '') + (isDeleted(booth) ? ' deleted' : '');
    card.setAttribute('aria-pressed', state.selected === booth.name ? 'true' : 'false');

    var withPhoto = dishes.filter(function (d) { return currentImage(d); }).length;
    var bits = [dishes.length + (dishes.length === 1 ? ' dish' : ' dishes')];
    if (dishes.length) bits.push(withPhoto + ' of ' + dishes.length + ' photographed');

    card.innerHTML =
      '<span class="booth-item-top">' +
        '<span class="booth-item-name">' + esc(valueOf(booth, 'name')) + '</span>' +
        (pos ? '<span class="pill ' + pos.precision + '">' + esc(pos.precision) + '</span>'
             : '<span class="pill unplaced">Not placed</span>') +
      '</span>' +
      '<span class="booth-item-meta">' + esc(bits.join(' · ')) +
        (isAdded(booth) ? ' <span class="pill curated">' +
          (isDeleted(booth) ? 'Deleted' : 'By hand') + '</span>' : '') +
      '</span>';

    card.addEventListener('click', function () { select(booth.name); });
    return card;
  }

  // The detail pane's header: the same booth, now editable.
  function renderBoothDetail(row) {
    var card = document.createElement('div');
    card.className = 'row booth-row' + (isRowChanged(row) ? ' edited' : '') +
      (isAdded(row) ? ' added' : '') + (isDeleted(row) ? ' deleted' : '');

    var fields = document.createElement('div');
    fields.className = 'fields';

    var pos = positionOf(row);
    var head = document.createElement('div');
    head.className = 'row-head';
    head.innerHTML = '<h2 class="display">' + esc(valueOf(row, 'name')) + '</h2>' +
      (pos ? '<span class="pill ' + pos.precision + '">' + esc(pos.precision) + '</span>'
           : '<span class="pill unplaced">Not placed</span>');
    if (isAdded(row)) {
      var pill = document.createElement('span');
      pill.className = 'pill curated';
      pill.textContent = isDeleted(row) ? 'Deleted' : 'Added by hand';
      head.appendChild(pill);
    }
    fields.appendChild(head);

    var live = dishesOf(row.name).length;
    var meta = document.createElement('div');
    meta.className = 'booth-name';
    meta.textContent = live + (live === 1 ? ' dish on this menu' : ' dishes on this menu');
    fields.appendChild(meta);

    fields.appendChild(makeInput(row, 'category', 'text', 'Category'));
    fields.appendChild(makeInput(row, 'location_description', 'textarea', 'Location description'));

    var geo = document.createElement('div');
    geo.className = 'geo';
    var coords = document.createElement('span');
    coords.innerHTML = pos
      ? '<span class="mono">' + pos.lat.toFixed(5) + ', ' + pos.lon.toFixed(5) + '</span>'
      : '<span style="color:var(--ink-muted)">no coordinate</span>';
    geo.appendChild(coords);
    if (row.name !== AGGREGATE_BOOTH_NAME) {
      geo.appendChild(button(
        state.armed === row.name ? 'Cancel' : (pos ? 'Move pin' : 'Place on map'),
        'small', function () { arm(row.name); }
      ));
      if (pos) geo.appendChild(button('Center', 'small', function () { centerOn(row); }));
      if (state.placements[row.name]) {
        geo.appendChild(button('Discard pin', 'small', function () {
          delete state.placements[row.name];
          save();
          render();
        }));
      }
    }
    fields.appendChild(geo);

    var actions = document.createElement('div');
    actions.className = 'field-row';
    if (isRowChanged(row) && !row._id) actions.appendChild(button('Revert', 'linkish', function () { revert(row); }));
    if (isAdded(row)) {
      actions.appendChild(isDeleted(row)
        ? button('Undo delete', 'linkish', function () { undelete(row); })
        : button('Delete', 'linkish', function () { removeRow(row); }));
    }
    if (actions.childNodes.length) fields.appendChild(actions);

    card.appendChild(fields);
    return card;
  }

  function renderBanner() {
    var el = document.getElementById('armed-banner');
    if (state.armed) {
      el.className = 'panel armed';
      el.innerHTML = 'Click the map to drop a pin for <b>' + esc(state.armed) + '</b> — Esc to cancel.';
    } else {
      el.className = 'panel note';
      el.innerHTML = 'Hit <b>Place on map</b> on a booth to start, then click its spot on the map.';
    }
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
      '<span class="tally">Surveyed <b>' + surveyed + '</b></span>' +
      '<span class="tally">Mapped <b>' + mapped + '</b></span>' +
      '<span class="tally">Anchored <b>' + anchored + '</b></span>' +
      '<span class="tally">Not placed <b>' + unplaced + '</b></span>' +
      '<span class="tally">Booths <b>' + all.length + '</b></span>';
  }

  function renderCounts() {
    var n = changeCount();
    document.getElementById('edit-count').innerHTML =
      n === 0 ? 'No changes yet' : '<b>' + n + '</b>' + (n === 1 ? ' row changed' : ' rows changed');
    document.getElementById('export').disabled = n === 0;
  }

  function emptyNote(text) {
    var el = document.createElement('div');
    el.className = 'panel empty-state';
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
    renderRail();
    renderDetail();
    renderBanner();
    renderTallies();
    renderCounts();
    syncMarkers();
    document.getElementById('map').classList.toggle('armed', !!state.armed);
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
        entry.dietary_tags = valueOf(row, 'tags') || [];
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
    if (!changeCount()) return;
    if (!confirm('Discard every change, pin and attached photo on this device?')) return;
    state.edits = { items: {}, booths: {} };
    state.placements = {};
    state.added = { items: [], booths: [] };
    state.deleted = { items: {}, booths: {} };
    save();
    dropAllPhotos().then(render);
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
  chip('chip-unplaced', 'unplacedOnly');
  chip('chip-edited', 'editedOnly');
  chip('chip-added', 'addedOnly');

  document.getElementById('back-to-booths').addEventListener('click', function () { select(null); });

  document.getElementById('toggle-map').addEventListener('click', function () {
    state.mapOpen ? closeMap() : openMap();
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
  if (!haveLeaflet) document.getElementById('offline-note').classList.remove('hidden');
  loadPhotos().then(render, render);
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
        .replace("__CENTER_JSON__", json.dumps(DEFAULT_CENTER))
        .replace("__ZOOM__", str(DEFAULT_ZOOM))
        .replace("__AGGREGATE_BOOTH_NAME__", json.dumps(AGGREGATE_BOOTH_NAME))
        .replace("__GENERATED_AT__", generated_at or "")
        .replace("__DATA_JSON__", payload)
    )
