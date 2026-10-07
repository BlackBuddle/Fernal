"""Generate Fernal's procedural textures and tray icon.

Run from the repo root:
    .venv/Scripts/python.exe scripts/make_textures.py

Writes fernal/assets/bark.png, bark_normal.png, leaf.png and tray.png.
Deterministic: a fixed seed always produces the same PNGs.
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # never open a window

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QTransform,
)

SEED = 20261007
ASSETS = Path(__file__).resolve().parent.parent / "fernal" / "assets"
BARK_SIZE = 512
LEAF_SIZE = 256
TRAY_SIZE = 64
ROUND = Qt.PenCapStyle.RoundCap


# ----------------------------------------------------------------- helpers

def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def save_png(arr, path):
    """Save a float array (h, w, 3 or 4) in 0..1 as an 8-bit PNG."""
    a = np.ascontiguousarray(np.clip(np.rint(arr * 255.0), 0, 255).astype(np.uint8))
    h, w, c = a.shape
    fmt = QImage.Format.Format_RGBA8888 if c == 4 else QImage.Format.Format_RGB888
    buf = a.tobytes()
    img = QImage(buf, w, h, w * c, fmt).copy()
    if not img.save(str(path), "PNG"):
        raise RuntimeError(f"could not write {path}")


def to_array(img):
    """QImage -> uint8 array (h, w, 4) in RGBA order."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    raw = np.frombuffer(bytes(img.constBits()), np.uint8)
    return raw.reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4)


def blur(a, sigma):
    """Separable Gaussian blur (zero padding outside the image)."""
    r = int(3 * sigma + 0.5)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(np.convolve, 0, a, k, mode="same")
    return np.apply_along_axis(np.convolve, 1, a, k, mode="same")


# -------------------------------------------------------------------- bark

def periodic_noise(rng, n, sx, sy):
    """Tileable Gaussian-filtered noise with unit std.

    sx, sy are spectral widths in cycles per tile; a small sy stretches the
    features along y.
    """
    k = np.fft.fftfreq(n, 1.0 / n)
    amp = np.exp(-((k[None, :] / sx) ** 2 + (k[:, None] / sy) ** 2))
    amp[0, 0] = 0.0
    f = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * amp))
    return f / f.std()


def sample_wrapped(field, x, y):
    """Bilinear lookup of a tileable field at fractional coords (tile = 0..1)."""
    n = field.shape[0]
    fx, fy = x * n, y * n
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - x0, fy - y0
    x0, y0 = x0 % n, y0 % n
    x1, y1 = (x0 + 1) % n, (y0 + 1) % n
    top = field[y0, x0] * (1 - tx) + field[y0, x1] * tx
    bottom = field[y1, x0] * (1 - tx) + field[y1, x1] * tx
    return top * (1 - ty) + bottom * ty


def jittered_points(rng, cols, rows, jitter):
    """Brick-offset jittered grid on the unit torus (rows must be even)."""
    c, r = np.meshgrid(np.arange(cols), np.arange(rows))
    x = (c + 0.5 + 0.5 * (r % 2) + rng.uniform(-jitter, jitter, c.shape)) / cols
    y = (r + 0.5 + rng.uniform(-jitter, jitter, r.shape)) / rows
    return x.ravel() % 1.0, y.ravel() % 1.0


def voronoi(px, py, x, y, stretch):
    """Toroidal F1, F2 and nearest-point index; y distances are divided by stretch."""
    f1 = np.full(x.shape, np.inf)
    f2 = np.full(x.shape, np.inf)
    idx = np.zeros(x.shape, int)
    for i, (ax, ay) in enumerate(zip(px, py)):
        dx = (x - ax + 0.5) % 1.0 - 0.5
        dy = ((y - ay + 0.5) % 1.0 - 0.5) / stretch
        d = np.sqrt(dx * dx + dy * dy)
        near = d < f1
        f2 = np.where(near, f1, np.minimum(f2, d))
        idx = np.where(near, i, idx)
        f1 = np.where(near, d, f1)
    return f1, f2, idx


def wrap_blur(a, passes=2):
    """Cheap tileable 3x3 box blur."""
    for _ in range(passes):
        a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0)) / 3.0
        a = (a + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 3.0
    return a


def border_distance(e):
    """Pixel distance to the Voronoi border (e = F2 - F1) and how vertical the
    border is (1 = long vertical furrow, 0 = horizontal break)."""
    gx = np.maximum(abs(np.roll(e, -1, 1) - e), abs(e - np.roll(e, 1, 1)))
    gy = np.maximum(abs(np.roll(e, -1, 0) - e), abs(e - np.roll(e, 1, 0)))
    g = np.hypot(gx, gy) + 1e-9
    return e / g, wrap_blur(gx / g)


# Knot centres and radii in tile units: (x, y, rx, ry).
KNOTS = ((0.27, 0.64, 0.024, 0.040), (0.73, 0.17, 0.018, 0.030))


def bark_height(rng, n=BARK_SIZE):
    """Tileable bark height field in 0..1 plus an albedo detail term."""
    gy, gx = np.mgrid[0:n, 0:n] / n
    # Domain warp: slow sideways meander plus ragged plate edges.
    wx = 0.018 * periodic_noise(rng, n, 5, 2.5) + 0.004 * periodic_noise(rng, n, 40, 12)
    wy = 0.020 * periodic_noise(rng, n, 4, 4)
    knot_r = []
    for kx, ky, rx, ry in KNOTS:
        dx = (gx - kx + 0.5) % 1.0 - 0.5
        dy = (gy - ky + 0.5) % 1.0 - 0.5
        r = np.hypot(dx / rx, dy / ry)
        wx -= 0.9 * dx * np.exp(-((r / 1.8) ** 2))  # fibres flow around the knot
        knot_r.append(r)
    x, y = gx + wx, gy + wy

    # Long plates separated by deep furrows; horizontal plate ends are only
    # thin, shallow breaks, so the ridges read as interlaced vertical strands.
    px, py = jittered_points(rng, 14, 4, 0.38)
    f1, f2, idx = voronoi(px, py, x, y, 3.5)
    dist, vertical = border_distance(f2 - f1)
    plate = smoothstep(0.0, 11.0, dist * (1.0 + 0.8 * (1.0 - vertical))) ** 0.7
    depth = 0.55 + 0.45 * vertical
    level = 0.78 + 0.22 * rng.random(len(px))
    h = (1 - depth * (1 - plate)) * (1 - (1 - level[idx]) * plate)
    h += 0.05 * plate * (1 - smoothstep(0.0, 0.06, f1))  # slightly domed plates

    # Shallow secondary cracks, only in patches.
    qx, qy = jittered_points(rng, 22, 8, 0.45)
    g1, g2, _ = voronoi(qx, qy, x, y, 2.75)
    patches = smoothstep(0.2, 1.0, periodic_noise(rng, n, 5, 3))
    h -= 0.22 * (1 - smoothstep(0.0, 2.5, border_distance(g2 - g1)[0])) * patches * plate

    # Vertical fibres on the plate tops, following the warped plates.
    fib = 0.5 * periodic_noise(rng, n, 80, 4) + 0.5 * periodic_noise(rng, n, 170, 8)
    fib = sample_wrapped(fib, x, y)
    h += 0.09 * fib * plate

    # Albedo-only detail: per-plate tone, long weathering streaks, fibres.
    streaks = sample_wrapped(periodic_noise(rng, n, 25, 2.5), x, y)
    detail = 0.08 * (rng.random(len(px))[idx] - 0.5) * plate + 0.04 * streaks + 0.03 * fib

    # Knots: sunken eye, raised lip, faint growth rings.
    for r in knot_r:
        rings = 0.04 * np.sin(r * 19.0) * (1 - smoothstep(0.7, 1.0, r))
        knot = 0.66 + 0.30 * np.exp(-(((r - 1.0) / 0.3) ** 2)) - 0.40 * np.exp(-((r / 0.6) ** 2))
        m = 1 - smoothstep(0.9, 1.6, r)
        h = h * (1 - m) + (knot + rings) * m
    return (h - h.min()) / (h.max() - h.min()), detail


def bark_albedo(h, detail, rng):
    """Near-neutral light tint map (0.55..1.0) with a faint warm cast."""
    lap = np.roll(h, 1, 0) + np.roll(h, -1, 0) + np.roll(h, 1, 1) + np.roll(h, -1, 1) - 4 * h
    curv = np.tanh(-lap / (2.0 * lap.std()))  # > 0 on ridges, < 0 in creases
    mottle = periodic_noise(rng, h.shape[0], 6, 6)
    cav = smoothstep(0.08, 0.65, h)  # 0 deep in a furrow, 1 on a plate
    v = 0.30 * cav + 0.10 * h + 0.035 * curv + detail + 0.04 * mottle
    lo, hi = np.percentile(v, [0.5, 99.7])
    v = np.clip(0.55 + 0.45 * (v - lo) / (hi - lo), 0.55, 1.0)
    deep = np.array([1.0, 0.94, 0.88])
    top = np.array([1.0, 0.98, 0.955])
    return v[..., None] * (deep + (top - deep) * cav[..., None])


def bark_normal(h):
    """Tangent-space normal map (OpenGL convention: green = +v, image up)."""
    dx = np.roll(h, -1, 1) - np.roll(h, 1, 1)
    gx = (np.roll(dx, 1, 0) + 2 * dx + np.roll(dx, -1, 0)) / 8.0
    dy = np.roll(h, -1, 0) - np.roll(h, 1, 0)  # derivative towards image bottom
    gy = (np.roll(dy, 1, 1) + 2 * dy + np.roll(dy, -1, 1)) / 8.0
    strength = 1.1 / np.percentile(np.hypot(gx, gy), 95)  # steep furrow walls ~48 deg
    nrm = np.dstack((-gx * strength, gy * strength, np.ones_like(h)))
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
    return nrm * 0.5 + 0.5


# -------------------------------------------------------------------- leaf

def cubic(p0, p1, p2, p3, t):
    t = np.asarray(t, float)[:, None]
    p0, p1, p2, p3 = (np.asarray(p, float) for p in (p0, p1, p2, p3))
    u = 1 - t
    return u**3 * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t**3 * p3


def quad(p0, p1, p2, t):
    t = np.asarray(t, float)[:, None]
    p0, p1, p2 = (np.asarray(p, float) for p in (p0, p1, p2))
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t * t * p2


def leaf_outline():
    """Blade with an acuminate tip (top) and a soft heart-shaped base."""
    p = QPointF
    blade = QPainterPath(p(128, 212))
    for c1, c2, end in (
        ((131, 219), (140, 228), (151, 228)),  # right lobe
        ((170, 228), (190, 196), (190, 158)),  # right flank, widest point
        ((190, 120), (174, 88), (154, 62)),
        ((144, 49), (137, 26), (133, 8)),  # drip tip, leaning slightly right
        ((129, 26), (111, 53), (100, 66)),
        ((78, 92), (60, 112), (60, 150)),  # left half is a little wider
        ((60, 192), (82, 229), (103, 229)),
        ((115, 229), (125, 219), (128, 212)),  # back into the stem notch
    ):
        blade.cubicTo(p(*c1), p(*c2), p(*end))
    blade.closeSubpath()
    return blade


MIDRIB = ((128, 212), (126.5, 150), (129.5, 70), (132.6, 14))
PETIOLE = ((125.5, 250), (127, 238), (128, 226), (128, 206))
# (position on midrib, side, rise / half-width, reach, start angle from vertical)
VEINS = (
    (0.035, 1, -0.12, 0.80, 86), (0.15, 1, 0.50, 0.86, 70), (0.28, 1, 0.66, 0.87, 63),
    (0.41, 1, 0.76, 0.87, 58), (0.54, 1, 0.84, 0.85, 53), (0.67, 1, 0.90, 0.80, 47),
    (0.06, -1, -0.06, 0.80, 84), (0.20, -1, 0.55, 0.86, 68), (0.33, -1, 0.70, 0.87, 61),
    (0.46, -1, 0.78, 0.87, 56), (0.59, -1, 0.86, 0.84, 51), (0.72, -1, 0.92, 0.78, 46),
)


def draw_stroke(painter, pts, widths, darks):
    """Polyline whose width and darkness vary per segment (Darken mode)."""
    for a, b, w, d in zip(pts[:-1], pts[1:], widths, darks):
        g = int(round(255 * (1 - d)))
        painter.setPen(QPen(QColor(g, g, g), float(w), Qt.PenStyle.SolidLine, ROUND))
        painter.drawLine(QPointF(*a), QPointF(*b))


def make_leaf(path, size=LEAF_SIZE):
    centre = QPainterPath(QPointF(*PETIOLE[0]))
    centre.cubicTo(*(QPointF(*q) for q in PETIOLE[1:]))
    stroker = QPainterPathStroker()
    stroker.setWidth(4.6)
    stroker.setCapStyle(ROUND)
    shape = leaf_outline().united(stroker.createStroke(centre))

    mask = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    p = QPainter(mask)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillPath(shape, QColor(255, 255, 255))
    p.end()
    alpha = to_array(mask)[..., 3] / 255.0
    inside = alpha > 0.5
    cols = np.arange(size) + 0.5

    def half_width(x0, y, side):
        xs = cols[inside[int(np.clip(round(y), 0, size - 1))]]
        return abs((xs.max() if side > 0 else xs.min()) - x0)

    veins = QImage(size, size, QImage.Format.Format_RGB32)
    veins.fill(Qt.GlobalColor.white)
    p = QPainter(veins)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Darken)
    p.setClipPath(shape)
    t = np.linspace(0, 1, 33)
    draw_stroke(p, cubic(*PETIOLE, t), np.full(32, 3.6), np.full(32, 0.9))
    t = np.linspace(0, 1, 65)
    tm = (t[:-1] + t[1:]) / 2
    draw_stroke(p, cubic(*MIDRIB, t), 4.2 - 3.3 * tm, 1.0 - 0.55 * tm**1.5)
    t = np.linspace(0, 1, 41)
    tm = (t[:-1] + t[1:]) / 2
    for pos, side, rise, reach, angle in VEINS:
        o = cubic(*MIDRIB, [pos])[0]
        ye = o[1] - rise * half_width(o[0], o[1], side)
        e = np.array([o[0] + side * reach * half_width(o[0], ye, side), ye])
        a = np.radians(angle)
        c = o + 0.6 * np.linalg.norm(e - o) * np.array([side * np.sin(a), -np.cos(a)])
        dark0 = 0.7 if rise < 0 else 0.8
        draw_stroke(p, quad(o, c, e, t), 2.3 * (1 - 0.7 * tm), dark0 * (1 - tm) ** 1.4)
    p.end()
    vein = 1.0 - to_array(veins)[..., 0] / 255.0

    edge = np.clip(2.0 * (1.0 - blur(alpha, 2.0)), 0.0, 1.0) * alpha  # thin rim
    body = smoothstep(0.6, 1.0, blur(alpha, 12.0))  # deep inside the blade
    tone = 0.975 - 0.03 * body + 0.03 * edge
    gray = np.where(alpha > 0, tone - (tone - 0.78) * vein, 0.98)
    rgba = np.dstack((gray, gray, gray, alpha))
    save_png(np.clip(rgba, 0.0, 1.0), path)


# -------------------------------------------------------------------- tray

def render_tray(size=TRAY_SIZE):
    """Leaf glyph tilted towards the upper right, drawn crisply at any size (QImage, ARGB32 premultiplied).

    Margin and vein width scale with size relative to TRAY_SIZE, so the 64 px tray icon is unchanged and the
    larger icon sizes (packaging/make_icon.py) are redrawn, not upscaled. The vein never gets thinner than
    1.5 px, so it still reads at 16 px.
    """
    scale = size / TRAY_SIZE
    margin = 6 * scale
    vein_px = max(3.6 * scale, 1.5)
    leaf = QPainterPath(QPointF(0, 26))
    leaf.cubicTo(QPointF(20, 15), QPointF(17, -15), QPointF(0, -30))
    leaf.cubicTo(QPointF(-17, -15), QPointF(-20, 15), QPointF(0, 26))
    stem = QPainterPath(QPointF(0, 22))
    stem.lineTo(QPointF(0, 36))
    stroker = QPainterPathStroker()
    stroker.setWidth(4.5)
    stroker.setCapStyle(ROUND)
    glyph = leaf.united(stroker.createStroke(stem))
    vein = QPainterPath(QPointF(0, 22))
    vein.quadTo(QPointF(2.0, -2), QPointF(0, -21))

    rot = QTransform().rotate(40)
    box = rot.map(glyph).boundingRect()
    s = (size - margin) / max(box.width(), box.height())
    c = box.center()
    xf = rot * QTransform.fromScale(s, s) * QTransform.fromTranslate(
        size / 2 - c.x() * s, size / 2 - c.y() * s
    )

    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setTransform(xf)
    p.fillPath(glyph, QColor("#5FA85A"))
    p.setPen(QPen(QColor("#D6EFD0"), vein_px / s, Qt.PenStyle.SolidLine, ROUND))
    p.drawPath(vein)
    p.end()
    return img


def make_tray(path, size=TRAY_SIZE):
    if not render_tray(size).save(str(path), "PNG"):
        raise RuntimeError(f"could not write {path}")


# -------------------------------------------------------------------- main

def main():
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    ASSETS.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    h, detail = bark_height(rng)
    save_png(bark_albedo(h, detail, rng), ASSETS / "bark.png")
    save_png(bark_normal(h), ASSETS / "bark_normal.png")
    make_leaf(ASSETS / "leaf.png")
    make_tray(ASSETS / "tray.png")
    for name in ("bark.png", "bark_normal.png", "leaf.png", "tray.png"):
        print("wrote", ASSETS / name)


if __name__ == "__main__":
    main()
