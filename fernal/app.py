"""Controller: owns the plant state, the timers and the overlay window.

Scene axes: x = east, y = up, z = south. Everything Qt-free that is worth testing lives in module-level
helpers (`params_moved`, `clamp_window`, `effective_radiation`, `mean_radiation`, `local_time_at`).
"""
import dataclasses
import logging
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import (QObject, QPoint, QRunnable, QStandardPaths, QThreadPool, QTimer, QUrl, Qt, Signal,
                            Slot)
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication, QFileDialog, QSystemTrayIcon

from . import debug_panel, mesh, overlay, sim, sky, themes, tools, tree

log = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

TICK_MS = 1000
SAVE_MS = 60_000
WEATHER_MS = 3_600_000
REGEN_MS = 50                   # regenerate requests inside this window are coalesced
HEATER_REGEN_MS = 250           # while the climate slider moves, regenerate once it pauses this long
MESH_MIN_INTERVAL = 0.1         # s between growth-driven mesh rebuilds
REGEN_THRESHOLD = 0.03          # a Params field must move by this share of its range to regenerate
CATCH_UP_GAP = 60.0             # s: a longer tick gap (sleep, stall) is replayed through sim.catch_up
CATCH_UP_CAP = 7 * 86400.0      # s, same cap as sim.catch_up
OFFLINE_RADIATION = 0.7         # synthesized peak radiation before the first successful weather fetch
WIND_STRENGTH = 0.4

FIRST_RUN_AGE = 48.0            # plant hours: the first launch already shows a young leafy tree
FIRST_RUN_TIME_SCALE = 8.0      # a plant matures in roughly a day
MATURE_AGE = 1e6                # screenshot default: everything fully grown

ORBIT_YAW_PER_PX = 0.4
ORBIT_PITCH_PER_PX = 0.3
PITCH_RANGE = (-10.0, 60.0)
ZOOM_RANGE = (300.0, 1200.0)
ZOOM_PER_DELTA = 0.5            # cm per wheel delta unit (one notch = 120)

WINDOW_MIN_SIZE = 100
WINDOW_MIN_VISIBLE = 40         # px of a saved window that must still lie on a screen

PANEL_GAP = 12                  # px between the overlay window and a panel placed beside it
PANEL_CASCADE = 24              # px each further panel is shifted (outward in x, down in y)
DEBUG_SHORTCUT = "Ctrl+Shift+D"
POT_MISSING = "화분 파일을 찾을 수 없습니다"
CITY_MISSING = "도시를 찾지 못했습니다"

SCREENSHOT_SETTLE_MS = 1500     # rendering time after the first swapped frame before the grab
SCREENSHOT_TIMEOUT_MS = 30_000

# Range of every numeric Params field (the contract's ranges; trunk_length and max_segments are
# never moved by params_from, their ranges only scale the comparison). Tropism is a unit vector.
PARAM_RANGES = {
    "branch_factor": (1.5, 3.5),
    "length_ratio": (0.6, 0.85),
    "spread_deg": (20.0, 60.0),
    "droop": (0.0, 1.0),
    "leaf_density": (0.0, 1.0),
    "leaf_size": (0.5, 1.5),
    "tropism_strength": (0.0, 1.0),
    "max_depth": (4, 7),
    "trunk_length": (50.0, 200.0),
    "fruit_ratio": (0.0, 1.0),
    "max_segments": (200, 3000),
}
TROPISM_RANGE = (-1.0, 1.0)


# ---- pure helpers (no Qt GUI needed) -------------------------------------------------------


def _clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


def default_state_path() -> Path:
    """QStandardPaths AppDataLocation + state.json: %APPDATA%/Fernal/state.json on Windows.

    The application name must be set (QCoreApplication.setApplicationName) before the first call.
    """
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "state.json"


def params_moved(old, new, threshold: float = REGEN_THRESHOLD) -> bool:
    """True if `new` differs from the last-used `old` Params enough to regenerate the skeleton.

    Any numeric field that moved by at least `threshold` of its range counts; so does a missing
    `old`. Non-numeric fields other than the tropism vector are compared for equality.
    """
    if old is None:
        return True
    for f in dataclasses.fields(new):
        a, b = getattr(old, f.name), getattr(new, f.name)
        if f.name == "tropism":
            span = TROPISM_RANGE[1] - TROPISM_RANGE[0]
            if any(abs(float(x) - float(y)) >= threshold * span for x, y in zip(a, b)):
                return True
        elif isinstance(b, (int, float)) and not isinstance(b, bool):
            lo, hi = PARAM_RANGES.get(f.name, (0.0, max(abs(a), abs(b), 1.0)))
            if abs(b - a) >= threshold * (hi - lo):
                return True
        elif a != b:
            return True
    return False


def clamp_window(rect: dict, screens: list, min_visible: int = WINDOW_MIN_VISIBLE) -> dict:
    """Keep a saved window rect on a screen; otherwise center it on the primary screen.

    `screens` is a list of (x, y, w, h) available-geometry tuples, primary first. A rect is kept
    when at least `min_visible` pixels (or its whole width/height if smaller) overlap one screen.
    An unusable size falls back to the default window size.
    """
    default = sim.PlantState().window
    x, y = int(rect.get("x", default["x"])), int(rect.get("y", default["y"]))
    w, h = int(rect.get("w", default["w"])), int(rect.get("h", default["h"]))
    if w < WINDOW_MIN_SIZE or h < WINDOW_MIN_SIZE:
        w, h = default["w"], default["h"]
    if not screens:
        return dict(rect, x=x, y=y, w=w, h=h)
    for sx, sy, sw, sh in screens:
        overlap_x = min(x + w, sx + sw) - max(x, sx)
        overlap_y = min(y + h, sy + sh) - max(y, sy)
        if overlap_x >= min(min_visible, w) and overlap_y >= min(min_visible, h):
            return dict(rect, x=x, y=y, w=w, h=h)
    sx, sy, sw, sh = screens[0]
    w, h = min(w, sw), min(h, sh)
    return dict(rect, x=sx + (sw - w) // 2, y=sy + (sh - h) // 2, w=w, h=h)


def place_beside(window_rect, panel_size, screens: list, index: int = 0) -> QPoint:
    """Top-left corner for a panel next to the overlay window.

    `window_rect` is (x, y, w, h) or a QRect, `panel_size` is (w, h) or a QSize and `screens` holds
    available-geometry tuples (x, y, w, h) as from `_screen_rects`. The panel goes on the right of the window
    if it fits on the window's screen, otherwise on its left, top aligned with the window. Panel number
    `index` is shifted by PANEL_CASCADE px per step (away from the window in x, down in y). The result is
    kept on the screen.
    """
    wx, wy, ww, wh = (window_rect.x(), window_rect.y(), window_rect.width(), window_rect.height()) \
        if hasattr(window_rect, "width") else window_rect
    pw, ph = (panel_size.width(), panel_size.height()) if hasattr(panel_size, "width") else panel_size
    cx, cy = wx + ww / 2, wy + wh / 2
    screen = next((s for s in screens if s[0] <= cx < s[0] + s[2] and s[1] <= cy < s[1] + s[3]),
                  screens[0] if screens else None)
    right, left = wx + ww + PANEL_GAP, wx - PANEL_GAP - pw
    side = 1
    if screen is not None and right + pw > screen[0] + screen[2] and left >= screen[0]:
        side = -1
    x = (right if side > 0 else left) + side * PANEL_CASCADE * index
    y = wy + PANEL_CASCADE * index
    if screen is not None:
        sx, sy, sw, sh = screen
        x = max(sx, min(x, sx + sw - pw))
        y = max(sy, min(y, sy + sh - ph))
    return QPoint(round(x), round(y))


def effective_radiation(radiation: "float | None", elevation_deg: float) -> float:
    """Radiation (0..1) the plant actually receives: never more than the sky allows.

    `radiation` is the last fetched value, or None before any successful fetch, in which case it is
    synthesized from the sun so an offline plant never lives in permanent darkness.
    """
    if radiation is None:
        radiation = max(0.0, math.sin(math.radians(elevation_deg))) * OFFLINE_RADIATION
    return max(0.0, min(float(radiation), sky.day_factor(elevation_deg)))


def mean_radiation(radiation: "float | None", lat: float, lon: float, end: float, span: float,
                   max_samples: int = 168) -> float:
    """Average effective radiation over the `span` seconds before unix time `end`.

    Used to replay time away: a constant radiation would treat a whole absence as noon or midnight.
    Samples hourly (at most `max_samples`, at least one in the middle of the span).
    """
    span = max(0.0, span)
    count = max(1, min(max_samples, int(span // 3600.0) + 1))
    total = 0.0
    for i in range(count):
        when = datetime.fromtimestamp(end - span + span * (i + 0.5) / count, timezone.utc)
        elevation, _ = sky.sun_position(lat, lon, when)
        total += effective_radiation(radiation, elevation)
    return total / count


def local_time_at(hour: float, now: "datetime | None" = None) -> datetime:
    """Timezone-aware datetime for today at `hour` (fractional hours allowed) in the local timezone."""
    now = now or datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=hour)


def pot_url(path: str) -> str:
    """File URL for an existing pot model, "" (default pot) when the path is empty or missing."""
    if path and Path(path).is_file():
        return QUrl.fromLocalFile(str(Path(path))).toString()
    return ""


def _screen_rects() -> list:
    """Available geometry of every screen as (x, y, w, h), primary first."""
    primary = QGuiApplication.primaryScreen()
    screens = ([primary] if primary is not None else []) + [
        s for s in QGuiApplication.screens() if s is not primary
    ]
    rects = [s.availableGeometry() for s in screens]
    return [(r.x(), r.y(), r.width(), r.height()) for r in rects]


# ---- weather worker ------------------------------------------------------------------------


class _WeatherSignals(QObject):
    done = Signal(object)  # dict from sky.fetch_weather, or None


class _WeatherJob(QRunnable):
    """Fetches the weather off the main thread; the result travels back through a queued signal."""

    def __init__(self, lat: float, lon: float, signals: _WeatherSignals):
        super().__init__()
        self._lat, self._lon, self._signals = lat, lon, signals

    def run(self):
        result = None
        try:
            result = sky.fetch_weather(self._lat, self._lon)  # returns None on any failure
        finally:
            self._signals.done.emit(result)


class _GeocodeSignals(QObject):
    done = Signal(str, object)  # the name that was asked for, dict from sky.geocode or None


class _GeocodeJob(QRunnable):
    """Looks a city up off the main thread; the result travels back through a queued signal."""

    def __init__(self, name: str, signals: _GeocodeSignals):
        super().__init__()
        self._name, self._signals = name, signals

    def run(self):
        result = None
        try:
            result = sky.geocode(self._name)  # returns None on any failure
        finally:
            self._signals.done.emit(self._name, result)


# ---- controller ----------------------------------------------------------------------------


class App(QObject):
    """Owns the state, the geometries, the window, the menu/tray and every timer.

    Needs a running QApplication (created by __main__).
    """

    def __init__(self, args):
        super().__init__()
        self.args = args
        self.screenshot_path = getattr(args, "screenshot", None)
        self.full_age = 0.0                 # max(birth_age + grow_hours) over the skeleton
        self.skeleton = None
        self.click_through = False
        self.exit_code = 0
        self._qapp = QApplication.instance()
        self._params = None                 # Params used for the current skeleton
        self._gen_key = None                # (theme, seed) of the current skeleton
        self._mature_age = 0.0              # full_age extended by the leaf and fruit unfurl time
        self._built_age = -1.0              # plant age of the meshes now on the GPU
        self._last_build = 0.0
        self._last_tick = time.monotonic()
        self._elevation = 0.0
        self._weather_ok = False            # a fetch succeeded in this session
        self._fetching = False
        self._weather_stale = False         # the place changed while a fetch was running
        self._panels = {}                   # key -> GlassPanel, created on first use and kept
        self._placed = 0                    # panels placed so far (cascade index)
        self._shot_armed = False
        self._shot_done = False
        self._state_path = None
        self.tray = None

        hour = getattr(args, "hour", None)
        self._fixed_time = local_time_at(hour) if (self.screenshot_path and hour is not None) else None
        if self.screenshot_path:
            self.state = self._screenshot_state()
        else:
            self.state = self._load_state()

        self.bridge = overlay.Bridge()
        self.geometries = {key: mesh.PlantGeometry() for key in ("branch", "leaf", "fruit")}
        self._apply_theme()
        self._apply_pot()
        self._update_sky()
        self._update_bridge()

        assets_url = QUrl.fromLocalFile(str(ASSETS_DIR) + "/")
        self.window = overlay.OverlayWindow(self.bridge, self.geometries, assets_url)
        self._place_window()
        self.window.hovered.connect(self._on_touch)
        self.window.clicked.connect(self._on_touch)
        self.window.orbitRequested.connect(self._on_orbit)
        self.window.zoomRequested.connect(self._on_zoom)
        self.window.menuRequested.connect(self._on_menu_requested)
        self.window.debugRequested.connect(self.open_debug)

        self.menu, self.actions = overlay.build_menu(None, self.state.theme, self.click_through)
        self._wire_menu()

        self._regen_timer = QTimer(self)
        self._regen_timer.setSingleShot(True)
        self._regen_timer.setInterval(REGEN_MS)
        self._regen_timer.timeout.connect(self._generate_now)
        self._heater_timer = QTimer(self)
        self._heater_timer.setSingleShot(True)
        self._heater_timer.setInterval(HEATER_REGEN_MS)
        self._heater_timer.timeout.connect(self.regenerate)
        self._tick_timer = self._make_timer(TICK_MS, self._tick)
        self._save_timer = self._make_timer(SAVE_MS, self.save_state)
        self._weather_timer = self._make_timer(WEATHER_MS, self._start_weather_fetch)
        self._weather_signals = _WeatherSignals(self)
        self._weather_signals.done.connect(self._on_weather)
        self._geocode_signals = _GeocodeSignals(self)
        self._geocode_signals.done.connect(self._on_geocode)

        if not self.screenshot_path:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = overlay.Tray(QIcon(str(ASSETS_DIR / "tray.png")), self.menu)
            else:
                log.warning("no system tray available")
            self._qapp.aboutToQuit.connect(self._shutdown)

        self._generate_now()

    # ---- construction helpers -------------------------------------------------------------

    def _make_timer(self, interval_ms, callback):
        timer = QTimer(self)
        timer.setInterval(interval_ms)
        timer.timeout.connect(callback)
        return timer

    def _screenshot_state(self) -> "sim.PlantState":
        """Fresh state from the arguments; never touches the state file."""
        args = self.args
        state = sim.PlantState()
        state.seed = args.seed if getattr(args, "seed", None) is not None else 1
        state.theme = getattr(args, "theme", None) or "normal"
        state.age = args.age if getattr(args, "age", None) is not None else MATURE_AGE
        elevation, _ = sky.sun_position(state.lat, state.lon, self._now())
        state.env.light = effective_radiation(None, elevation)
        state.vitality = sim.vitality_of(state.env)
        return state

    def _load_state(self) -> "sim.PlantState":
        """Load the state file, apply first-run defaults or replay the time away, clamp the window."""
        args = self.args
        self._state_path = Path(args.state) if getattr(args, "state", None) else default_state_path()
        state = sim.load(self._state_path)
        if state.last_saved <= 0:   # no file, or a corrupt one that was moved to .bak
            seed = getattr(args, "seed", None)
            state.seed = seed if seed is not None else random.randrange(1, 2**31)
            state.theme = getattr(args, "theme", None) or "normal"
            age = getattr(args, "age", None)
            state.age = age if age is not None else FIRST_RUN_AGE
            state.controls.time_scale = FIRST_RUN_TIME_SCALE
        else:
            elapsed = time.time() - state.last_saved
            if elapsed > 0.0:
                radiation = mean_radiation(None, state.lat, state.lon, time.time(),
                                           min(elapsed, CATCH_UP_CAP))
                outdoor = dataclasses.replace(state.outdoor, radiation=radiation)
                sim.catch_up(state, outdoor, elapsed)
        state.window = clamp_window(state.window, _screen_rects())
        return state

    def _place_window(self):
        w = self.state.window
        self.window.setGeometry(w["x"], w["y"], w["w"], w["h"])

    def _wire_menu(self):
        actions = self.actions
        for name in themes.THEMES:
            actions["theme:" + name].triggered.connect(lambda _checked=False, n=name: self.set_theme(n))
        actions["clickthrough"].triggered.connect(self.set_click_through)
        actions["quit"].triggered.connect(self._qapp.quit)
        for key in ("water", "nutrients", "climate", "spray", "settings", "pot"):
            actions[key].triggered.connect(lambda _checked=False, k=key: self._on_tool(k))

    # ---- sky and bridge -------------------------------------------------------------------

    def _now(self) -> datetime:
        return self._fixed_time or datetime.now().astimezone()

    def _update_sky(self) -> float:
        """Sun elevation/azimuth for now (or the screenshot hour) into the bridge."""
        elevation, azimuth = sky.sun_position(self.state.lat, self.state.lon, self._now())
        self._elevation = elevation
        self.bridge.sunElevation = elevation
        self.bridge.sunAzimuth = azimuth
        self.bridge.dayFactor = sky.day_factor(elevation)
        return elevation

    def _update_bridge(self):
        self.bridge.vitality = self.state.vitality
        self.bridge.windStrength = WIND_STRENGTH

    def _apply_theme(self):
        t = themes.theme(self.state.theme)
        b = self.bridge
        b.theme = self.state.theme
        b.barkColor = t["bark"]
        b.emissiveColor = t["bark_emissive"]
        b.leafColor = t["leaf"]
        b.leafEmissive = t["leaf_emissive"]
        b.fruitColor = t["fruit_color"]
        b.accentColor = t["accent"]
        b.glowEnabled = t["glow"]
        b.particlesEnabled = True
        for panel in self._panels.values():
            panel.set_accent(t["accent"])

    def _apply_pot(self):
        self.bridge.potSource = pot_url(self.state.pot_path)

    @property
    def mature_age(self) -> float:
        """Plant age at which the current skeleton, its leaves and its fruits are fully grown."""
        return self._mature_age

    def sun_dir(self) -> tuple:
        """Unit vector toward the sun at local 13:00 today: x = east, y = up, z = south."""
        elevation, azimuth = sky.sun_position(self.state.lat, self.state.lon, local_time_at(13.0))
        el, az = math.radians(max(elevation, 5.0)), math.radians(azimuth)  # polar winter: stay above the horizon
        return (math.cos(el) * math.sin(az), math.sin(el), -math.cos(el) * math.cos(az))

    def _effective_outdoor(self, elevation: float) -> "sim.Outdoor":
        """Copy of the last weather with radiation limited by the sun (synthesized before a fetch)."""
        radiation = self.state.outdoor.radiation if self._weather_ok else None
        return dataclasses.replace(self.state.outdoor, radiation=effective_radiation(radiation, elevation))

    # ---- skeleton and meshes --------------------------------------------------------------

    def regenerate(self, immediate: bool = False) -> None:
        """Request a new skeleton; requests within 50 ms collapse into one (`immediate` skips the wait)."""
        if immediate:
            self._regen_timer.stop()
            self._generate_now()
        elif not self._regen_timer.isActive():
            self._regen_timer.start()

    def _generate_now(self):
        st = self.state
        params = tree.params_from(st.env, st.vitality, self.sun_dir(), st.theme)
        skel = tree.generate(st.seed, params)
        self.skeleton, self._params = skel, params
        self._gen_key = (st.theme, st.seed)
        self.full_age = max((s.birth_age + s.grow_hours for s in skel.segments), default=0.0)
        ends = [self.full_age]
        if len(skel.leaf_birth):
            ends.append(float(skel.leaf_birth.max()) + mesh.LEAF_GROW_HOURS)
        if len(skel.fruit_birth):
            ends.append(float(skel.fruit_birth.max()) + mesh.FRUIT_GROW_HOURS)
        self._mature_age = max(ends)
        self.rebuild_meshes()

    def rebuild_meshes(self) -> None:
        """Arrays for the current plant age into the three geometries."""
        if self.skeleton is None:
            return
        skel, age = self.skeleton, self.state.age
        self.geometries["branch"].set_arrays(mesh.branch_arrays(skel, age))
        self.geometries["leaf"].set_arrays(mesh.leaf_arrays(skel, age, self._params.leaf_size))
        self.geometries["fruit"].set_arrays(mesh.fruit_arrays(skel, age))
        self._built_age = age
        self._last_build = time.monotonic()

    def _grow_meshes(self):
        """Growth animation: rebuild at most every 100 ms while the last build was not fully grown."""
        if self.skeleton is None or self._built_age >= self._mature_age:
            return
        if self.state.age == self._built_age or time.monotonic() - self._last_build < MESH_MIN_INTERVAL:
            return
        self.rebuild_meshes()

    def _needs_regenerate(self) -> bool:
        st = self.state
        if self._gen_key != (st.theme, st.seed):
            return True
        return params_moved(self._params, tree.params_from(st.env, st.vitality, self.sun_dir(), st.theme))

    # ---- timers ---------------------------------------------------------------------------

    @Slot()
    def _tick(self):
        now = time.monotonic()
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now
        outdoor = self._effective_outdoor(self._update_sky())
        if dt > CATCH_UP_GAP:
            sim.catch_up(self.state, outdoor, dt)
        else:
            sim.step(self.state, outdoor, dt)
        self._update_bridge()
        if self._needs_regenerate():
            self.regenerate()
        self._grow_meshes()
        self._refresh_panels()

    def _start_weather_fetch(self):
        if self._fetching:
            self._weather_stale = True   # refetch once the running request is done
            return
        self._fetching = True
        self._weather_stale = False
        QThreadPool.globalInstance().start(
            _WeatherJob(self.state.lat, self.state.lon, self._weather_signals))

    @Slot(object)
    def _on_weather(self, weather):
        self._fetching = False
        if self._weather_stale:   # the answer belongs to a place the user has left
            self._start_weather_fetch()
            return
        if not weather:
            return  # offline or an API error: keep the last values
        try:
            self.state.outdoor = sim.Outdoor(**weather)
        except (TypeError, ValueError):
            log.warning("unusable weather data: %r", weather)
            return
        self._weather_ok = True

    def save_state(self) -> None:
        """Write state.json with the current window geometry (no-op in screenshot mode)."""
        if self._state_path is None:
            return
        g = self.window.geometry()
        self.state.window = {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}
        try:
            sim.save(self.state, self._state_path)
        except OSError as exc:
            log.warning("could not save %s: %s", self._state_path, exc)

    def _shutdown(self):
        self.save_state()
        for panel in self._panels.values():
            panel.close()
        if self.tray is not None:
            self.tray.hide()

    # ---- window and menu handlers ---------------------------------------------------------

    def _on_touch(self):
        sim.touch(self.state)

    def _on_orbit(self, dx, dy):
        b = self.bridge
        b.cameraYaw = b.cameraYaw + dx * ORBIT_YAW_PER_PX
        b.cameraPitch = _clamp(b.cameraPitch - dy * ORBIT_PITCH_PER_PX, *PITCH_RANGE)

    def _on_zoom(self, delta):
        b = self.bridge
        b.cameraDistance = _clamp(b.cameraDistance - delta * ZOOM_PER_DELTA, *ZOOM_RANGE)

    def _on_menu_requested(self, pos):
        self.menu.popup(pos)

    def _on_tool(self, key):
        """Menu entries: the four tools and settings open a panel, the pot entry asks for a model file."""
        if key == "pot":
            self.choose_pot()
        else:
            self.open_panel(key)

    # ---- panels ---------------------------------------------------------------------------

    def open_panel(self, key: str) -> None:
        """Show panel `key` (water, nutrients, climate, spray, settings or debug), creating it on first use.

        A new panel is placed beside the overlay window; a panel that already exists keeps its position.
        """
        panel = self._panels.get(key)
        fresh = panel is None
        if fresh:
            panel = self._panels[key] = self._create_panel(key)
        if key == "settings":
            self._sync_settings()
        else:
            self._refresh_panel(key)
        if fresh:
            self._place_panel(panel)
        if panel.isVisible():   # no second fade-in: just bring it forward
            panel.raise_()
            panel.activateWindow()
        else:
            panel.show_animated()

    def open_debug(self) -> None:
        self.open_panel("debug")

    def _create_panel(self, key: str) -> tools.GlassPanel:
        accent = themes.theme(self.state.theme)["accent"]
        if key == "settings":
            panel = tools.SettingsPanel(accent)
            panel.themeChanged.connect(self.set_theme)
            panel.potChosen.connect(self.set_pot)
            panel.cityChanged.connect(self.set_city)
            panel.sizeChanged.connect(self.set_window_size)
        elif key == "debug":
            panel = debug_panel.DebugPanel(accent)
            panel.changed.connect(self._on_debug_changed)
        else:
            panel = tools.ToolPanel(key, accent)
            panel.action.connect(self._on_tool_action)
        QShortcut(QKeySequence(DEBUG_SHORTCUT), panel).activated.connect(self.open_debug)
        return panel

    def _place_panel(self, panel: tools.GlassPanel) -> None:
        g = self.window.geometry()
        panel.adjustSize()
        panel.move(place_beside((g.x(), g.y(), g.width(), g.height()), (panel.width(), panel.height()),
                                _screen_rects(), self._placed))
        self._placed += 1

    def _refresh_panel(self, key: str) -> None:
        """Gauges, captions and sliders of one panel from the current state (not the settings fields)."""
        panel = self._panels.get(key)
        if panel is None or key == "settings":
            return
        st = self.state
        env = st.env
        caption = None
        if key == "water":
            panel.set_value(env.water)
        elif key == "nutrients":
            panel.set_value(env.nutrients)
        elif key == "spray":
            panel.set_value(env.humidity)
            caption = ""   # the gauge row already reads out the humidity
        elif key == "climate":
            if not panel.slider.isSliderDown():   # never fight the user's drag
                panel.set_value((st.controls.heater + 10.0) / 20.0)
            caption = f"현재 {env.temperature:.1f}°C"
        elif key == "debug":
            panel.set_state(st, self.mature_age)
        if caption is not None and panel.caption_label.text() != caption:
            panel.set_caption(caption)

    def _refresh_panels(self) -> None:
        for key, panel in self._panels.items():
            if panel.isVisible():
                self._refresh_panel(key)

    def _sync_settings(self) -> None:
        panel = self._panels.get("settings")
        if panel is not None:
            g = self.window.geometry()
            panel.set_values(self.state.theme, self.state.pot_path, self.state.city, g.width(), g.height())

    def _apply_controls(self) -> None:
        """Make heater and pinned values count now: a zero-length step recomputes the environment."""
        sim.step(self.state, self._effective_outdoor(self._elevation), 0.0)
        self._update_bridge()

    @Slot(str, float)
    def _on_tool_action(self, name: str, value: float) -> None:
        st = self.state
        if name == "water":
            sim.water(st)
        elif name == "feed":
            sim.feed(st)
        elif name == "spray":
            sim.spray(st)
        elif name == "heater":
            st.controls.heater = _clamp(float(value), -10.0, 10.0)
        else:
            return
        self._apply_controls()
        self._refresh_panels()
        if name == "heater":   # a drag sends ~10 updates a second; a skeleton takes ~100 ms, so wait for a pause
            self._heater_timer.start()
        else:
            self.regenerate()

    # ---- debug tool -----------------------------------------------------------------------

    def _on_debug_changed(self, change: dict) -> None:
        st = self.state
        if "time_scale" in change:
            st.controls.time_scale = max(0.0, float(change["time_scale"]))
        if "age" in change:
            st.age = max(0.0, float(change["age"]))
            self.rebuild_meshes()
        if "growth_percent" in change:
            st.age = _clamp(float(change["growth_percent"]), 0.0, 100.0) / 100.0 * self.mature_age
            self.rebuild_meshes()
        if change.get("reseed"):
            old = st.seed
            while st.seed == old:
                st.seed = random.randrange(1, 2**31)
            self.regenerate(immediate=True)
        if "force" in change:
            for name, value in change["force"].items():
                if not hasattr(st.env, name):
                    continue
                if value is None:
                    st.controls.forced.pop(name, None)
                else:
                    st.controls.forced[name] = float(value)
            self._apply_controls()
            self.regenerate()
        if change.get("reset"):
            self._reset_plant()
        self._refresh_panels()

    def _reset_plant(self) -> None:
        """A fresh plant with first-run age and speed; place, theme, pot and the last weather stay."""
        old = self.state
        fresh = sim.PlantState(window=old.window, theme=old.theme, pot_path=old.pot_path, city=old.city,
                               lat=old.lat, lon=old.lon, outdoor=old.outdoor)
        fresh.seed = random.randrange(1, 2**31)
        fresh.age = FIRST_RUN_AGE
        fresh.controls.time_scale = FIRST_RUN_TIME_SCALE
        self.state = fresh
        self._apply_controls()
        self.regenerate(immediate=True)

    # ---- settings -------------------------------------------------------------------------

    def set_theme(self, name: str) -> None:
        if name not in themes.THEMES:
            return
        if name != self.state.theme:
            self.state.theme = name
            self._apply_theme()
            self.regenerate()
        self._sync_menu()
        panel = self._panels.get("settings")   # the menu may have changed it; keep the other fields as typed
        if panel is not None and panel.theme_combo.currentData() != name:
            was = panel.theme_combo.blockSignals(True)
            panel.theme_combo.setCurrentIndex(panel.theme_combo.findData(name))
            panel.theme_combo.blockSignals(was)

    def choose_pot(self) -> None:
        """Menu entry "화분 바꾸기…": pick a .glb/.gltf file, then use it."""
        path = self._ask_pot_file()
        if path:
            self.set_pot(path)

    def _ask_pot_file(self) -> str:
        path, _ = QFileDialog.getOpenFileName(None, "화분 파일 선택", self.state.pot_path, "3D 모델 (*.glb *.gltf)")
        return path

    def set_pot(self, path: str) -> None:
        """Use the pot model at `path`; "" or a missing file shows the default pot."""
        missing = bool(path) and not Path(path).is_file()
        self.state.pot_path = "" if missing else path
        self._apply_pot()
        panel = self._panels.get("settings")
        if panel is not None:
            panel.set_pot_path(self.state.pot_path)
            if missing:
                panel.set_status(POT_MISSING)
            elif panel.status_label.text() == POT_MISSING:
                panel.set_status("")

    def set_city(self, name: str) -> None:
        """Look the city up in the background; `_on_geocode` applies the answer."""
        panel = self._panels.get("settings")
        if panel is not None:
            panel.set_status("찾는 중…")
        QThreadPool.globalInstance().start(_GeocodeJob(name, self._geocode_signals))

    @Slot(str, object)
    def _on_geocode(self, name: str, place):
        panel = self._panels.get("settings")
        try:
            city, lat, lon = str(place["city"]), float(place["lat"]), float(place["lon"])
        except (TypeError, KeyError, ValueError):
            if panel is not None:
                panel.set_status(CITY_MISSING)
            return
        st = self.state
        st.city, st.lat, st.lon = city, lat, lon
        if panel is not None:
            panel.set_status(f"위치: {city}")
        self._update_sky()
        self.regenerate()
        self._start_weather_fetch()

    def set_window_size(self, w: int, h: int) -> None:
        self.window.resize(int(w), int(h))
        self.state.window = dict(self.state.window, w=int(w), h=int(h))

    def set_click_through(self, on: bool) -> None:
        self.click_through = bool(on)
        self.window.set_click_through(self.click_through)
        self._sync_menu()

    def _sync_menu(self):
        for name in themes.THEMES:
            self.actions["theme:" + name].setChecked(name == self.state.theme)
        self.actions["clickthrough"].setChecked(self.click_through)

    # ---- run ------------------------------------------------------------------------------

    def run(self) -> int:
        """Show the window and run the event loop; screenshot mode exits after writing the PNG."""
        if self.window.status() == QQuickView.Status.Error:
            return 2
        if self.screenshot_path:
            return self._run_screenshot()
        self.window.show()
        if self.tray is not None:
            self.tray.show()
        self._last_tick = time.monotonic()
        for timer in (self._tick_timer, self._save_timer, self._weather_timer):
            timer.start()
        self._start_weather_fetch()
        return self._qapp.exec()

    def _run_screenshot(self) -> int:
        # frameSwapped fires on the render thread; the queued connection hops to the main thread.
        self.window.frameSwapped.connect(self._on_frame_swapped, Qt.ConnectionType.QueuedConnection)
        QTimer.singleShot(SCREENSHOT_TIMEOUT_MS, self._screenshot_timeout)
        self.window.show()
        self._qapp.exec()
        return self.exit_code

    @Slot()
    def _on_frame_swapped(self):
        if not self._shot_armed:
            self._shot_armed = True
            QTimer.singleShot(SCREENSHOT_SETTLE_MS, self._take_screenshot)

    def _take_screenshot(self):
        path = Path(self.screenshot_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.window.grab_png(str(path)):
            print(f"saved {path}", flush=True)
        else:
            print(f"could not write {path}", file=sys.stderr, flush=True)
            self.exit_code = 3
        self._shot_done = True
        self._qapp.quit()

    def _screenshot_timeout(self):
        if not self._shot_done:
            print("screenshot timed out: no frame was rendered", file=sys.stderr, flush=True)
            self.exit_code = 4
            self._qapp.quit()

