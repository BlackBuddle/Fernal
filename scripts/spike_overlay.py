"""T0 spike: transparent, frameless, always-on-top QQuickView with View3D glow/shadow/particles.

Run from the repo root: .venv/Scripts/python.exe scripts/spike_overlay.py
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Slot
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "docs" / "screenshots" / "spike.png"
COMPOSITE = ROOT / "docs" / "screenshots" / "spike_composite.png"
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20


def log(msg):
    print(msg, flush=True)


def ex_style(view):
    get = ctypes.windll.user32.GetWindowLongW
    get.argtypes = [wintypes.HWND, ctypes.c_int]
    get.restype = ctypes.c_long
    return get(int(view.winId()), GWL_EXSTYLE) & 0xFFFFFFFF


class FirstFrame(QObject):
    """Starts the capture countdown once the first frame has actually been swapped in."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self._done = False

    @Slot()
    def on_frame(self):
        if not self._done:
            self._done = True
            self._callback()


def main():
    app = QApplication(sys.argv)
    QQuickWindow.setDefaultAlphaBuffer(True)

    view = QQuickView()
    view.setColor(Qt.transparent)
    view.setFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(420, 640)
    view.setPosition(100, 100)
    view.setSource(QUrl.fromLocalFile(str(ROOT / "scripts" / "spike.qml")))
    if view.status() != QQuickView.Ready:
        for err in view.errors():
            log("QML ERROR: " + err.toString())
        return 2
    view.show()

    results = {}

    def step_grab():
        api = view.rendererInterface().graphicsApi()
        results["rhi"] = QSGRendererInterface.GraphicsApi(api).name
        log(f"RHI backend: {results['rhi']}")
        img = view.grabWindow()
        SHOT.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(SHOT))
        w, h = img.width(), img.height()
        log(f"grab size: {w}x{h} dpr={img.devicePixelRatio()} format={img.format().name}")
        # The four logical corners (0,0),(419,0),(0,639),(419,639) are the image corners in physical
        # pixels (the grab is 420*DPR x 640*DPR).
        corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
        alphas = [img.pixelColor(x, y).alpha() for x, y in corners]
        results["corners"] = all(a == 0 for a in alphas)
        log(f"(a) corner alphas {corners} = {alphas} -> transparent={results['corners']}")
        nonzero = sum(1 for y in range(0, h, 4) for x in range(0, w, 4) if img.pixelColor(x, y).alpha() > 0)
        log(f"    sampled non-transparent pixels (every 4th): {nonzero}")
        comp = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        comp.setDevicePixelRatio(img.devicePixelRatio())
        comp.fill(QColor("#303030"))
        # Premultiplied "over" with saturation, like DWM: glow may write rgb > alpha, and a plain
        # SourceOver would overflow 8-bit channels there. DestinationOut then Plus both clamp.
        p = QPainter(comp)
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        p.drawImage(0, 0, img)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.drawImage(0, 0, img)
        p.end()
        comp.save(str(COMPOSITE))
        log(f"(b) composite saved: {COMPOSITE}")
        QTimer.singleShot(0, step_click_on)

    def step_click_on():
        view.setFlag(Qt.WindowTransparentForInput, True)
        QTimer.singleShot(300, check_on)

    def check_on():
        style = ex_style(view)
        results["bit_on"] = bool(style & WS_EX_TRANSPARENT)
        log(f"(c) transparent-for-input ON: exstyle=0x{style:08X} WS_EX_TRANSPARENT={results['bit_on']}")
        view.setFlag(Qt.WindowTransparentForInput, False)
        QTimer.singleShot(300, check_off)

    def check_off():
        style = ex_style(view)
        results["bit_off"] = not (style & WS_EX_TRANSPARENT)
        img = view.grabWindow()
        results["grab_ok"] = (not img.isNull()) and img.width() > 0 and img.height() > 0
        log(
            f"(c) transparent-for-input OFF: exstyle=0x{style:08X} bit_cleared={results['bit_off']} "
            f"grab_ok={results['grab_ok']} ({img.width()}x{img.height()})"
        )
        log(f"click-through toggle ok: {results['bit_on'] and results['bit_off'] and results['grab_ok']}")
        app.quit()

    # 1500 ms of real rendering after the first swapped frame (scene setup alone can take ~1 s).
    first = FirstFrame(lambda: QTimer.singleShot(1500, step_grab))
    view.frameSwapped.connect(first.on_frame, Qt.QueuedConnection)
    QTimer.singleShot(20000, app.quit)  # safety net
    rc = app.exec()
    log(f"exit code {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
