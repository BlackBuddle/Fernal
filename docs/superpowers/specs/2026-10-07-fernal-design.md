# Fernal Design Spec (2026-10-07)

A desktop program that grows a 3D plant by fractal rules inside a transparent overlay window on the desktop.
Two-day mini project (16 hours total). **Aesthetics come first.**

## 1. Goal and success criteria

- A frameless, transparent, always-on-top window shows a 3D plant that grows over time.
- Water, nutrients, temperature, humidity, affection and light affect every branch individually, so the plant grows asymmetrically.
- Moving a slider in a semi-transparent Qt Widgets tool panel changes the plant immediately.
- The sun moves with the time of day and gives way to moonlight at night. Temperature and light default to today's local weather.
- Three themes (glowing Erdtree, normal tree, fruit tree) and a swappable pot model.
- Time spent while the app was closed is simulated on relaunch. A hidden tool sets the time scale and growth level directly.
- Success: each theme's screenshot makes you want it on your desk. Done within 16 hours.

## 2. Global constraints

- Python 3.14, PySide6 >= 6.11, numpy. These are the only runtime dependencies.
- **Only the plant scene (`fernal/qml/Scene.qml`) is QML.** Tool panels, menus, tray, settings and the debug tool are all Qt Widgets written in Python.
- Windows 11 only. Overlay flags: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`.
- UI copy is Korean. The only external API is Open-Meteo (no key).
- No secrets. State file: `%APPDATA%\Fernal\state.json`.
- Textures are three PNGs (`bark.png`, `bark_normal.png`, `leaf.png`) generated once by a script and committed under `fernal/assets/`. No runtime generation.
- Documents, code, comments and agent prompts are written in English. Only chat output to the user is Korean.
- Models: visual work (3D scene, materials, themes, panel design, textures, shaders) uses Opus; logic and wiring use Sonnet; Fable only with the user's explicit approval.

## 3. Architecture

One process, one language. The pure-Python layer (sim, tree, sky) is tested without Qt.

| Module | Responsibility | Depends on |
|---|---|---|
| `fernal/sim.py` | Environment values, age and vitality over time; tool actions; catch-up for time away; JSON save/load | nothing |
| `fernal/tree.py` | seed + params -> branch skeleton (segments, leaf and fruit positions) | numpy |
| `fernal/mesh.py` | skeleton + age -> vertex arrays -> three `QQuick3DGeometry` objects (branches, leaves, fruits) | numpy, PySide6 |
| `fernal/sky.py` | sun/moon position, Open-Meteo weather and geocoding | stdlib |
| `fernal/themes.py` | per-theme colors, emissive, glow, fruit and accent table | nothing |
| `fernal/overlay.py` | transparent `QQuickView` window, drag, right-click menu, tray, click-through, QML bridge | PySide6 |
| `fernal/tools.py` | glass panel base class, four tool panels, settings panel, hidden debug panel | PySide6 |
| `fernal/qml/Scene.qml` | View3D, lights and shadows, camera, pot, three plant models, wind material, particles | Qt Quick 3D |
| `fernal/app.py` | Controller: owns state, timers, wires window/tools/scene, saves, screenshot mode | PySide6 |
| `fernal/__main__.py` | Entry point, argument parsing | PySide6 |
| `fernal/assets/` | three texture PNGs, tray icon | nothing |
| `scripts/make_textures.py` | one-off generator for bark albedo, bark normal map and leaf alpha mask | numpy, PySide6 (QPainter) |

Data flow: 1 s timer -> `sim.step` -> if params changed, `tree.generate` -> `mesh` rebuild -> QML update.
Slider changes take the same path immediately, throttled to 20 Hz. Growth animation only interpolates lengths by age at 10 Hz while any segment is still growing; the skeleton is not regenerated.

## 4. Growth model

Recursive branching instead of an L-system, so every parameter maps directly onto individual branches.

- Every segment has a unique id. Its RNG is `numpy.random.default_rng([seed, node_id])`, so moving a slider morphs the same tree continuously instead of reshuffling it.
- Child count, angle, length and radius = base value x environment factor +- the segment's own random jitter. Different jitter per branch makes the tree asymmetric.
- Phototropism: child directions are bent toward `tropism` (the sun's daily average direction) by `tropism_strength`. Thirst bends them downward by `droop`.
- Each segment has `birth_age` and `grow_hours`. It appears once the plant's age passes `birth_age` and lengthens with a smoothstep over `grow_hours`.
- Leaves attach at the tips of segments of depth >= `max_depth - 1`, in proportion to `leaf_density`. Fruits attach at a subset of leaf positions, fruit theme only.

Environment -> parameters (initial coefficients, adjustable in the hidden tool):

| Value | Range | Source and dynamics | Effect |
|---|---|---|---|
| `water` | 0..1 | watering +; evaporation - (faster with high temperature and light) | `length_ratio`, `leaf_size`. Below 0.2 `droop` rises; above 0.9 vitality drops |
| `nutrients` | 0..1 | tool +; -0.1 per day | `branch_factor`, radius |
| `temperature` | degC | today's outdoor temperature + heater/AC offset | growth rate (bell curve, optimum 22, width 10), leaf tint (cold -> yellow/red) |
| `humidity` | 0..1 | computed from water, temperature, light; spray + | `leaf_density` |
| `light` | 0..1 | today's shortwave radiation, normalized; 0 at night | growth rate, `tropism_strength`, leaf count |
| `affection` | 0..1 | +0.05 per hover/click on the window; -0.1 per day | vitality, fruit chance |

`vitality` (0..1) is a weighted mean of how far each value sits from its optimum band. It multiplies growth rate; when low, leaf count drops and leaf color blends toward brown.

## 5. Time and sky

- Plant age is in "plant hours" and advances at real time x `time_scale` x growth rate. Default `time_scale` is 1.0; the hidden tool changes it.
- On relaunch, `now - last_saved` is replayed through `sim.step` in 10-minute slices using the last known weather, capped at 7 days.
- Sun elevation and azimuth come from the NOAA approximation using latitude, longitude and local time. The moon sits opposite the sun.
- Day: the `DirectionalLight` follows the sun with a warm color. Night: it follows the moon with a dim blue. The blend is linear over elevation -6..+6 degrees.
- Weather: Open-Meteo `current=temperature_2m,relative_humidity_2m,shortwave_radiation`, fetched hourly with a 5 s timeout. On failure the last values stay. The city name in settings is resolved through Open-Meteo geocoding.

## 6. Rendering and visual direction

- Three meshes: branches (6-sided tube per segment, UV = around/along), leaves (textured quads with the leaf alpha mask, `alphaMode: Mask`, double-sided), fruits (low-poly spheres). Thousands of leaves are merged into one mesh; per-leaf size, rotation and color variation are baked into the vertices.
- Textures: trunk uses `bark.png` albedo + `bark_normal.png` normal map. Leaves use `leaf.png` (alpha = outline and veins). All three come from `scripts/make_textures.py` (numpy noise + QPainter).
- Wind: the leaf and branch meshes sway through a `CustomMaterial` (`shadingMode: Shaded`) vertex shader. Python bakes `UV1 = (sway phase, sway weight)` per vertex; a QML `NumberAnimation` drives a `time` uniform and the GPU does the rest. Python does nothing per frame. No instancing; switch to `QQuick3DInstancing` only if more than ~20k leaves get slow.
- Particles (`QtQuick3D.Particles3D`): Erdtree has slowly rising golden motes (additive, ~60). Normal and fruit trees drop an occasional falling leaf. First thing to cut if the schedule slips.
- Camera: `PerspectiveCamera`, FOV 35, looking slightly up at the plant's center. Wheel zooms, Shift+drag orbits.
- Lighting: sun/moon `DirectionalLight` (`castsShadow: true`, `shadowMapQuality: High`, soft PCF) + a cool fill from the opposite side + a rim light. Branches, leaves and pot cast and receive shadows. No ground plane.
- Pot: `RuntimeLoader` loads a user `.glb/.gltf`. Default is a code-built cylinder pot in dark ceramic.
- Theme table:

| Theme | Branches | Leaves | Extras |
|---|---|---|---|
| `erdtree` | gold bark `#8A6A2E`, emissive `#FFD27A` | translucent gold emissive leaves | `ExtendedSceneEnvironment.glowEnabled`, `glowBloom 0.5`, golden motes. If glow cannot coexist with the transparent window, fall back to emissive materials + a light billboard |
| `normal` | bark `#5A4030` | green `#4F8A3A`, blending to `#B8A24A` as vitality drops | falling leaf |
| `fruit` | same as normal | same as normal | fruit spheres `#D9452B`, count scales with affection |

- UI visuals: dark glass panels `rgba(18,20,28,0.78)`, 1 px border `rgba(255,255,255,0.08)`, 14 px corners, per-theme accent (Erdtree gold, normal green, fruit vermilion). Font Pretendard if installed, else Segoe UI. Panels fade in over 150 ms. Korean text labels, no icons.

## 7. Window and tools

- Overlay: default 420x640, hidden from the taskbar. Left-drag moves it, right-click opens a `QMenu`. Hover and click feed affection.
- Click-through: toggled from the menu or tray by re-applying `Qt.WindowTransparentForInput`. While on, the tray menu is the only control.
- Tray `QSystemTrayIcon`: open tools, theme, choose pot, settings, click-through, quit.
- Tool panels (each a `GlassPanel` subclass, independent windows): watering (button, +0.2), nutrients (button, +0.3), climate (heater/AC slider -10..+10 degC), spray (button, +0.15). Each shows a gauge of the current value.
- Settings panel: city name, theme, pot file picker, window size.
- Hidden debug panel (`Ctrl+Shift+D`): time scale slider (0.1..1000), direct age input, growth percent slider, reseed, force any of the six environment values, reset.

## 8. Persistence and error handling

- Save `state.json` every minute and on quit: seed, environment, age, controls, last-saved time, theme, pot path, window geometry, location (lat, lon, city).
- A corrupt file is moved to `state.json.bak` and the app starts fresh. A window position off every screen is reset to the primary screen's center.
- A pot model that fails to load falls back to the default pot. Weather fetches time out after 5 s and keep the last values on failure.

## 9. Verification

- `tests/` with pytest: `tree` (same seed -> same skeleton; parameter monotonicity; segment count cap), `sim` (evaporation, decay, vitality, catch-up cap, JSON round trip, corrupt-file recovery), `sky` (max elevation at solar noon, zero light at night, weather parsing and failure handling).
- Visuals: `python -m fernal --screenshot out.png --theme erdtree --age 300 --seed 7 [--hour 14]` writes a PNG. Every visual task delivers screenshots for three themes x day/night. Wind is checked by fixing `--hour` and shooting two frames one second apart; leaf positions must differ. The user makes the final call.

## 10. Out of scope (not in these two days)

- Multiple plants, sound, installer, historical weather, GPU instancing, ground shadow plane.
- Cut order if the schedule slips: particles -> wind shader -> falling leaf -> fruits on the fruit theme.
