# Fernal Implementation Plan

> **For agentic workers:** This plan is executed as Workflow runs, one per phase. Each task is self-contained: read the spec, this plan's "Interface contracts" section and your task block, then implement, verify and commit. Tasks use checkbox (`- [ ]`) syntax for tracking. Granularity is deliberately moderate (user request): task-level, not minute-level steps.

**Goal:** A transparent desktop overlay that grows a procedurally generated 3D plant driven by environment values, with Qt Widgets tool panels, three themes and day/night lighting, in 16 working hours.

**Architecture:** Pure-Python simulation (`sim`) and skeleton generation (`tree`) feed numpy mesh builders (`mesh`) that push vertex arrays into `QQuick3DGeometry` objects exposed to a single QML scene. A controller (`app`) owns state and timers; the overlay window, tray, menus and tool panels are Qt Widgets/QWindow code in Python.

**Tech Stack:** Python 3.14, PySide6 >= 6.11 (QtQuick3D, QtQuick3D.Helpers, QtQuick3D.Particles3D, QtWidgets), numpy, pytest. Open-Meteo HTTP API via `urllib`.

**Spec:** `docs/superpowers/specs/2026-10-07-fernal-design.md`

## Global Constraints

- Python 3.14, PySide6 >= 6.11, numpy. No other runtime dependency. Dev dependency: pytest.
- Only `fernal/qml/Scene.qml` (and its shaders under `fernal/qml/shaders/`) is QML. Every other UI element is Qt Widgets in Python.
- Windows 11. Overlay flags `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`. Transparent window requires `QQuickWindow.setDefaultAlphaBuffer(True)` before the view is created and `view.setColor(Qt.transparent)`.
- UI copy in Korean. Code, comments, docs and commit messages in English.
- State file `%APPDATA%\Fernal\state.json` (use `QStandardPaths.AppDataLocation`).
- Textures are committed PNGs under `fernal/assets/`, generated once by `scripts/make_textures.py`.
- Scene units: centimeters. Trunk length 100. Y is up. Tree base at the origin; the pot sits below it.
- Models: visual tasks (T4b, T5, T8, T11) run on Opus. Logic tasks run on Sonnet. Fable only after the user approves it for a specific task.
- Budget: 16 hours over two days. Cut order if late: particles -> wind shader -> falling leaf -> fruits.
- Commit after each task: `feat(<module>): <summary>`.

## Review Focus

1. No network (offline, DNS failure, timeout): `sky.fetch_weather` returns `None`, the app keeps the last `Outdoor` values and never raises. Pinned by `test_sky.py::test_fetch_weather_failure_returns_none` (T3).
2. Corrupt or old-schema `state.json`: `sim.load` moves it to `state.json.bak` and returns a fresh `PlantState`; unknown keys are ignored, missing keys get defaults. Pinned by `test_sim.py::test_load_corrupt_file_backs_up` and `test_from_dict_ignores_unknown_keys` (T2).
3. Months away: `sim.catch_up` caps elapsed time at 7 days and finishes in under one second. Pinned by `test_sim.py::test_catch_up_is_capped` (T2).
4. Slider spam: regeneration is coalesced by a 50 ms single-shot timer so the UI stays responsive. Checked manually in T10 by dragging the climate slider for 5 seconds.
5. Missing pot file or off-screen saved window geometry: pot falls back to the default cylinder, window is re-centered on the primary screen. Checked manually in T10 with a bogus pot path and `window.x = 99999`.

---

## File map

| Path | Owner task | Responsibility |
|---|---|---|
| `requirements.txt`, `CLAUDE.md`, `.gitignore` | T0 | deps, project rules |
| `fernal/__init__.py`, `fernal/__main__.py` | T0 (stub), T7 (final) | entry point, argparse |
| `scripts/spike_overlay.py`, `scripts/spike.qml` | T0 | throwaway transparency + glow + shadow spike |
| `fernal/tree.py`, `tests/test_tree.py` | T1 | skeleton generation |
| `fernal/sim.py`, `tests/test_sim.py` | T2 | simulation, persistence |
| `fernal/sky.py`, `tests/test_sky.py` | T3 | sun position, weather |
| `fernal/mesh.py`, `tests/test_mesh.py` | T4 | vertex arrays, `PlantGeometry` |
| `scripts/make_textures.py`, `fernal/assets/*.png` | T4b | textures, tray icon |
| `fernal/themes.py` | T5 | theme table |
| `fernal/qml/Scene.qml`, `fernal/qml/shaders/*` | T5 | 3D scene |
| `scripts/preview_scene.py` | T5 | throwaway scene harness |
| `fernal/overlay.py` | T6 | window, bridge, menu, tray |
| `fernal/app.py` | T7 | controller, timers, persistence, screenshot mode |
| `fernal/tools.py` | T8 | glass panel, tool panels, settings |
| `fernal/debug_panel.py` | T9 | hidden debug panel + wiring into app |
| `docs/screenshots/*.png` | T10, T11 | evidence |
| `README.md` | T12 | usage, screenshots |

## Interface contracts

Every task implements exactly these names and signatures. Tasks running in parallel depend on them.

```python
# fernal/sim.py  (no Qt, no numpy)
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Env:
    water: float = 0.6
    nutrients: float = 0.5
    temperature: float = 22.0   # degC, effective = outdoor + heater
    humidity: float = 0.5
    light: float = 0.0          # 0..1, 0 at night
    affection: float = 0.5

@dataclass
class Outdoor:
    temperature: float = 20.0   # degC
    humidity: float = 0.5       # 0..1
    radiation: float = 0.0      # 0..1 = shortwave W/m2 / 800, clamped

@dataclass
class Controls:
    heater: float = 0.0         # -10..+10 degC
    time_scale: float = 1.0
    forced: dict = field(default_factory=dict)   # {"water": 0.3} pins an Env field (debug tool)

@dataclass
class PlantState:
    seed: int = 1
    age: float = 0.0            # plant hours
    env: Env = field(default_factory=Env)
    controls: Controls = field(default_factory=Controls)
    vitality: float = 1.0
    theme: str = "normal"       # "erdtree" | "normal" | "fruit"
    pot_path: str = ""          # "" = default pot
    city: str = "Seoul"
    lat: float = 37.57
    lon: float = 126.98
    window: dict = field(default_factory=lambda: {"x": 100, "y": 100, "w": 420, "h": 640})
    outdoor: Outdoor = field(default_factory=Outdoor)   # last fetched weather; `step` never modifies it
    last_saved: float = 0.0     # unix seconds

OPTIMUM = {"water": (0.4, 0.8), "nutrients": (0.3, 0.9), "temperature": (17.0, 27.0),
           "humidity": (0.35, 0.8), "light": (0.3, 1.0), "affection": (0.3, 1.0)}

def vitality_of(env: Env) -> float: ...            # 0..1, weighted distance from OPTIMUM bands
def growth_rate(env: Env, vitality: float) -> float: ...  # bell(temperature, 22, 10) * (0.3 + 0.7*light) * vitality
def step(state: PlantState, outdoor: Outdoor, dt_seconds: float) -> None: ...
def catch_up(state: PlantState, outdoor: Outdoor, elapsed_seconds: float,
             slice_seconds: float = 600.0, cap_seconds: float = 7 * 86400.0) -> None: ...
def water(state: PlantState, amount: float = 0.2) -> None: ...
def feed(state: PlantState, amount: float = 0.3) -> None: ...
def spray(state: PlantState, amount: float = 0.15) -> None: ...
def touch(state: PlantState, amount: float = 0.05) -> None: ...
def to_dict(state: PlantState) -> dict: ...
def from_dict(d: dict) -> PlantState: ...
def save(state: PlantState, path: Path) -> None: ...
def load(path: Path) -> PlantState: ...            # corrupt -> rename to .bak, return PlantState()
```

Dynamics inside `step` (h = dt_seconds / 3600, all values clamped to range):
- `env.temperature = outdoor.temperature + controls.heater`; `env.light = outdoor.radiation`
- `env.water -= h * (0.01 + 0.02 * env.light + 0.001 * max(0, env.temperature - 20))`
- `env.nutrients -= h * 0.1 / 24`; `env.affection -= h * 0.1 / 24`
- humidity target `= clamp(0.3 + 0.5*env.water + 0.2*outdoor.humidity - 0.15*env.light - 0.005*(env.temperature - 22))`; `env.humidity += (target - env.humidity) * min(1, 0.5*h)`
- apply `controls.forced` overrides; `state.vitality = vitality_of(env)`
- `state.age += h * controls.time_scale * growth_rate(env, vitality)`

```python
# fernal/tree.py  (numpy only; env is duck-typed, do NOT import sim)
import numpy as np
from dataclasses import dataclass

@dataclass
class Params:
    branch_factor: float = 2.4      # mean children per segment, 1.5..3.5
    length_ratio: float = 0.72      # child/parent length, 0.6..0.85
    spread_deg: float = 35.0        # 20..60
    droop: float = 0.0              # 0..1 downward bend
    leaf_density: float = 0.7       # 0..1
    leaf_size: float = 1.0          # 0.5..1.5 multiplier
    tropism: tuple = (0.0, 1.0, 0.0)
    tropism_strength: float = 0.2   # 0..1
    max_depth: int = 6              # 4..7
    trunk_length: float = 100.0     # cm
    fruit_ratio: float = 0.0        # 0..1 fraction of leaves that carry a fruit
    max_segments: int = 1500

@dataclass
class Segment:
    id: int
    parent: int                     # -1 for the trunk
    depth: int
    start: np.ndarray               # (3,) float32, fully grown
    end: np.ndarray                 # (3,) float32
    radius: float                   # cm at the base
    birth_age: float                # plant hours
    grow_hours: float

@dataclass
class Skeleton:
    segments: list                  # list[Segment], index == id
    leaf_pos: np.ndarray            # (L,3) f32
    leaf_dir: np.ndarray            # (L,3) f32 unit normal of the leaf quad
    leaf_birth: np.ndarray          # (L,) f32
    leaf_scale: np.ndarray          # (L,) f32 in 0.7..1.3
    fruit_pos: np.ndarray           # (F,3) f32
    fruit_birth: np.ndarray         # (F,) f32

def params_from(env, vitality: float, sun_dir: tuple, theme: str) -> Params: ...
def generate(seed: int, params: Params) -> Skeleton: ...
```

Generation rules: RNG per segment is `np.random.default_rng([seed, segment_id])`. Trunk: id 0, start (0,0,0), end (0, trunk_length, 0), radius `trunk_length*0.06`, birth 0, grow_hours 24. Children: count = `round(branch_factor + rng.uniform(-0.8, 0.8))` clamped 1..4; direction = parent direction rotated by `spread_deg * rng.uniform(0.6, 1.4)` around a random perpendicular axis, then `dir = normalize(dir + tropism_strength*tropism - droop*(0,1,0))`; length `= parent_len * length_ratio * rng.uniform(0.85, 1.15)`; radius `= parent_radius * 0.7`; `grow_hours = parent.grow_hours * 0.8`; `birth_age = parent.birth_age + parent.grow_hours * rng.uniform(0.6, 0.9)`. Stop at `max_depth` or `max_segments`. Leaves: for segments with `depth >= max_depth - 1`, `n = round(6 * leaf_density * rng.uniform(0.5, 1.5))` leaves spread along the last 60 % of the segment, `leaf_dir` = random unit vector biased to the segment's perpendicular, `leaf_birth = birth_age + grow_hours*0.5`, `leaf_scale = rng.uniform(0.7, 1.3)`. Fruits: `fruit_ratio` fraction of leaves (deterministic per leaf id), positioned 3 cm below the leaf.

```python
# fernal/mesh.py
Arrays = tuple  # (positions (N,3) f32, normals (N,3) f32, uv0 (N,2) f32, uv1 (N,2) f32, indices (M,) u32)

def growth(age: float, birth, hours):  ...        # smoothstep(clamp((age - birth) / hours, 0, 1)), works on arrays
def branch_arrays(skel, age: float) -> Arrays: ... # 6-sided tube per segment with growth > 0; length and radius scaled by growth
def leaf_arrays(skel, age: float, size: float) -> Arrays: ...   # one quad per leaf, 8 cm * size * leaf_scale * growth
def fruit_arrays(skel, age: float, radius: float = 4.0) -> Arrays: ...  # low-poly sphere (icosahedron, 1 subdivision)

class PlantGeometry(QQuick3DGeometry):
    def set_arrays(self, arrays) -> None: ...     # vertex data, index data, attributes Position/Normal/TexCoord0/TexCoord1, bounds, update()
```

`uv1 = (sway_phase, sway_weight)`: branches use `phase = (id * 0.618) % 1.0`, `weight = (depth / max_depth) * growth`; leaves use a per-leaf random phase and `weight = 1.0`. `uv0` for tubes: u around the ring, v = distance along the branch / 20 cm (tiling). Leaves: full 0..1 quad UVs.

```python
# fernal/themes.py
THEMES = {
    "erdtree": dict(label="세계수", bark="#8A6A2E", bark_emissive="#FFD27A", leaf="#FFD27A",
                    leaf_emissive="#FFB347", leaf_low="#B8A24A", glow=True, fruit=False,
                    fruit_color="#D9452B", particles="motes", accent="#E8C06A"),
    "normal":  dict(label="일반 나무", bark="#5A4030", bark_emissive="#000000", leaf="#4F8A3A",
                    leaf_emissive="#000000", leaf_low="#B8A24A", glow=False, fruit=False,
                    fruit_color="#D9452B", particles="leaf", accent="#5FA85A"),
    "fruit":   dict(label="열매 나무", bark="#5A4030", bark_emissive="#000000", leaf="#4F8A3A",
                    leaf_emissive="#000000", leaf_low="#B8A24A", glow=False, fruit=True,
                    fruit_color="#D9452B", particles="leaf", accent="#E2563A"),
}
def theme(name: str) -> dict: ...   # unknown name -> THEMES["normal"]
```

```python
# fernal/sky.py  (stdlib only; does NOT import sim)
def sun_position(lat: float, lon: float, when: datetime) -> tuple[float, float]: ...  # (elevation_deg, azimuth_deg), `when` tz-aware
def day_factor(elevation_deg: float) -> float: ...     # linear 0..1 over -6..+6
def fetch_weather(lat: float, lon: float, timeout: float = 5.0) -> "dict | None": ...
    # {"temperature": degC, "humidity": 0..1, "radiation": 0..1 (shortwave W/m2 / 800, clamped)}; App builds sim.Outdoor(**w)
def geocode(name: str, timeout: float = 5.0) -> "dict | None": ...   # {"city": str, "lat": float, "lon": float}
```

```python
# fernal/overlay.py
class Bridge(QObject):
    # Qt Properties with <name>Changed signals, read by Scene.qml:
    # sunElevation: float, sunAzimuth: float, dayFactor: float,
    # theme: str, glowEnabled: bool, particlesEnabled: bool, potSource: str (file URL or ""),
    # barkColor: str, emissiveColor: str, leafColor: str, leafEmissive: str, fruitColor: str, accentColor: str,
    # vitality: float, windStrength: float (0..1),
    # cameraYaw: float (deg), cameraPitch: float (deg, -10..60), cameraDistance: float (cm, 300..1200)

class OverlayWindow(QQuickView):
    hovered = Signal()
    clicked = Signal()
    menuRequested = Signal(QPoint)       # global position
    orbitRequested = Signal(float, float)  # dx, dy in pixels (Shift+drag)
    zoomRequested = Signal(float)        # wheel delta
    geometryChanged = Signal()
    def __init__(self, bridge: Bridge, geometries: dict, assets_url: QUrl): ...
    # context properties: "bridge", "branchGeometry", "leafGeometry", "fruitGeometry", "assetsUrl"
    def set_click_through(self, on: bool) -> None: ...
    def grab_png(self, path: str) -> bool: ...

def build_menu(parent, state_theme: str, click_through: bool) -> tuple[QMenu, dict]: ...
    # dict of QAction by key: "water","nutrients","climate","spray","settings","theme:<name>","pot","clickthrough","quit"
class Tray(QSystemTrayIcon):
    def __init__(self, icon: QIcon, menu: QMenu): ...
```

```python
# fernal/tools.py
class GlassPanel(QWidget):
    def __init__(self, title: str, accent: str = "#5FA85A", parent=None): ...
    body: QVBoxLayout                      # content goes here
    def set_accent(self, color: str) -> None: ...
    def show_animated(self) -> None: ...   # fade in 150 ms

class ToolPanel(GlassPanel):
    action = Signal(str, float)            # ("water",0.2) ("feed",0.3) ("spray",0.15) ("heater",-3.0)
    def __init__(self, kind: str, accent: str): ...   # kind in {"water","nutrients","climate","spray"}
    def set_value(self, value: float) -> None: ...     # gauge 0..1 (climate: heater offset mapped to 0..1)

class SettingsPanel(GlassPanel):
    themeChanged = Signal(str); potChosen = Signal(str); cityChanged = Signal(str); sizeChanged = Signal(int, int)
    def set_values(self, theme: str, pot_path: str, city: str, w: int, h: int) -> None: ...

# fernal/debug_panel.py
class DebugPanel(GlassPanel):
    changed = Signal(dict)   # any of: time_scale, age, growth_percent, reseed(bool), force{name: value|None}, reset(bool)
    def set_state(self, state) -> None: ...
```

```python
# fernal/app.py
class App(QObject):
    full_age: float                        # max(birth_age + grow_hours) over the current skeleton; 0 before the first generate
    def __init__(self, args): ...          # argparse Namespace from __main__
    def sun_dir(self) -> tuple: ...        # unit vector of the sun at local 13:00 today: x = east, y = up, z = south
    def regenerate(self) -> None: ...      # params_from(env, vitality, sun_dir(), theme) -> generate -> rebuild meshes (coalesced by a 50 ms single-shot QTimer)
    def rebuild_meshes(self) -> None: ...  # arrays for current age -> geometries
    def run(self) -> int: ...              # normal mode; screenshot mode exits after writing the PNG
```

Screenshot CLI (`python -m fernal --screenshot PATH [--theme T] [--age H] [--seed S] [--hour HH]`): sets state from args, computes the sun for today at `--hour` local time, regenerates, shows the window, grabs after 1500 ms, writes PNG, exits 0.

---

## Phase 0 (Day 1, ~1 h wall): scaffold + spike

### T0: Scaffold and transparency spike — Sonnet, 1 h

**Files:** `requirements.txt`, `.gitignore`, `fernal/__init__.py`, `fernal/__main__.py` (stub printing "Fernal"), `scripts/spike_overlay.py`, `scripts/spike.qml`, `docs/superpowers/notes/spike.md`, `docs/screenshots/spike.png`

- [ ] Create `.venv` with Python 3.14, install `PySide6>=6.11 numpy pytest`, write `requirements.txt`.
- [ ] Spike: frameless, transparent, always-on-top `QQuickView` (`setDefaultAlphaBuffer(True)`, `setColor(Qt.transparent)`) loading `spike.qml`: `View3D` with `ExtendedSceneEnvironment { backgroundMode: Transparent; glowEnabled: true; glowBloom: 0.5 }`, a `DirectionalLight { castsShadow: true }`, an emissive sphere, a cube below it receiving the shadow, and a `SpriteParticle3D` emitter. Try `tonemapMode: SceneEnvironment.TonemapModeNone` if the background turns black.
- [ ] After 1500 ms call `view.grabWindow().save("docs/screenshots/spike.png")`, then toggle `Qt.WindowTransparentForInput` on and off, then quit.
- [ ] Write `spike.md`: five lines answering (1) corners transparent? (2) glow halo visible? (3) shadow visible? (4) particles visible? (5) click-through toggle worked without a crash?
- [ ] Commit `chore: scaffold and overlay spike`.

**Done when:** `spike.png` exists, `spike.md` answers all five questions. Main decides glow path vs. fallback before Phase 1.

## Phase 1 (Day 1, ~2 h wall): core, five agents in parallel

### T1: Skeleton generation — Sonnet, 1.5 h

**Files:** `fernal/tree.py`, `tests/test_tree.py`
**Interfaces:** produces `Params`, `Segment`, `Skeleton`, `params_from`, `generate` exactly as in the contracts.

- [ ] Implement the generation rules from the contracts section. `params_from` maps `Env` + vitality + sun direction + theme to `Params` using the table in spec section 4 (`fruit_ratio = 0.3 * affection` for the fruit theme, else 0).
- [ ] Tests: `test_same_seed_same_skeleton` (arrays equal), `test_different_seed_differs`, `test_more_nutrients_more_segments`, `test_segment_cap_respected` (`max_segments=200`), `test_params_from_ranges` (every field inside its range for extreme envs), `test_tropism_bends_toward_sun` (mean of tip x-coordinates moves with `tropism=(1,0,0)` vs `(-1,0,0)`).
- [ ] `pytest tests/test_tree.py -q` passes. Commit `feat(tree): seeded recursive skeleton`.

### T2: Simulation and persistence — Sonnet, 1.5 h

**Files:** `fernal/sim.py`, `tests/test_sim.py`
**Interfaces:** produces everything listed under `sim.py` in the contracts.

- [ ] Implement dataclasses, dynamics, tool actions, `catch_up`, JSON round trip, `save`/`load` with `.bak` recovery.
- [ ] Tests: `test_water_evaporates_faster_in_light`, `test_nutrients_decay_per_day`, `test_vitality_is_one_at_optimum_and_lower_outside`, `test_growth_rate_bell_on_temperature`, `test_catch_up_is_capped` (30 days elapsed advances the same as 7 days and runs under 1 s), `test_json_round_trip`, `test_from_dict_ignores_unknown_keys`, `test_load_corrupt_file_backs_up` (tmp_path), `test_forced_values_pin_env`.
- [ ] `pytest tests/test_sim.py -q` passes. Commit `feat(sim): environment simulation and state file`.

### T3: Sun and weather — Sonnet, 1 h

**Files:** `fernal/sky.py`, `tests/test_sky.py`
**Interfaces:** produces `sun_position`, `day_factor`, `fetch_weather`, `geocode`.

- [ ] NOAA solar position approximation (declination, equation of time, hour angle) with stdlib `math` and `datetime`.
- [ ] `fetch_weather` calls `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current=temperature_2m,relative_humidity_2m,shortwave_radiation` with `urllib.request` and the timeout; any exception returns `None`. `geocode` uses `https://geocoding-api.open-meteo.com/v1/search?name=..&count=1&language=ko`.
- [ ] Tests: `test_noon_is_max_elevation` (Seoul, 2026-06-21, compare 12:30 KST against 06:00 and 18:00), `test_night_elevation_negative`, `test_day_factor_bounds`, `test_fetch_weather_failure_returns_none` (monkeypatch `urllib.request.urlopen` to raise), `test_fetch_weather_parses` (monkeypatch to return a canned JSON body with temperature_2m=21.5, relative_humidity_2m=60, shortwave_radiation=400; assert the result equals {"temperature": 21.5, "humidity": 0.6, "radiation": 0.5}).
- [ ] `pytest tests/test_sky.py -q` passes. Commit `feat(sky): sun position and Open-Meteo`.

### T4: Mesh builders and geometry — Sonnet, 1.5 h

**Files:** `fernal/mesh.py`, `tests/test_mesh.py`
**Interfaces:** consumes `Skeleton` fields from the contracts (build a hand-made `Skeleton` in tests; do not import `tree`). Produces `growth`, `branch_arrays`, `leaf_arrays`, `fruit_arrays`, `PlantGeometry`.

- [ ] Vectorized tube/quad/sphere builders with numpy; `uv1` sway attributes as specified.
- [ ] `PlantGeometry.set_arrays`: `clear()`, `setVertexData(QByteArray)`, `setIndexData`, `addAttribute` for `PositionSemantic` (offset 0), `NormalSemantic` (12), `TexCoord0Semantic` (24), `TexCoord1Semantic` (32), stride 40, `IndexSemantic` U32, `setBounds`, `setPrimitiveType(Triangles)`, `update()`.
- [ ] Tests (no QApplication needed for array tests): `test_growth_smoothstep_bounds`, `test_branch_arrays_vertex_count` (2 rings x 6 verts = 12 vertices and 36 indices per visible segment), `test_unborn_segments_excluded`, `test_leaf_quad_size_scales_with_growth`, `test_indices_in_range`, `test_plant_geometry_import` (import succeeds; constructing requires a `QGuiApplication` fixture).
- [ ] `pytest tests/test_mesh.py -q` passes. Commit `feat(mesh): numpy mesh builders and PlantGeometry`.

### T4b: Textures and icon — Opus, 1 h

**Files:** `scripts/make_textures.py`, `fernal/assets/bark.png`, `fernal/assets/bark_normal.png`, `fernal/assets/leaf.png`, `fernal/assets/tray.png`

- [ ] `bark.png` 512x512 tileable: layered value noise stretched vertically (fiber), a near-neutral light tint map (values about 0.55..1.0, faint warm tint) so the theme's bark color multiplies it; darker crevices and ridges carry the structure. `bark_normal.png` from the same height field (Sobel, strength tuned so ridges read at 1 m camera distance).
- [ ] `leaf.png` 256x256 RGBA: elegant leaf silhouette (pointed tip, slight asymmetry), alpha outline anti-aliased, midrib and side veins darker, lighter edge. Color is near-white so the material tints it.
- [ ] `tray.png` 64x64: simple leaf glyph, transparent background, readable at 16 px.
- [ ] Script is deterministic (fixed seed) and re-runnable. Commit `feat(assets): procedural bark and leaf textures`.

**Done when:** all four PNGs exist and the script runs without error.

## Phase 2 (Day 1 -> Day 2, ~3 h wall): scene and overlay, three agents

### T5: 3D scene, themes, wind, particles — Opus, 2.5 h

**Files:** `fernal/themes.py`, `fernal/qml/Scene.qml`, `fernal/qml/shaders/wind.vert`, `fernal/qml/shaders/bark.frag`, `fernal/qml/shaders/leaf.frag`, `scripts/preview_scene.py` (throwaway harness), `docs/screenshots/scene_<theme>_<day|night>.png`
**Interfaces:** consumes `PlantGeometry` (T4), context properties and `Bridge` property names (contracts), `tree.generate` + `params_from` (T1). Produces `Scene.qml` bound only to those names and `themes.THEMES`.

- [ ] Apply the spike findings (`docs/superpowers/notes/spike.md`, verified on the real screen, D3D11): glow coexists with the transparent window; use `glowBlendMode: Additive` and `glowLevel: One|Two|Three` (Qt defaults SoftLight/One show no halo); `glowBloom 0.5` white-outs lit surfaces, so keep materials dark or lower the bloom; particles need `particleScale` about 0.3 and an `EmitBurst3D` at t=0 because the first frame arrives about 1 s after show(); the display DPR can be 1.5 (grabs are 1.5x larger).
- [ ] `Scene.qml`: `View3D` with `ExtendedSceneEnvironment` (transparent background, MSAA High, `glowEnabled: bridge.glowEnabled`, `glowBloom: 0.5`, glow strength tuned), camera on an orbit `Node` driven by `bridge.cameraYaw/cameraPitch/cameraDistance` (defaults 0, 8, 650) framing a 300 cm tall plant from slightly below (FOV 35), sun `DirectionalLight` whose rotation follows `bridge.sunElevation/sunAzimuth`, color and brightness blended by `bridge.dayFactor` (warm 1.0 by day, blue 0.25 at night), `castsShadow: true`, `shadowMapQuality: High`, soft PCF, plus a cool fill and a rim light.
- [ ] Models: branches (`CustomMaterial`, Shaded, `wind.vert` + `bark.frag` with `bark.png` albedo and `bark_normal.png` normal, emissive from `bridge.emissiveColor`), leaves (`CustomMaterial`, `NoCulling`, `leaf.frag` with alpha discard from `leaf.png`, base color blends `bridge.leafColor` by `bridge.vitality`), fruits (`PrincipledMaterial`, `bridge.fruitColor`, visible only when the theme has fruit).
- [ ] `wind.vert`: `VERTEX += sway(UV1.x phase, UV1.y weight, time uniform, windStrength uniform)` using two summed sines, amplitude 2 cm max. `time` is a `property real` driven by a looping `NumberAnimation` in QML.
- [ ] Celestial body (spec section 6): a soft glowing sun disc by day and moon disc by night gliding along an arc across the top band of the window, driven by `bridge.sunElevation/sunAzimuth/dayFactor`, fading near the horizon.
- [ ] Pot: `RuntimeLoader { source: bridge.potSource }` when non-empty, else a code-built cylinder pot (`#Cylinder` scaled 60x40x60, dark ceramic `PrincipledMaterial`) positioned so the trunk base sits on the soil.
- [ ] Particles: `ParticleSystem3D` with golden motes (erdtree, additive, ~60, slow rise, fade) and an occasional falling leaf sprite (normal/fruit), switched by `bridge.particlesEnabled` and theme.
- [ ] `scripts/preview_scene.py`: transparent window that builds a skeleton via `tree` for a given `--theme --age --hour`, feeds the three geometries and a `Bridge`-shaped `QObject`, grabs a PNG. Produce six screenshots (3 themes x day/night) into `docs/screenshots/`.
- [ ] Commit `feat(scene): Qt Quick 3D scene, themes, wind and particles`.

**Done when:** six screenshots exist, corners are transparent, Erdtree glows, shadows visible on the pot, and leaves move between two frames one second apart.

### T6: Overlay window, bridge, menu, tray — Sonnet, 1.5 h

**Files:** `fernal/overlay.py`
**Interfaces:** produces `Bridge`, `OverlayWindow`, `build_menu`, `Tray` exactly as in the contracts.

- [ ] `Bridge`: `Property` + `Signal` for every listed name, with setters that emit only on change.
- [ ] `OverlayWindow`: flags `FramelessWindowHint | WindowStaysOnTopHint | Tool`, `setDefaultAlphaBuffer(True)` before construction, `setColor(Qt.transparent)`, context properties, `setSource(Scene.qml)`. Left-drag moves the window; Shift+drag emits `orbitRequested`; wheel emits `zoomRequested`; right-click emits `menuRequested(globalPos)`; enter/press emit `hovered`/`clicked`. `set_click_through` re-applies flags with `WindowTransparentForInput` and re-shows. `grab_png` uses `grabWindow()`.
- [ ] `build_menu`: Korean labels: 물 주기, 영양제, 온도 조절, 스프레이, 설정, 테마 ▸ (세계수/일반 나무/열매 나무, checkable), 화분 바꾸기…, 클릭 통과 (checkable), 종료.
- [ ] `Tray`: icon from `fernal/assets/tray.png`, same menu, left-click shows the menu.
- [ ] Manual check: `python -c` smoke script that opens the window with empty geometries and a stub QML showing a sphere; right-click shows the menu; toggling click-through does not crash. Commit `feat(overlay): transparent window, bridge, menu, tray`.

### T7: Controller, timers, persistence, screenshot mode — Sonnet, 1.5 h

**Files:** `fernal/app.py`, `fernal/__main__.py`
**Interfaces:** consumes `sim`, `tree`, `mesh`, `sky`, `themes.theme`, `overlay` names from the contracts. Produces `App` and the CLI.

- [ ] `__main__`: argparse (`--screenshot`, `--theme`, `--age`, `--seed`, `--hour`), `QApplication`, `App(args).run()`.
- [ ] `App.__init__`: load state (`sim.load`), clamp window geometry to available screens, `catch_up` with the last `Outdoor` (stored in state file under key `outdoor`), create `Bridge`, three `PlantGeometry`, `OverlayWindow`, menu + `Tray`, connect signals (hover/click -> `sim.touch`; `orbitRequested` -> `cameraYaw += dx*0.4`, `cameraPitch -= dy*0.3` clamped; `zoomRequested` -> `cameraDistance` clamped 300..1200; menu actions -> no-ops for tools until T9, theme/click-through/quit wired now).
- [ ] Timers: 1 s tick (`sim.step`, sun update via `sky.sun_position`, bridge day factor and sun angles, `regenerate` if `params_from` output changed, else `rebuild_meshes` at 10 Hz while any segment still grows), 60 s save, 1 h weather fetch on a `QThreadPool` runnable (result dict -> `sim.Outdoor(**w)` stored in `state.outdoor`, applied on the main thread), fetched once at startup.
- [ ] `regenerate` coalesced by a 50 ms single-shot `QTimer`. `rebuild_meshes` uses `branch_arrays`, `leaf_arrays` (size from params), `fruit_arrays`.
- [ ] Screenshot mode as specified under the contracts. Commit `feat(app): controller, timers, persistence, screenshot CLI`.

**Done when:** `python -m fernal --screenshot docs/screenshots/app_normal.png --theme normal --age 120 --seed 3 --hour 14` writes a PNG with a visible plant and transparent corners, and the normal run shows the window, menu and tray.

## Phase 3 (Day 2, ~2.5 h wall): tools UI, two agents

### T8: Glass panels, tool panels, settings — Opus, 2 h

**Files:** `fernal/tools.py`
**Interfaces:** produces `GlassPanel`, `ToolPanel`, `SettingsPanel` exactly as in the contracts.

- [ ] `GlassPanel`: frameless `Tool` window, `WA_TranslucentBackground`, custom `paintEvent` (rounded 14 px rect `rgba(18,20,28,0.78)`, 1 px border `rgba(255,255,255,0.08)`, 2 px accent line under the title), header with Korean title and a close glyph, drag by header, `show_animated` fades `windowOpacity` 0 -> 1 over 150 ms. Font: Pretendard if `QFontDatabase` has it, else Segoe UI.
- [ ] `ToolPanel`: per kind: 물 주기 (button "물 주기", gauge "토양 수분"), 영양제 (button, gauge), 온도 조절 (slider -10..+10 with labels 에어컨/난방, current effective temperature label), 스프레이 (button, gauge "습도"). Buttons have a 120 ms press animation. Large slider handle styled with the accent.
- [ ] `SettingsPanel`: city `QLineEdit` + 적용 button, theme `QComboBox`, pot file `QFileDialog` button (`*.glb *.gltf`) + 기본 화분 button, width/height spin boxes.
- [ ] Deliver `docs/screenshots/panels.png` (all panels open over a dark and a light desktop wallpaper, via `QWidget.grab()` composited by a small script). Commit `feat(tools): glass tool panels and settings`.

### T9: Debug panel and wiring — Sonnet, 1 h

**Files:** `fernal/debug_panel.py`, modify `fernal/app.py`
**Interfaces:** consumes `GlassPanel` and `ToolPanel`/`SettingsPanel` signals (contracts). Produces `DebugPanel`.

- [ ] `DebugPanel`: time scale slider (log scale 0.1..1000, label shows value), age spin box, growth percent slider (0..100 maps to age 0..`max birth_age + grow_hours` of the current skeleton, exposed by `App` as `app.full_age`), 시드 재추첨 button, six force rows (checkbox + slider), 초기화 button. Emits `changed` dicts.
- [ ] Wire in `App`: menu actions open the four `ToolPanel`s and `SettingsPanel` (created lazily, `show_animated`); `ToolPanel.action` -> `sim.water/feed/spray` or `controls.heater`; `SettingsPanel` signals -> state (`geocode` on a runnable), theme -> bridge colors from `themes.theme`, pot path -> `bridge.potSource` (file URL, fallback to "" if missing), size -> window resize. `Ctrl+Shift+D` `QShortcut` on the overlay opens `DebugPanel`; `changed` -> state. Panels' gauges refreshed on each tick.
- [ ] Commit `feat(debug): hidden debug panel and tool wiring`.

**Done when:** every menu entry opens its panel, pressing 물 주기 raises the water gauge, the climate slider changes the trunk bend within a second, and the debug time-scale at 1000 visibly grows the plant.

## Phase 4 (Day 2, ~3 h wall): integration, polish, review

### T10: Integration pass — Sonnet, 1.5 h (runs first)

- [ ] Run the app end to end; fix crashes and wiring gaps. Verify Review Focus items 4 and 5 manually (slider spam, bogus pot path, off-screen geometry) and record results in `docs/superpowers/notes/integration.md`.
- [ ] Produce `docs/screenshots/final_<theme>_<day|night>.png` (six) via the CLI and one `final_desktop.png` of the real overlay with two panels open.
- [ ] `pytest -q` green. Commit `fix: integration pass`.

### T11: Visual polish — Opus, 1.5 h (after T10, parallel with T12)

- [ ] Using T10 screenshots: tune light colors and intensities per day factor, glow strength, leaf tint by vitality, wind amplitude, particle rate, camera framing, pot material, panel spacing and typography. Keep diffs inside `Scene.qml`, shaders, `themes.py`, `tools.py`.
- [ ] Re-shoot the six screenshots. Commit `style: visual polish pass`.

### T12: Review and README — Sonnet, 1 h (parallel with T11)

- [ ] Code review of all modules against the spec and contracts: naming, dead code, exception swallowing beyond the two allowed places (weather fetch, pot load), thread safety of the weather runnable. Fix small issues directly, list larger ones in `docs/superpowers/notes/review.md`.
- [ ] `README.md` (English): what it is, install (`python -m venv .venv`, `pip install -r requirements.txt`), run (`python -m fernal`), controls, hidden debug shortcut, screenshot CLI, the six screenshots.
- [ ] Commit `docs: README and review notes`.

## Workflow execution notes

- One Workflow run per phase; agents per run: P0 1, P1 5, P2 3, P3 2, P4 3 (T10 then T11 + T12). All under the 10-agent guideline.
- Main (this session) checks between phases: tests green, screenshots opened and judged, contracts respected. The user judges visuals after Phase 2 and Phase 4.
- An agent that fails its "Done when" twice is stopped; main asks the user whether to assign Fable to that task.
- Every task commits only its own files; `app.py` is modified only by T7 (create), T9 (wire), T10 (fix).
- Run what can run (user request): at every phase boundary main executes the runnable pieces itself and shows the result before starting the next phase. P0: view the spike screenshot. P1: full pytest run, plus a throwaway tree-to-PNG render if T4b/T4 are both done. P2: launch the real overlay and the screenshot CLI. P3: open every panel and press every button. P4: end-to-end run with the six final screenshots.
