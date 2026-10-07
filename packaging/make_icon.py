"""Write packaging/fernal.ico: the tray leaf glyph, redrawn (not upscaled) at every icon size.

Run from the repo root:
    .venv/Scripts/python.exe packaging/make_icon.py

The glyph comes from render_tray() in scripts/make_textures.py, which scales its margin and vein width with
the size. The ICO container is written with struct and holds one PNG-encoded image per size (Vista and later).
"""
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # never open a window

import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import make_textures  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = HERE / "fernal.ico"


def png_bytes(img) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, "PNG"):
        raise RuntimeError("could not encode PNG")
    buf.close()
    return bytes(data)


def build_ico(entries) -> bytes:
    """entries: [(size, png_bytes)] -> ICO file contents (ICONDIR, ICONDIRENTRY per image, then the PNGs)."""
    head = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(head) + 16 * len(entries)
    directory, blobs = b"", b""
    for size, png in entries:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    return head + directory + blobs


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    entries = [(s, png_bytes(make_textures.render_tray(s))) for s in SIZES]
    OUT.write_bytes(build_ico(entries))
    print("wrote", OUT, f"({OUT.stat().st_size} bytes, sizes {', '.join(map(str, SIZES))})")


if __name__ == "__main__":
    main()
