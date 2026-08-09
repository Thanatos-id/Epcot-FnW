import os
from build_icon import (render, triangles, legs, CX, CY, R_OUT, R_IN,
                        SRC_W, SRC_H, BG, FG)

OUT = "epcot-icons/icons"
os.makedirs(OUT, exist_ok=True)

ANY_FRAC = 0.78       # comfortable breathing room for un-cropped contexts
MASK_FRAC = 0.60      # fits inside the 40%-radius maskable safe circle

# ---------- PNG raster set ----------
render(1024, ANY_FRAC).save(f"{OUT}/icon-1024.png")
render(512,  ANY_FRAC).save(f"{OUT}/icon-512.png")
render(192,  ANY_FRAC).save(f"{OUT}/icon-192.png")
render(512,  MASK_FRAC).save(f"{OUT}/icon-maskable-512.png")
render(192,  MASK_FRAC).save(f"{OUT}/icon-maskable-192.png")
render(180,  ANY_FRAC).convert("RGB").save(f"{OUT}/apple-touch-icon.png")
render(256,  0.88).save(f"{OUT}/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])


# ---------- SVG (true vector, infinitely sharp) ----------
def to_svg(content_frac, size=1024):
    content = size * content_frac
    s = content / max(SRC_W, SRC_H)
    ox = (size - SRC_W * s) / 2.0
    oy = (size - SRC_H * s) / 2.0
    T = lambda p: (p[0] * s + ox, p[1] * s + oy)
    fg = "#%02X%02X%02X" % FG
    bg = "#%02X%02X%02X" % BG

    cx, cy = T((CX, CY))
    ro, ri = R_OUT * s, R_IN * s

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">',
        f'<rect width="{size}" height="{size}" fill="{bg}"/>',
        f'<g fill="{fg}">',
        # ring drawn as a stroked circle on the mid-radius
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{(ro + ri) / 2:.2f}" '
        f'fill="none" stroke="{fg}" stroke-width="{ro - ri:.2f}"/>',
    ]
    for poly in legs() + triangles():
        pts = " ".join("%.2f,%.2f" % T(p) for p in poly)
        parts.append(f'<polygon points="{pts}"/>')
    parts += ["</g>", "</svg>"]
    return "\n".join(parts)


open(f"{OUT}/icon.svg", "w").write(to_svg(ANY_FRAC))
open(f"{OUT}/icon-maskable.svg", "w").write(to_svg(MASK_FRAC))

print("\n".join(sorted(os.listdir(OUT))))
