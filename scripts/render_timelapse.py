"""Render a growth time-lapse (sunrise to night) as PNG frames for the project page video.

Run from the repo root:

    .venv/Scripts/python.exe scripts/render_timelapse.py --out frames/ --seconds 8 --fps 30

The plant grows from 20 to 100 percent of its mature age while the sun crosses the sky
(06:00 to 21:00 in Seoul) and the moon takes over at dusk. Every frame sets the sun, the
plant age and the wind clock explicitly, then grabs the window, so the result does not
depend on how fast the machine renders. Frames are composited over #303030 like the
screenshots. Encode them with ffmpeg, for example:

    ffmpeg -framerate 30 -i frames/frame_%04d.png -c:v libx264 -pix_fmt yuv420p -crf 26 \
        -preset slow -movflags +faststart docs/media/timelapse.mp4
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# On the basic render loop grabWindow() renders exactly the state set just before it.
os.environ["QSG_RENDER_LOOP"] = "basic"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preview_scene as ps  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from PySide6.QtCore import QObject, Qt, QUrl, qInstallMessageHandler  # noqa: E402
from PySide6.QtQuick import QQuickView, QQuickWindow  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fernal import mesh, sky, themes, tree  # noqa: E402


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="folder for frame_0001.png ...")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--theme", choices=sorted(themes.THEMES), default="normal")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--start-hour", type=float, default=6.0)
    ap.add_argument("--end-hour", type=float, default=21.0)
    ap.add_argument("--grow-until", type=float, default=0.8, help="clip fraction at which the tree is fully grown")
    ap.add_argument("--wind", type=float, default=0.45)
    args = ap.parse_args(argv)

    qInstallMessageHandler(ps._qt_message)
    app = QApplication(sys.argv[:1])
    QQuickWindow.setDefaultAlphaBuffer(True)

    # The skeleton is shaped by the afternoon sun, as in the app (App.sun_dir uses 13:00).
    today = datetime.now(ps.KST).date()
    midnight = datetime(today.year, today.month, today.day, tzinfo=ps.KST)
    el13, az13 = sky.sun_position(ps.LAT, ps.LON, midnight + timedelta(hours=13))
    env = SimpleNamespace(water=0.6, nutrients=0.5, temperature=22.0, humidity=0.5, light=0.6,
                          affection=0.9 if args.theme == "fruit" else 0.5)
    params = tree.params_from(env, 1.0, ps.sun_vector(el13, az13), args.theme)
    skel = tree.generate(args.seed, params)
    mature = ps.full_age(skel)

    t = themes.theme(args.theme)
    bridge = ps.PreviewBridge(theme=args.theme, glowEnabled=t["glow"], particlesEnabled=True,
                              barkColor=t["bark"], emissiveColor=t["bark_emissive"], leafColor=t["leaf"],
                              leafEmissive=t["leaf_emissive"], fruitColor=t["fruit_color"],
                              accentColor=t["accent"], vitality=1.0, windStrength=args.wind)
    geometries = {key: mesh.PlantGeometry() for key in ("branch", "leaf", "fruit")}

    view = QQuickView()
    view.setColor(Qt.transparent)
    view.setFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(*ps.WINDOW)
    view.setPosition(100, 100)
    ctx = view.rootContext()
    ctx.setContextProperty("bridge", bridge)
    ctx.setContextProperty("branchGeometry", geometries["branch"])
    ctx.setContextProperty("leafGeometry", geometries["leaf"])
    ctx.setContextProperty("fruitGeometry", geometries["fruit"])
    ctx.setContextProperty("assetsUrl", QUrl.fromLocalFile(str(ps.ASSETS) + "/"))
    view.setSource(QUrl.fromLocalFile(str(ps.SCENE)))
    if view.status() != QQuickView.Ready:
        for err in view.errors():
            print("QML ERROR: " + err.toString(), file=sys.stderr, flush=True)
        return 2
    view.show()
    root = view.rootObject()
    # Stop the scene's own wind clock; every frame sets the clock itself.
    for obj in root.findChildren(QObject):
        if obj.metaObject().className() == "QQuickNumberAnimation":
            obj.setProperty("running", False)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = int(round(args.seconds * args.fps))
    for i in range(frames):
        u = i / max(1, frames - 1)
        hour = args.start_hour + (args.end_hour - args.start_hour) * u
        elevation, azimuth = sky.sun_position(ps.LAT, ps.LON, midnight + timedelta(hours=hour))
        bridge.sunElevation, bridge.sunAzimuth = elevation, azimuth
        bridge.dayFactor = sky.day_factor(elevation)
        age = mature * (0.2 + 0.8 * smoothstep(u / args.grow_until))
        geometries["branch"].set_arrays(mesh.branch_arrays(skel, age))
        geometries["leaf"].set_arrays(mesh.leaf_arrays(skel, age, params.leaf_size))
        geometries["fruit"].set_arrays(mesh.fruit_arrays(skel, age))
        root.setProperty("time", 10.0 + i / args.fps)
        app.processEvents()
        img = view.grabWindow()
        if img.isNull():
            print(f"grab failed at frame {i + 1}", file=sys.stderr, flush=True)
            return 3
        ps.composite(img).save(str(out / f"frame_{i + 1:04d}.png"))
        if i % args.fps == 0:
            print(f"frame {i + 1}/{frames}: hour {hour:.1f}, age {age:.1f}/{mature:.1f} h", flush=True)
    print(f"wrote {frames} frames to {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
