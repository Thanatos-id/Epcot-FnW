"""Renders docs/editor.html, the editable view of the database.

The ledger shows what the crawl found. This is for when what it found is
wrong - a mis-tagged drink, a price the blog fat-fingered, a dish name still
carrying the source's punctuation - and the fix is one person who can see it
typing the right answer.

Edits never touch the database directly. They come out as a block for
`data/manual/menu_items.json` and `data/manual/booth_locations.json`, staged
through the same curated `manual` source (priority_rank 0) that the booth
survey feeds, which is what makes a correction survive the next crawl instead
of being overwritten by it.

Rendered by build_artifact.py alongside the ledger, from the same snapshot,
so the two can never disagree about what is in the database. `render()` is
pure - snapshot in, HTML out - so it is testable without a browser.
"""

from __future__ import annotations

import json
from typing import Any

# Everything a curated menu_item record may carry. Order is column order.
ITEM_FIELDS = ("name", "description", "price", "category", "tags")

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


def editor_rows(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Flatten the snapshot into the two tables the page edits.

    Menu items are flattened out of their booths and carry `booth` with them,
    because a dish is only identified by the pair - five booths sell something
    called "Beer Flight" - and that pair is what a curated record needs to
    find it again.
    """
    booths, items = [], []
    for booth in snapshot.get("booths") or []:
        name = booth.get("name")
        if not name:
            continue
        booths.append(
            {
                "name": name,
                "category": booth.get("category"),
                "location_description": booth.get("location_description"),
                "latitude": booth.get("latitude"),
                "longitude": booth.get("longitude"),
                "location_precision": booth.get("location_precision"),
                "item_count": len(booth.get("items") or []),
            }
        )
        for item in booth.get("items") or []:
            if not item.get("name"):
                continue
            items.append(
                {
                    "booth": name,
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "price": item.get("price"),
                    "category": item.get("category"),
                    "tags": sorted(item.get("tags") or []),
                }
            )
    return {"booths": booths, "items": items}


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light dark" />
<meta name="description" content="Editable table view of the crawled Epcot Food &amp; Wine Festival database - correct a dish, a price, a category or a dietary tag and export the result as curated overrides." />
<title>Database Editor — Epcot Food &amp; Wine</title>

<link rel="manifest" href="manifest.json" />
<link rel="icon" href="icons/favicon.ico" sizes="any" />
<link rel="icon" type="image/svg+xml" href="icons/icon.svg" />
<link rel="apple-touch-icon" sizes="180x180" href="icons/apple-touch-icon.png" />
<meta name="apple-mobile-web-app-title" content="DB Editor" />
<meta name="theme-color" content="#efe8d8" media="(prefers-color-scheme: light)" />
<meta name="theme-color" content="#1b1510" media="(prefers-color-scheme: dark)" />
<style>
:root {
  --bg: #efe8d8; --surface: #fbf7ee; --surface-2: #f3ebd8; --ink: #241c16;
  --ink-muted: #6b5d4f; --accent: #7a2036; --accent-soft: #f0dce0; --gold: #a9752b;
  --gold-soft: #f1e2c4; --border: #ddd0b5; --good: #4f7a45; --good-soft: #e1ebdb;
  --warn: #bb5a2c; --warn-soft: #f3e1d2;
  --shadow: 0 1px 2px rgba(36,28,22,0.06), 0 8px 24px rgba(36,28,22,0.06);
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
}
.wrap { max-width: 1400px; margin: 0 auto; padding: clamp(18px, 4vw, 34px) clamp(12px, 3vw, 22px) 130px; }
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
.subtitle a { color: var(--accent); }

.panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  box-shadow: var(--shadow); padding: 13px 15px; margin: 16px 0;
  font-size: 13.5px; color: var(--ink-muted);
}
.panel b { color: var(--ink); }

/* ---------- toolbar ---------- */
.toolbar {
  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
  margin: 18px 0 12px;
}
input[type="search"], select, input[type="text"], input[type="number"], textarea {
  font: inherit; font-size: 14px; color: var(--ink); background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 11px;
}
input[type="search"] { flex: 1 1 260px; min-width: 0; }
input[type="search"]:focus, select:focus, textarea:focus, .cell-input:focus {
  outline: 2px solid var(--accent); outline-offset: -1px;
}
button {
  font: inherit; font-size: 14px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); padding: 8px 13px; cursor: pointer;
  min-height: 40px;
}
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
button.primary:disabled { opacity: 0.5; cursor: default; }
button.tab.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 600; }
.spacer { flex: 1 1 auto; }
.count { font-size: 13px; color: var(--ink-muted); white-space: nowrap; }

/* ---------- table ---------- */
.table-shell {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  box-shadow: var(--shadow); overflow-x: auto; -webkit-overflow-scrolling: touch;
}
table { border-collapse: collapse; width: 100%; min-width: 960px; }
thead th {
  position: sticky; top: 0; z-index: 2; background: var(--surface-2);
  text-align: left; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--ink-muted); font-weight: 700; padding: 10px 12px;
  border-bottom: 1px solid var(--border); white-space: nowrap; cursor: pointer;
  user-select: none;
}
thead th.no-sort { cursor: default; }
thead th .arrow { color: var(--accent); font-size: 10px; }
tbody td {
  padding: 4px 8px; border-bottom: 1px solid var(--border); vertical-align: top;
  font-size: 13.5px;
}
tbody tr:nth-child(even) { background: var(--surface-2); }
tbody tr.edited { box-shadow: inset 3px 0 0 var(--gold); }
tbody tr.edited td:first-child { font-weight: 600; }
td.col-booth { color: var(--ink-muted); font-size: 12.5px; padding-top: 12px; width: 150px; }
td.col-name { width: 250px; }
td.col-price { width: 96px; }
td.col-cat { width: 170px; }
td.col-tags { width: 250px; }
td.readonly { padding-top: 12px; }

.cell-input {
  font: inherit; font-size: 13.5px; width: 100%; color: var(--ink);
  background: transparent; border: 1px solid transparent; border-radius: 6px;
  padding: 6px 7px; resize: vertical;
}
.cell-input:hover { border-color: var(--border); }
.cell-input.changed { background: var(--gold-soft); border-color: var(--gold); }
textarea.cell-input { min-height: 38px; line-height: 1.4; }
select.cell-input { padding: 6px 5px; }
select.cell-input.changed { background: var(--gold-soft); }

/* Collapsed by default. Seven toggles on 229 rows is three lines of chrome
   per row and a table nobody can scan; the tags actually set are the only
   ones worth showing until someone means to change them. */
.tag-cell { padding: 6px 0; cursor: pointer; min-height: 30px; }
.tag-cell:hover .tag-edit { color: var(--accent); }
.tag-summary { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.tag-none { color: var(--ink-muted); font-size: 12px; font-style: italic; }
.tag-edit { color: var(--ink-muted); font-size: 11px; margin-left: 2px; }
.tag-picker { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 0; }
.tag-toggle {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.02em;
  padding: 3px 8px; border-radius: 20px; cursor: pointer;
  border: 1px solid var(--border); background: transparent; color: var(--ink-muted);
  min-height: 0;
}
.tag-toggle.on { background: var(--gold-soft); border-color: var(--gold); color: var(--gold); }
.tag-toggle.changed { outline: 1px dashed var(--gold); outline-offset: 1px; }

.revert, .tag-done {
  border: none; background: transparent; color: var(--accent); cursor: pointer;
  font-size: 12px; padding: 6px 4px; min-height: 0; text-decoration: underline;
}
.empty-state { padding: 34px 16px; text-align: center; color: var(--ink-muted); }

/* ---------- export drawer ---------- */
.sticky {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 10;
  background: var(--surface); border-top: 1px solid var(--border);
  padding: 10px clamp(12px, 3vw, 22px) calc(10px + env(safe-area-inset-bottom));
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  box-shadow: 0 -4px 20px rgba(0,0,0,0.07);
}
.sticky .count b { color: var(--accent); }
dialog {
  border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
  color: var(--ink); max-width: min(760px, 92vw); width: 100%; padding: 0;
  box-shadow: 0 12px 48px rgba(0,0,0,0.3);
}
dialog::backdrop { background: rgba(20,14,10,0.5); }
.dialog-body { padding: 18px 20px 20px; }
.dialog-body h2 { margin: 0 0 6px; font-size: 19px; }
.dialog-body p { margin: 0 0 12px; font-size: 13.5px; color: var(--ink-muted); }
.dialog-body code { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; }
.export-block { margin-bottom: 16px; }
.export-block h3 { margin: 0 0 4px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-muted); }
textarea.export {
  width: 100%; min-height: 150px; font-family: ui-monospace, Menlo, monospace; font-size: 12px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 10px;
}
.dialog-actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
footer { margin-top: 26px; color: var(--ink-muted); font-size: 12.5px; }
footer a { color: var(--accent); }
.hidden { display: none !important; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">Editable snapshot</div>
    <h1 class="display">Database Editor</h1>
    <p class="subtitle">
      Every dish and booth in the database, editable in place. Change what's wrong, then
      <b>Export</b> — the result is a block to paste into the curated files, which override
      the crawl and survive the next refresh. <a href="index.html">Back to the ledger</a>.
    </p>
  </header>

  <div class="panel">
    <b>Nothing here writes to the database.</b> Edits live in this browser until you export
    them, so you can work through the list across several sittings. A dish's <b>name</b> is
    how a correction finds it again, so renaming one is recorded as a rename rather than an
    edit — both the old and new name go into the export.
  </div>

  <div class="toolbar">
    <button type="button" class="tab active" id="tab-items">Dishes</button>
    <button type="button" class="tab" id="tab-booths">Booths</button>
    <input type="search" id="search" placeholder="Search dishes, booths, descriptions…" autocomplete="off" />
    <select id="filter-booth"><option value="">All booths</option></select>
    <select id="filter-cat">
      <option value="">All categories</option>
      <option value="food">Food</option>
      <option value="alcoholic_beverage">Alcoholic</option>
      <option value="non_alcoholic_beverage">Non-alcoholic</option>
    </select>
    <button type="button" id="filter-edited">Edited only</button>
    <span class="count" id="result-count"></span>
  </div>

  <div class="table-shell">
    <table id="grid"><thead id="grid-head"></thead><tbody id="grid-body"></tbody></table>
  </div>

  <footer>
    Snapshot built __GENERATED_AT__ · <a href="survey.html">Booth survey</a> ·
    Prices are US dollars; a blank price means no source has published one.
  </footer>
</div>

<div class="sticky">
  <span class="count" id="edit-count"></span>
  <span class="spacer"></span>
  <button type="button" id="discard">Discard all</button>
  <button type="button" class="primary" id="export" disabled>Export changes</button>
</div>

<dialog id="export-dialog">
  <div class="dialog-body">
    <h2 class="display">Export</h2>
    <p>Paste each block over the matching key in its file, then run <code>epcot-fw manual</code>.</p>
    <div class="export-block" id="block-items">
      <h3>data/manual/menu_items.json</h3>
      <textarea class="export" id="export-items" readonly spellcheck="false"></textarea>
    </div>
    <div class="export-block" id="block-booths">
      <h3>data/manual/booth_locations.json</h3>
      <textarea class="export" id="export-booths" readonly spellcheck="false"></textarea>
    </div>
    <div class="dialog-actions">
      <button type="button" id="copy-all">Copy both</button>
      <button type="button" class="primary" id="close-dialog">Done</button>
    </div>
  </div>
</dialog>

<script id="editor-data" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById('editor-data').textContent);
  var CATEGORIES = __CATEGORIES__;
  var TAGS = __TAGS__;
  var STORE_KEY = 'epcot-db-editor-v1';

  var ITEM_COLUMNS = [
    { key: 'booth',       label: 'Booth',       sortable: true,  edit: false },
    { key: 'name',        label: 'Dish',        sortable: true,  edit: 'text' },
    { key: 'description', label: 'Description', sortable: false, edit: 'textarea' },
    { key: 'price',       label: 'Price',       sortable: true,  edit: 'price' },
    { key: 'category',    label: 'Category',    sortable: true,  edit: 'select' },
    { key: 'tags',        label: 'Dietary tags',sortable: false, edit: 'tags' }
  ];
  var BOOTH_COLUMNS = [
    { key: 'name',                 label: 'Booth',      sortable: true,  edit: false },
    { key: 'item_count',           label: 'Items',      sortable: true,  edit: false },
    { key: 'category',             label: 'Category',   sortable: true,  edit: 'text' },
    { key: 'location_description', label: 'Location',   sortable: false, edit: 'textarea' },
    { key: 'location_precision',   label: 'Precision',  sortable: true,  edit: false },
    { key: 'coords',               label: 'Coordinates',sortable: false, edit: false }
  ];

  var state = {
    tab: 'items',
    edits: load(),
    q: '',
    booth: '',
    category: '',
    editedOnly: false,
    expandedTags: null,
    sort: { key: null, dir: 1 }
  };

  function load() {
    try {
      var raw = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
      return { items: raw.items || {}, booths: raw.booths || {} };
    } catch (e) {
      return { items: {}, booths: {} };   // private mode, storage off - start clean
    }
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state.edits)); } catch (e) {}
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // A dish is identified by booth + name; five booths sell a "Beer Flight".
  function rowKey(row) {
    // JSON rather than a delimiter: any separator that can appear in a
    // name makes ('A B', 'C') and ('A', 'B C') the same key.
    return state.tab === 'items' ? JSON.stringify([row.booth, row.name]) : row.name;
  }
  function bucket() { return state.edits[state.tab === 'items' ? 'items' : 'booths']; }
  function rows() { return state.tab === 'items' ? DATA.items : DATA.booths; }

  function edited(row, key) {
    var e = bucket()[rowKey(row)];
    return e && Object.prototype.hasOwnProperty.call(e, key) ? e : null;
  }
  function valueOf(row, key) {
    var e = edited(row, key);
    return e ? e[key] : row[key];
  }
  function isRowEdited(row) {
    var e = bucket()[rowKey(row)];
    return !!e && Object.keys(e).length > 0;
  }
  function editCount() {
    return Object.keys(state.edits.items).length + Object.keys(state.edits.booths).length;
  }

  function setValue(row, key, value) {
    var store = bucket();
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
    delete bucket()[rowKey(row)];
    save();
    render();
  }

  // ---- filtering ----
  function visibleRows() {
    var list = rows().filter(function (row) {
      if (state.editedOnly && !isRowEdited(row)) return false;
      if (state.tab === 'items') {
        if (state.booth && row.booth !== state.booth) return false;
        if (state.category && valueOf(row, 'category') !== state.category) return false;
      }
      if (state.q) {
        var hay = [row.booth, valueOf(row, 'name'), valueOf(row, 'description'),
                   valueOf(row, 'location_description')].join(' ').toLowerCase();
        if (hay.indexOf(state.q) === -1) return false;
      }
      return true;
    });

    if (state.sort.key) {
      var k = state.sort.key, dir = state.sort.dir;
      list = list.slice().sort(function (a, b) {
        var av = valueOf(a, k), bv = valueOf(b, k);
        if (av === null || av === undefined || av === '') return 1;   // blanks last, always
        if (bv === null || bv === undefined || bv === '') return -1;
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
        return String(av).localeCompare(String(bv)) * dir;
      });
    }
    return list;
  }

  // ---- rendering ----
  var head = document.getElementById('grid-head');
  var body = document.getElementById('grid-body');

  function columns() { return state.tab === 'items' ? ITEM_COLUMNS : BOOTH_COLUMNS; }

  function renderHead() {
    var tr = document.createElement('tr');
    columns().forEach(function (col) {
      var th = document.createElement('th');
      th.textContent = col.label;
      if (!col.sortable) {
        th.className = 'no-sort';
      } else {
        if (state.sort.key === col.key) {
          th.innerHTML = esc(col.label) + ' <span class="arrow">' + (state.sort.dir > 0 ? '▲' : '▼') + '</span>';
        }
        th.addEventListener('click', function () {
          if (state.sort.key === col.key) state.sort.dir = -state.sort.dir;
          else state.sort = { key: col.key, dir: 1 };
          render();
        });
      }
      tr.appendChild(th);
    });
    var th = document.createElement('th');
    th.className = 'no-sort';
    tr.appendChild(th);
    head.innerHTML = '';
    head.appendChild(tr);
  }

  function makeInput(row, col) {
    var value = valueOf(row, col.key);
    var changed = !!edited(row, col.key);
    var el;

    if (col.edit === 'textarea') {
      el = document.createElement('textarea');
      el.rows = 2;
      el.value = value === null || value === undefined ? '' : value;
    } else if (col.edit === 'select') {
      el = document.createElement('select');
      CATEGORIES.forEach(function (c) {
        var o = document.createElement('option');
        o.value = c;
        o.textContent = c.replace(/_/g, ' ');
        el.appendChild(o);
      });
      el.value = value || 'food';
    } else if (col.edit === 'price') {
      el = document.createElement('input');
      el.type = 'number';
      el.step = '0.01';
      el.min = '0';
      el.value = value === null || value === undefined ? '' : value;
    } else {
      el = document.createElement('input');
      el.type = 'text';
      el.value = value === null || value === undefined ? '' : value;
    }

    el.className = 'cell-input' + (changed ? ' changed' : '');
    el.addEventListener('change', function () {
      var next = el.value;
      if (col.edit === 'price') next = el.value === '' ? null : Number(el.value);
      if (col.edit !== 'price' && next === '') next = null;
      setValue(row, col.key, next);
      el.classList.toggle('changed', !!edited(row, col.key));
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
      if (state.expandedTags === key) {
        cell.appendChild(makeTagPicker(row, paint));
        return;
      }
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
      summary.addEventListener('click', function () {
        state.expandedTags = key;
        paint();
      });
      cell.appendChild(summary);
    }
    paint();
    return cell;
  }

  function makeTagPicker(row, repaint) {
    var wrap = document.createElement('div');
    wrap.className = 'tag-picker';
    var current = (valueOf(row, 'tags') || []).slice();
    var changed = !!edited(row, 'tags');
    TAGS.forEach(function (tag) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tag-toggle' + (current.indexOf(tag) !== -1 ? ' on' : '') + (changed ? ' changed' : '');
      btn.textContent = tag.replace(/_/g, ' ');
      btn.addEventListener('click', function () {
        var next = (valueOf(row, 'tags') || []).slice();
        var at = next.indexOf(tag);
        if (at === -1) next.push(tag); else next.splice(at, 1);
        next.sort();
        setValue(row, 'tags', next);
        renderRowTags(wrap, row);
        markRow(wrap, row);
      });
      wrap.appendChild(btn);
    });
    var done = document.createElement('button');
    done.type = 'button';
    done.className = 'tag-done';
    done.textContent = 'done';
    done.addEventListener('click', function () {
      state.expandedTags = null;
      if (repaint) repaint();
    });
    wrap.appendChild(done);
    return wrap;
  }

  function renderRowTags(wrap, row) {
    var current = valueOf(row, 'tags') || [];
    var changed = !!edited(row, 'tags');
    // Only the toggles. The picker also holds a "done" button, and walking
    // every child by index repainted that one as TAGS[7] - an undefined tag,
    // which turned the button into a dead chip on the first toggle.
    var buttons = wrap.querySelectorAll('button.tag-toggle');
    Array.prototype.forEach.call(buttons, function (btn, i) {
      btn.className = 'tag-toggle' + (current.indexOf(TAGS[i]) !== -1 ? ' on' : '') + (changed ? ' changed' : '');
    });
  }

  function markRow(el, row) {
    var tr = el.closest('tr');
    if (!tr) return;
    tr.classList.toggle('edited', isRowEdited(row));
    var cell = tr.querySelector('.revert-cell');
    if (cell) cell.innerHTML = '';
    if (cell && isRowEdited(row)) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'revert';
      b.textContent = 'Revert';
      b.addEventListener('click', function () { revert(row); });
      cell.appendChild(b);
    }
  }

  function render() {
    renderHead();
    var list = visibleRows();
    body.innerHTML = '';

    if (!list.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = columns().length + 1;
      td.className = 'empty-state';
      td.textContent = state.editedOnly ? 'No edits yet.' : 'Nothing matches that search.';
      tr.appendChild(td);
      body.appendChild(tr);
    }

    list.forEach(function (row) {
      var tr = document.createElement('tr');
      if (isRowEdited(row)) tr.className = 'edited';

      columns().forEach(function (col) {
        var td = document.createElement('td');
        td.className = 'col-' + col.key.replace(/_/g, '-');
        if (col.key === 'booth') td.className = 'col-booth';
        if (col.key === 'name' && state.tab === 'items') td.className = 'col-name';
        if (col.key === 'price') td.className = 'col-price';
        if (col.key === 'category' && state.tab === 'items') td.className = 'col-cat';
        if (col.key === 'tags') td.className = 'col-tags';

        if (col.edit === 'tags') {
          td.appendChild(makeTagCell(row));
        } else if (!col.edit) {
          td.classList.add('readonly');
          if (col.key === 'coords') {
            td.innerHTML = row.latitude
              ? '<span class="mono">' + Number(row.latitude).toFixed(5) + ', ' + Number(row.longitude).toFixed(5) + '</span>'
              : '<span style="color:var(--ink-muted)">not placed</span>';
          } else {
            td.textContent = row[col.key] === null || row[col.key] === undefined ? '—' : row[col.key];
          }
        } else {
          td.appendChild(makeInput(row, col));
        }
        tr.appendChild(td);
      });

      var actions = document.createElement('td');
      actions.className = 'revert-cell';
      tr.appendChild(actions);
      body.appendChild(tr);

      if (isRowEdited(row)) markRow(actions, row);
    });

    document.getElementById('result-count').textContent =
      list.length + (list.length === 1 ? ' row' : ' rows');
    renderCounts();
  }

  function renderCounts() {
    var n = editCount();
    document.getElementById('edit-count').innerHTML =
      n === 0 ? 'No changes yet' : '<b>' + n + '</b>' + (n === 1 ? ' row changed' : ' rows changed');
    document.getElementById('export').disabled = n === 0;
  }

  // ---- export ----
  // Only what changed: a curated file listing every dish would freeze the
  // whole menu against the crawl, so a future price correction from the
  // source could never land.
  function buildExport() {
    var items = [];
    DATA.items.forEach(function (row) {
      var e = state.edits.items[rowKey(row)];
      if (!e) return;
      var entry = { booth_name: row.booth, name: row.name };
      if (Object.prototype.hasOwnProperty.call(e, 'name')) entry.rename_to = e.name;
      if (Object.prototype.hasOwnProperty.call(e, 'description')) entry.description = e.description;
      if (Object.prototype.hasOwnProperty.call(e, 'price')) entry.price_usd = e.price;
      if (Object.prototype.hasOwnProperty.call(e, 'category')) entry.category = e.category;
      if (Object.prototype.hasOwnProperty.call(e, 'tags')) entry.dietary_tags = e.tags;
      items.push(entry);
    });

    var booths = [];
    DATA.booths.forEach(function (row) {
      var e = state.edits.booths[rowKey(row)];
      if (!e) return;
      var entry = { name: row.name };
      if (Object.prototype.hasOwnProperty.call(e, 'category')) entry.category = e.category;
      if (Object.prototype.hasOwnProperty.call(e, 'location_description')) {
        entry.location_description = e.location_description;
      }
      booths.push(entry);
    });

    return {
      items: JSON.stringify({ menu_items: items }, null, 2),
      booths: JSON.stringify({ booths: booths }, null, 2),
      hasItems: items.length > 0,
      hasBooths: booths.length > 0
    };
  }

  var dialog = document.getElementById('export-dialog');
  document.getElementById('export').addEventListener('click', function () {
    var out = buildExport();
    document.getElementById('export-items').value = out.items;
    document.getElementById('export-booths').value = out.booths;
    document.getElementById('block-items').classList.toggle('hidden', !out.hasItems);
    document.getElementById('block-booths').classList.toggle('hidden', !out.hasBooths);
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
  });
  document.getElementById('close-dialog').addEventListener('click', function () {
    if (dialog.close) dialog.close(); else dialog.removeAttribute('open');
  });
  document.getElementById('copy-all').addEventListener('click', function () {
    var out = buildExport();
    var text = (out.hasItems ? 'data/manual/menu_items.json\n' + out.items + '\n\n' : '') +
               (out.hasBooths ? 'data/manual/booth_locations.json\n' + out.booths : '');
    var btn = document.getElementById('copy-all');
    var done = function () {
      btn.textContent = 'Copied';
      setTimeout(function () { btn.textContent = 'Copy both'; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () {});
    } else {
      document.getElementById('export-items').select();
      try { document.execCommand('copy'); done(); } catch (e) {}
    }
  });

  document.getElementById('discard').addEventListener('click', function () {
    if (!editCount()) return;
    if (!confirm('Discard every change on this device?')) return;
    state.edits = { items: {}, booths: {} };
    save();
    render();
  });

  // ---- controls ----
  function switchTab(tab) {
    state.tab = tab;
    state.sort = { key: null, dir: 1 };
    document.getElementById('tab-items').classList.toggle('active', tab === 'items');
    document.getElementById('tab-booths').classList.toggle('active', tab === 'booths');
    document.getElementById('filter-booth').classList.toggle('hidden', tab !== 'items');
    document.getElementById('filter-cat').classList.toggle('hidden', tab !== 'items');
    render();
  }
  document.getElementById('tab-items').addEventListener('click', function () { switchTab('items'); });
  document.getElementById('tab-booths').addEventListener('click', function () { switchTab('booths'); });

  var boothFilter = document.getElementById('filter-booth');
  DATA.booths.forEach(function (b) {
    var o = document.createElement('option');
    o.value = b.name;
    o.textContent = b.name;
    boothFilter.appendChild(o);
  });
  boothFilter.addEventListener('change', function () { state.booth = boothFilter.value; render(); });
  document.getElementById('filter-cat').addEventListener('change', function (e) {
    state.category = e.target.value;
    render();
  });
  document.getElementById('search').addEventListener('input', function (e) {
    state.q = e.target.value.trim().toLowerCase();
    render();
  });
  var editedBtn = document.getElementById('filter-edited');
  editedBtn.addEventListener('click', function () {
    state.editedOnly = !state.editedOnly;
    editedBtn.classList.toggle('active', state.editedOnly);
    editedBtn.className = 'tab' + (state.editedOnly ? ' active' : '');
    render();
  });

  render();
})();
</script>
</body>
</html>
"""


def render(snapshot: dict[str, Any], *, generated_at: str = "") -> str:
    """Snapshot in, complete self-contained page out."""
    rows = editor_rows(snapshot)
    # `</` is broken up because the blob sits inside a <script> element, where
    # the HTML parser ends the element at the first `</script>` regardless of
    # what the JSON quoting thinks.
    payload = json.dumps(rows, default=str).replace("</", "<\\/")
    return (
        TEMPLATE.replace("__CATEGORIES__", json.dumps(list(CATEGORIES)))
        .replace("__TAGS__", json.dumps(list(TAGS)))
        .replace("__GENERATED_AT__", generated_at or "")
        .replace("__DATA_JSON__", payload)
    )
