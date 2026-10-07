"""Render every glass panel over a dark and a bright backdrop into docs/screenshots/panels.png.

    python scripts/preview_panels.py [--out PATH] [--accent HEX] [--keep]

The panels are shown as real windows (so layouts and fonts are final), grabbed with QWidget.grab() including
their translucency, and composited over a dark desktop-like gradient (left half) and a bright photo-like
gradient (right half). --keep leaves the windows open on screen afterwards (for real-screen inspection).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout  # noqa: E402

from fernal.tools import TEXT, TEXT_DIM, GlassPanel, SettingsPanel, ToolPanel, _label  # noqa: E402

GAP = 28
MARGIN = 44


def build(accent: str):
    water = ToolPanel("water", accent)
    water.set_value(0.35)
    water.set_caption("마지막 물 주기 2시간 전")
    feed = ToolPanel("nutrients", accent)
    feed.set_value(0.6)
    climate = ToolPanel("climate", accent)
    climate.set_value((3 + 10) / 20)
    climate.set_caption("현재 24.5°C")
    spray = ToolPanel("spray", accent)
    spray.set_value(0.8)
    spray.set_caption("실내 습도 52%")
    settings = SettingsPanel(accent)
    settings.set_values("normal", "C:/Users/me/Models/terracotta_pot_v2.glb", "서울", 420, 640)
    settings.set_status("서울특별시 · 37.57°N 126.98°E")
    glass = GlassPanel("식물 상태", accent)
    for name, value in (("나이", "3일 4시간"), ("활력", "92%"), ("애정", "높음")):
        row = QHBoxLayout()
        row.addWidget(_label(name, 12, TEXT_DIM), 0, Qt.AlignmentFlag.AlignBaseline)
        row.addStretch(1)
        row.addWidget(_label(value, 15, TEXT), 0, Qt.AlignmentFlag.AlignBaseline)
        glass.body.addLayout(row)
    glass.adjustSize()
    return [water, feed, climate, spray, settings, glass]


def backdrop(img: QImage, w: float, h: float) -> None:
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    half = w / 2
    # dark desktop: deep navy to violet with soft glows
    g = QLinearGradient(QPointF(0, 0), QPointF(half, h))
    g.setColorAt(0.0, QColor("#0B1020"))
    g.setColorAt(0.6, QColor("#1A1838"))
    g.setColorAt(1.0, QColor("#2A1A3A"))
    p.fillRect(QRectF(0, 0, half, h), g)
    for cx, cy, r, c in ((0.25, 0.15, 0.55, "#2B4C8C"), (0.8, 0.9, 0.5, "#5A2E6E")):
        rg = QRadialGradient(QPointF(half * cx, h * cy), half * r)
        col = QColor(c)
        col.setAlpha(150)
        rg.setColorAt(0.0, col)
        col.setAlpha(0)
        rg.setColorAt(1.0, col)
        p.fillRect(QRectF(0, 0, half, h), rg)
    # bright photo-like scene: pale sky into warm light with leafy and sunny blotches
    g = QLinearGradient(QPointF(half, 0), QPointF(half, h))
    g.setColorAt(0.0, QColor("#CFE6F7"))
    g.setColorAt(0.55, QColor("#F4EBD8"))
    g.setColorAt(1.0, QColor("#E9DCC0"))
    p.fillRect(QRectF(half, 0, half, h), g)
    for cx, cy, r, c, a in ((0.15, 0.2, 0.35, "#FFFFFF", 230), (0.55, 0.85, 0.4, "#A9C98A", 170),
                            (0.9, 0.3, 0.3, "#FFE2A8", 200), (0.35, 0.6, 0.25, "#BFD9EE", 150)):
        rg = QRadialGradient(QPointF(half + half * cx, h * cy), half * r)
        col = QColor(c)
        col.setAlpha(a)
        rg.setColorAt(0.0, col)
        col.setAlpha(0)
        rg.setColorAt(1.0, col)
        p.fillRect(QRectF(half, 0, half, h), rg)
    p.end()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots",
                                                  "panels.png"))
    ap.add_argument("--accent", default="#5FA85A")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    panels = build(args.accent)
    x = MARGIN
    for w in panels:
        w.move(x, 80)
        w.show()
        x += w.width() + GAP
    total_w = x - GAP + MARGIN
    total_h = max(w.height() for w in panels) + 2 * MARGIN

    def shoot():
        dpr = max(w.devicePixelRatioF() for w in panels)
        img = QImage(int(total_w * dpr), int(total_h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        backdrop(img, total_w, total_h)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        px = MARGIN
        for w in panels:
            p.drawPixmap(QPointF(px, MARGIN), w.grab())
            px += w.width() + GAP
        p.end()
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        img.save(out)
        print(f"wrote {out} ({img.width()}x{img.height()})")
        if not args.keep:
            app.quit()

    QTimer.singleShot(600, shoot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
