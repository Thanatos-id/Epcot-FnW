# Epcot App Icons

> **How this is wired up in this repo.** The "To install" steps below describe
> a generic static root where paths resolve to `/icons/...`. This repo
> publishes `docs/` at a GitHub Pages *project* subpath, so root-absolute
> paths would 404 — the head tags in `tools/data_ledger/build_artifact.py` and
> the `src` entries in `assets/manifest.json` use **relative** paths instead.
> The icons here are build assets: `build_artifact.py` copies them into
> `docs/` on every build. Don't hand-edit `docs/icons/`. Everything below
> about the artwork, the maskable/any split, and the iOS notes still applies.


Generated from your uploaded Spaceship Earth mark. Ready to drop into a web
app's `public/` (or equivalent static root).

## What's in here

```
icons/
  icon.svg                    true vector source -- infinitely sharp, re-export any size from this
  icon-maskable.svg           vector source, sized for the maskable safe zone
  icon-1024.png               large raster master
  icon-192.png                manifest "any" icon
  icon-512.png                manifest "any" icon
  icon-maskable-192.png       manifest "maskable" icon (content fit to 40% safe-zone radius)
  icon-maskable-512.png       manifest "maskable" icon (content fit to 40% safe-zone radius)
  apple-touch-icon.png        180x180, opaque, for iOS home screen
  favicon.ico                 16/32/48 multi-size, browser tab icon
manifest.json                  web app manifest with the icons array wired up
head-snippet.html              <head> tags to paste into your HTML/layout
build_icon.py                  parametric generator (geometry constants live here)
export_icons.py                re-exports every PNG + SVG from the geometry
```

## About the artwork

The original upload was a JPEG, so scaling it up produced soft, artifacty
edges. Rather than upscaling pixels, the mark was measured and rebuilt as
actual geometry -- sphere radius, ring thickness, lattice period, triangle
dimensions, and leg attach points were all derived from the source, then
redrawn as vector shapes. Every raster here is rendered from that geometry at
8x supersample and downsampled, so edges are clean at every size and the
triangle corners stay crisp instead of rounding off.

If you ever need a different size or want to tweak the color, edit the
constants at the top of `build_icon.py` and run `python3 export_icons.py`.

## To install

1. Copy the `icons/` folder into your app's static/public directory (root, so paths resolve to `/icons/...`).
2. Drop `manifest.json` in your static root too (or merge the `icons` array into an existing manifest).
3. Paste the contents of `head-snippet.html` into your `<head>` (index.html, root layout, etc.).

## Why both "any" and "maskable" icons

- **any** icons (`icon-192`, `icon-512`) keep the full mark with breathing room — used as-is by browsers/desktops that don't crop to a shape.
- **maskable** icons are built so the logo sits inside the safe 40%-radius circle with background filling edge-to-edge — Android and other platforms crop these to a circle/squircle/whatever shape without clipping your artwork.

## The iOS Liquid Glass piece

iOS 26 only applies the new Default/Dark/Clear/Tinted Liquid Glass treatment
to home-screen icons that come from an `apple-touch-icon` link tag — the
manifest.json icons alone aren't enough. That tag is already in
`head-snippet.html`, pointing at `apple-touch-icon.png` (180×180, no
transparency, since iOS fills transparent pixels with black).

**One limitation to know about:** native iOS apps can build Liquid Glass icons
from separate foreground/mid-ground/background layers in Apple's Icon
Composer, which lets the system add real depth and parallax. PWAs can only
supply a single flat image, so iOS applies its Clear/Tinted/Dark processing
to that one layer rather than true multi-layer glass. This icon was designed
with that in mind — bold, simple shapes with high contrast against the dark
background — since intricate detail tends to get lost once the system's blur
and translucency are applied. If you eventually wrap this as a native iOS
app, the same mark can be rebuilt in Icon Composer with proper layers for the
full effect.

## Testing

There's no PWA-specific Liquid Glass preview tool from Apple — test by adding
to your iPhone's home screen and checking it under Settings > Appearance in
Default, Dark, Clear, and Tinted modes.
