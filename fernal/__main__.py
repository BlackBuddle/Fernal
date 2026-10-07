"""Command line entry point: python -m fernal [--screenshot PATH] [--theme T] [--age H] [--seed N] [--hour H].

Without --screenshot the overlay runs normally. --theme, --seed and --age seed a fresh plant (first run or
screenshot); an existing state file keeps its own values.
"""
import argparse
import logging
import os
import signal
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from . import themes
from .app import App


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m fernal", description="Desktop overlay that grows a 3D plant.")
    ap.add_argument("--screenshot", metavar="PATH", help="render one frame to PATH (PNG) and exit")
    ap.add_argument("--theme", choices=sorted(themes.THEMES), help="theme of a fresh plant (default: normal)")
    ap.add_argument("--age", type=float, metavar="HOURS",
                    help="plant age in hours (screenshot default: fully grown; first run: 8)")
    ap.add_argument("--seed", type=int, metavar="N", help="plant seed (screenshot default: 1; first run: random)")
    ap.add_argument("--hour", type=float, metavar="LOCAL_HOUR",
                    help="screenshot only: local hour of day for the sun, e.g. 14 or 6.5 (default: now)")
    ap.add_argument("--state", metavar="PATH", help="state file (default: %%APPDATA%%/Fernal/state.json)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # Render on the GUI thread. OverlayWindow overrides event() in Python, which holds the GIL while Qt
    # waits for the render thread; that thread needs the GIL to sync PlantGeometry (a Python subclass),
    # so the threaded loop deadlocks on the first frame. Drop this once overlay.py uses an event filter.
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    QCoreApplication.setOrganizationName("")
    QCoreApplication.setApplicationName("Fernal")
    qapp = QApplication(sys.argv[:1])
    qapp.setQuitOnLastWindowClosed(False)  # the tray keeps the app alive

    # Ctrl+C / Ctrl+Break quit cleanly so the state is saved; Python runs the handler on the next tick.
    for name in ("SIGINT", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: qapp.quit())

    return App(args).run()


if __name__ == "__main__":
    sys.exit(main())
