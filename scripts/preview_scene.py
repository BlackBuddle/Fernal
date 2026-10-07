"""Render fernal/qml/Scene.qml for one tree and save a screenshot composited over #303030.

Run from the repo root, for example:

    .venv/Scripts/python.exe scripts/preview_scene.py --theme erdtree --age mature --hour 14 \
        --seed 7 --out docs/screenshots/scene_erdtree_day.png

``--age`` takes plant hours, ``mature`` (the age at which everything is fully grown) or a
percentage of that age such as ``45%``. With ``--twin`` a second frame is grabbed one second
later, saved as ``<out>_b.png``, and the number of differing pixels is printed (wind check).

The window is a transparent frameless QQuickView like the real overlay, with a stand-in
``PreviewBridge`` that carries every property Scene.qml reads.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import Property, QObject, Qt, QTimer, QUrl, Signal, Slot, qInstallMessageHandler
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQuick import QQuickView, QQuickWindow
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fernal import mesh, sky, themes, tree  # noqa: E402

SCENE = ROOT / "fernal" / "qml" / "Scene.qml"
ASSETS = ROOT / "fernal" / "assets"
LAT, LON = 37.57, 126.98  # Seoul
KST = timezone(timedelta(hours=9))
WINDOW = (420, 640)
BACKDROP = "#303030"
SETTLE_MS = 1500  # rendering time after the first swapped frame before the grab
TWIN_MS = 1000

# (name, type, default) for every property Scene.qml reads from the bridge.
BRIDGE_PROPS = (
    ("sunElevation", float, 45.0),
    ("sunAzimuth", float, 180.0),
    ("dayFactor", float, 1.0),
    ("theme", str, "normal"),
    ("glowEnabled", bool, False),
    ("particlesEnabled", bool, True),
    ("potSource", str, ""),
    ("barkColor", str, "#5A4030"),
    ("emissiveColor", str, "#000000"),
    ("leafColor", str, "#4F8A3A"),
    ("leafEmissive", str, "#000000"),
    ("fruitColor", str, "#D9452B"),
    ("accentColor", str, "#5FA85A"),
    ("vitality", float, 1.0),
    ("windStrength", float, 0.4),
    ("cameraYaw", float, 0.0),
    ("cameraPitch", float, 8.0),
    ("cameraDistance", float, 650.0),
)


def _make_bridge_class():
    """QObject with a Qt Property and a <name>Changed signal per BRIDGE_PROPS entry."""
    ns = {}

    def add(name, typ):
        signal = Signal()

        def getter(self):
            return self._values[name]

        def setter(self, value):
            value = typ(value)
            if self._values[name] != value:
                self._values[name] = value
                getattr(self, name + "Changed").emit()

        ns[name + "Changed"] = signal
        ns[name] = Property(typ, getter, setter, notify=signal)

    for name, typ, _ in BRIDGE_PROPS:
        add(name, typ)

    def __init__(self, parent=None, **values):
        QObject.__init__(self, parent)
        self._values = {name: default for name, _, default in BRIDGE_PROPS}
        for key, value in values.items():
            setattr(self, key, value)

    ns["__init__"] = __init__
    return type("PreviewBridge", (QObject,), ns)


PreviewBridge = _make_bridge_class()


def sun_vector(elevation_deg, azimuth_deg):
    """Unit vector toward the sun in scene axes (x east, y up, z south)."""
    el, az = np.radians(elevation_deg), np.radians(azimuth_deg)
    return (float(np.cos(el) * np.sin(az)), float(np.sin(el)), float(-np.cos(el) * np.cos(az)))


def full_age(skel):
    """Plant hours after which every segment, leaf and fruit is fully grown."""
    ages = [s.birth_age + s.grow_hours for s in skel.segments]
    if len(skel.leaf_birth):
        ages.append(float(np.max(skel.leaf_birth)) + mesh.LEAF_GROW_HOURS)
    if len(skel.fruit_birth):
        ages.append(float(np.max(skel.fruit_birth)) + mesh.FRUIT_GROW_HOURS)
    return max(ages)


def parse_age(text, mature_age):
    text = text.strip().lower()
    if text == "mature":
        return mature_age
    if text.endswith("%"):
        return mature_age * float(text[:-1]) / 100.0
    return float(text)


def composite(img, backdrop=BACKDROP):
    """Premultiplied 'over' onto the backdrop with saturation (glow may write rgb > alpha)."""
    out = QImage(img.width(), img.height(), QImage.Format_ARGB32_Premultiplied)
    out.setDevicePixelRatio(img.devicePixelRatio())  # draw the grab 1:1 in physical pixels
    out.fill(QColor(backdrop))
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    p.drawImage(0, 0, img)
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    p.drawImage(0, 0, img)
    p.end()
    return out


def pixels(img):
    """(H, W, 4) uint8 copy of the image; the copy outlives the converted QImage."""
    img = img.convertToFormat(QImage.Format_ARGB32)
    rows = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())
    return rows[:, : img.width() * 4].reshape(img.height(), img.width(), 4).copy()


def _qt_message(mode, context, message):
    """Forward every Qt message (QML warnings, shader compile errors) to stderr."""
    print(f"qt[{mode.name}]: {message}", file=sys.stderr, flush=True)


class FirstFrame(QObject):
    """Calls back once, on the first swapped frame."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self._done = False

    @Slot()
    def on_frame(self):
        if not self._done:
            self._done = True
            self._callback()


def build_scene_inputs(args):
    """Sun, bridge values and the three mesh arrays for the requested tree."""
    today = datetime.now(KST).date()
    hour = float(args.hour)
    when = datetime(today.year, today.month, today.day, tzinfo=KST) + timedelta(hours=hour)
    elevation, azimuth = sky.sun_position(LAT, LON, when)
    day = sky.day_factor(elevation)
    is_day = elevation > 0.0

    env = SimpleNamespace(
        water=0.6, nutrients=0.5, temperature=22.0, humidity=0.5,
        light=0.6 if is_day else 0.0,
        affection=0.9 if args.theme == "fruit" else 0.5,
    )
    vitality = float(args.vitality)
    # Phototropism follows the sun only while it is up; at night the plant just grows upward.
    sun_dir = sun_vector(elevation, azimuth) if is_day else (0.0, 1.0, 0.0)
    params = tree.params_from(env, vitality, sun_dir, args.theme)
    skel = tree.generate(args.seed, params)
    mature = full_age(skel)
    age = parse_age(args.age, mature)

    t = themes.theme(args.theme)
    bridge_values = dict(
        sunElevation=elevation, sunAzimuth=azimuth, dayFactor=day,
        theme=args.theme, glowEnabled=t["glow"], particlesEnabled=not args.no_particles,
        barkColor=t["bark"], emissiveColor=t["bark_emissive"], leafColor=t["leaf"],
        leafEmissive=t["leaf_emissive"], fruitColor=t["fruit_color"], accentColor=t["accent"],
        vitality=vitality, windStrength=args.wind,
        cameraYaw=args.yaw, cameraPitch=args.pitch, cameraDistance=args.distance,
    )
    if args.pot:
        bridge_values["potSource"] = QUrl.fromLocalFile(str(Path(args.pot).resolve())).toString()
    arrays = dict(
        branch=mesh.branch_arrays(skel, age),
        leaf=mesh.leaf_arrays(skel, age, params.leaf_size),
        fruit=mesh.fruit_arrays(skel, age),
    )
    info = (f"theme={args.theme} seed={args.seed} age={age:.1f}h (mature {mature:.1f}h) "
            f"hour={hour:g} sun el={elevation:.1f} az={azimuth:.1f} day={day:.2f} "
            f"verts branch={len(arrays['branch'][0])} leaf={len(arrays['leaf'][0])} "
            f"fruit={len(arrays['fruit'][0])}")
    return bridge_values, arrays, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", choices=sorted(themes.THEMES), default="normal")
    ap.add_argument("--age", default="mature", help='plant hours, "mature" or a percentage like "45%%"')
    ap.add_argument("--hour", type=float, default=14.0, help="local hour in UTC+9 (Seoul)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True, help="PNG path")
    ap.add_argument("--twin", action="store_true", help="grab a second frame 1 s later (wind check)")
    ap.add_argument("--wind", type=float, default=0.4)
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=8.0)
    ap.add_argument("--distance", type=float, default=650.0)
    ap.add_argument("--pot", default="", help="optional .glb/.gltf pot file")
    ap.add_argument("--no-particles", action="store_true")
    ap.add_argument("--vitality", type=float, default=1.0, help="0..1; low values turn leaves autumnal")
    ap.add_argument("--backdrop", default=BACKDROP, help="backdrop color behind the transparent window")
    ap.add_argument("--scene", default=str(SCENE), help="QML scene file (default: fernal/qml/Scene.qml)")
    args = ap.parse_args(argv)

    qInstallMessageHandler(_qt_message)
    app = QApplication(sys.argv[:1])
    QQuickWindow.setDefaultAlphaBuffer(True)

    bridge_values, arrays, info = build_scene_inputs(args)
    print(info, flush=True)
    bridge = PreviewBridge(**bridge_values)
    geometries = {}
    for key in ("branch", "leaf", "fruit"):
        geometries[key] = mesh.PlantGeometry()
        geometries[key].set_arrays(arrays[key])

    view = QQuickView()
    view.setColor(Qt.transparent)
    view.setFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(*WINDOW)
    view.setPosition(100, 100)
    ctx = view.rootContext()
    ctx.setContextProperty("bridge", bridge)
    ctx.setContextProperty("branchGeometry", geometries["branch"])
    ctx.setContextProperty("leafGeometry", geometries["leaf"])
    ctx.setContextProperty("fruitGeometry", geometries["fruit"])
    ctx.setContextProperty("assetsUrl", QUrl.fromLocalFile(str(ASSETS) + "/"))
    view.setSource(QUrl.fromLocalFile(str(Path(args.scene).resolve())))
    if view.status() != QQuickView.Ready:
        for err in view.errors():
            print("QML ERROR: " + err.toString(), file=sys.stderr, flush=True)
        return 2
    view.show()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    twin_path = out.with_name(out.stem + "_b" + out.suffix)
    result = {"rc": 0}

    def grab():
        img = view.grabWindow()
        if img.isNull():
            print("grab failed", file=sys.stderr, flush=True)
            result["rc"] = 3
        return img

    def first_grab():
        img = grab()
        if img.isNull():
            app.quit()
            return
        corners = [img.pixelColor(x, y).alpha() for x, y in
                   ((0, 0), (img.width() - 1, 0), (0, img.height() - 1), (img.width() - 1, img.height() - 1))]
        comp = composite(img, args.backdrop)
        comp.save(str(out))
        print(f"saved {out} ({img.width()}x{img.height()}, corner alphas {corners})", flush=True)
        if args.twin:
            result["first"] = comp
            QTimer.singleShot(TWIN_MS, second_grab)
        else:
            app.quit()

    def second_grab():
        img = grab()
        if not img.isNull():
            comp = composite(img, args.backdrop)
            comp.save(str(twin_path))
            a, b = pixels(result["first"]), pixels(comp)
            diff = int(np.any(a != b, axis=2).sum())
            print(f"saved {twin_path}; differing pixels: {diff}", flush=True)
        app.quit()

    first = FirstFrame(lambda: QTimer.singleShot(SETTLE_MS, first_grab))
    view.frameSwapped.connect(first.on_frame, Qt.QueuedConnection)
    QTimer.singleShot(30000, app.quit)  # safety net
    app.exec()
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
