"""Rebuild the Epcot Spaceship Earth mark as true vector geometry.

Measurements taken from the source raster (905x924 crop):
  sphere center (453, 452), outer radius 448, ring thickness 40
  lattice: horizontal period 194, triangle base 108, height 94
  row centers (y): 118, 250, 381.5, 522.5, 654.5, 785
"""
import numpy as np
from PIL import Image, ImageDraw

# ---- source-space geometry constants ----
CX, CY = 453.0, 452.0
R_OUT = 448.0
RING = 40.0
R_IN = R_OUT - RING

PERIOD = 194.0      # horizontal lattice period
TRI_B = 108.0       # triangle base width
TRI_H = 94.0        # triangle height
ROW_PITCH = 134.5
ROW_Y = [CY + ROW_PITCH * k for k in (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)]  # even & symmetric

SRC_W, SRC_H = 905.0, 924.0

BG = (26, 32, 48)
FG = (139, 74, 232)



def _clip_to_circle(poly, cx, cy, r, n=192):
    """Sutherland-Hodgman clip of a convex polygon against a circle (as an n-gon)."""
    import math
    clip = [(cx + r * math.cos(2 * math.pi * i / n),
             cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    out = list(poly)
    for i in range(n):
        a, b = clip[i], clip[(i + 1) % n]
        if not out:
            return []
        ex, ey = b[0] - a[0], b[1] - a[1]
        def inside(p):
            return ex * (p[1] - a[1]) - ey * (p[0] - a[0]) >= 0
        new = []
        for j in range(len(out)):
            cur, prv = out[j], out[j - 1]
            ci, pi_ = inside(cur), inside(prv)
            if ci:
                if not pi_:
                    new.append(_isect(prv, cur, a, b))
                new.append(cur)
            elif pi_:
                new.append(_isect(prv, cur, a, b))
        out = new
    return out


def _isect(p1, p2, a, b):
    x1, y1 = p1; x2, y2 = p2; x3, y3 = a; x4, y4 = b
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-12:
        return p2
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def triangles():
    """Yield triangle polygons in source coordinates, clipped to the inner circle."""
    out = []
    for ri, ycen in enumerate(ROW_Y):
        top = ycen - TRI_H / 2.0
        bot = ycen + TRI_H / 2.0
        # alternate the phase per row so rows interlock
        phase = (PERIOD / 2.0) if ri % 2 else 0.0
        k_range = range(-6, 7)
        for k in k_range:
            # down-pointing triangle: wide edge on top
            xc = CX + phase + k * PERIOD
            out.append([(xc - TRI_B / 2, top), (xc + TRI_B / 2, top), (xc, bot)])
            # up-pointing triangle: wide edge on bottom, offset half a period
            xu = xc + PERIOD / 2.0
            out.append([(xu - TRI_B / 2, bot), (xu + TRI_B / 2, bot), (xu, top)])
    # clip each triangle to the inner circle so the lattice fills the sphere
    r = R_IN - 10
    kept = []
    for tri in out:
        c = _clip_to_circle(tri, CX, CY, r)
        if len(c) >= 3 and _area(c) > 40:
            kept.append(c)
    return kept


def _area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def legs():
    """Two flared support legs plus horizontal feet, measured off the source."""
    polys = []
    y_top, y_bot = 819.0, 902.0
    y_foot_t, y_foot_b = 894.0, 920.0
    for s in (-1, 1):
        polys.append([
            (CX + s * 257.0, y_top),   # outer, on the circle
            (CX + s * 173.0, y_top),   # inner, on the circle
            (CX + s * 185.0, y_bot),   # inner, near vertical
            (CX + s * 343.0, y_bot),   # outer, flared out
        ])
        xa, xb = CX + s * 389.0, CX + s * 178.0
        polys.append([
            (min(xa, xb), y_foot_t), (max(xa, xb), y_foot_t),
            (max(xa, xb), y_foot_b), (min(xa, xb), y_foot_b),
        ])
    return polys


def render(out_size, content_frac, ss=8):
    """Draw the mark at `ss`x supersample, then downsample for clean anti-aliasing."""
    content_px = out_size * content_frac
    scale = content_px / max(SRC_W, SRC_H) * ss
    off_x = (out_size * ss - SRC_W * scale) / 2.0
    off_y = (out_size * ss - SRC_H * scale) / 2.0

    def T(p):
        return (p[0] * scale + off_x, p[1] * scale + off_y)

    img = Image.new("RGB", (out_size * ss, out_size * ss), BG)
    d = ImageDraw.Draw(img)

    # outer ring (annulus): purple disc, then punch out the middle with bg
    c = T((CX, CY))
    ro = R_OUT * scale
    ri = R_IN * scale
    d.ellipse([c[0] - ro, c[1] - ro, c[0] + ro, c[1] + ro], fill=FG)
    d.ellipse([c[0] - ri, c[1] - ri, c[0] + ri, c[1] + ri], fill=BG)

    for poly in legs():
        d.polygon([T(p) for p in poly], fill=FG)
    for tri in triangles():
        d.polygon([T(p) for p in tri], fill=FG)

    return img.resize((out_size, out_size), Image.LANCZOS)


if __name__ == "__main__":
    render(1024, 0.80).save("preview-1024.png")
    print("triangles kept:", len(triangles()))
