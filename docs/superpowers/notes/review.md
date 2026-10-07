# T12 code review

Scope: every file under `fernal/`, `scripts/` and `tests/`, checked against the spec, the plan's interface contracts and the five Review Focus items. Visual files (`Scene.qml`, shaders, theme colors, panel styling, `make_textures.py`) were read but not edited.

Evidence used: `pytest -q` (111 tests after this review, was 98), the screenshot CLI, and throwaway probes (render-loop hang, quit during a request, timing). The probes lived outside the repo and are not kept.

## Review Focus coverage

| # | Item | Pinned by |
|---|---|---|
| 1 | Offline weather returns `None`, app keeps the last `Outdoor`, nothing raises | `test_sky.py::test_fetch_weather_failure_returns_none`, `test_fetch_weather_malformed_returns_none`, new `test_fetch_weather_rejects_non_finite_values`; app level: new `test_app.py::test_failed_weather_keeps_the_last_values` |
| 2 | Corrupt or old-schema `state.json` | `test_sim.py::test_load_corrupt_file_backs_up` (includes a `NaN` literal), `test_from_dict_ignores_unknown_keys` (missing keys and sections get defaults); app level: new `test_corrupt_state_file_starts_a_fresh_plant` |
| 3 | Months away is capped and fast | `test_sim.py::test_catch_up_is_capped` |
| 4 | Slider spam is debounced | was manual only and never recorded (`integration.md` from plan T10 does not exist). Now automated: `test_app.py::test_regenerate_requests_are_coalesced` (200 requests, one skeleton), `test_tools.py::test_climate_slider_spam_is_throttled` (300 moves, at most 6 updates, last value last) |
| 5 | Missing pot file and off-screen geometry fall back | was manual only. Now `test_app.py::test_pot_url_falls_back_to_the_default_pot`, `test_clamp_window_*`, `test_offscreen_window_and_missing_pot_fall_back`. A pot file that exists but is corrupt falls back inside QML (`defaultPot.visible` follows `RuntimeLoader.status`); that path needs the real screen (see `manual-qa.md`) |

Thread safety (weather and geocode runnables): the workers read only plain values captured at construction, call stdlib code and touch Qt only by emitting a signal; both slots are `@Slot`s of `App`, so delivery is queued onto the main thread. Pinned by `test_weather_arrives_on_the_main_thread_through_a_signal` (worker thread id differs from the slot's thread id, slot id equals the main thread). No widget or QObject is read from a worker.

Exception swallowing: the two allowed places are `sky.fetch_weather` and the pot fallback (which uses `Path.is_file` and QML status, no `except`). Also present and judged acceptable: `sky.geocode` (same network class as the weather fetch), `sim.load` (narrow tuple, then a best-effort `.bak` move), `App._on_weather`, `App._on_geocode`, `App.save_state` (narrow, logged). Added in this review: `except RuntimeError` around the signal emit in both runnables (quit race, see below). No bare `except:`.

Network: weather is fetched at startup, hourly, and once after a successful city lookup (guarded by `_fetching`, a stale answer triggers one refetch). Screenshot mode never starts the weather timer. Geocoding runs only from the 찾기 button or Enter in the city field.

## Fixed in this pass

1. `sky.py:71-92` `fetch_weather` accepted `NaN`/`Infinity` (json allows the literals). They would flow into `Env`, be written to `state.json` and make the next `load` treat the file as corrupt (the plant is lost to `.bak`). Now returns `None`. Test added.
2. `sky.py:95-110` `geocode` could return non-finite or impossible coordinates that are saved as `lat`/`lon`. Now validated (-90..90, -180..180).
3. `app.py:229-266` quitting while a weather or geocode request ran printed `RuntimeError: Signal source has been deleted` from the worker thread. The emit is now guarded.
4. `app.py:808` a slow geocode answer for an older city name could overwrite a newer one. Answers for names other than the latest request are dropped.
5. `app.py:358` with no tray icon (`isSystemTrayAvailable()` false) click-through could be switched on with no way back. The menu entry is now disabled in that case.
6. `app.py:573` `_shutdown` now stops the timers explicitly before the single final save.
7. `__main__.py:34-42` the render-loop comment claimed the cause was PlantGeometry needing the GIL; the probe showed the Python `event()` override alone causes the hang (see ranked item 1). Comment rewritten, and the variable is assigned instead of `setdefault`, because an inherited `QSG_RENDER_LOOP=threaded` hangs the app on the first frame. `overlay.py:143` got a matching note.
8. `__main__.py:24` `--age` help said "first run: 8" (that is the time scale); the first-run age is 48. `--state` help now says screenshot mode never reads or writes it.
9. Duplicates and dead code: `THEME_LABELS` (overlay.py) and `THEME_CHOICES` (tools.py) were hand-copied from `themes.py`; both now derive from `themes.THEMES` (names unchanged, test added). Removed the unused `tools.FILL` and `ToolPanel.value_row`. `app.py` module docstring now lists every pure helper.

## Open items, ranked

1. Medium, `overlay.py:143` (`OverlayWindow.event`) and `__main__.py:42`: the Python `event()` override forces `QSG_RENDER_LOOP=basic`. Probe: with Qt's threaded loop the first frame never arrives (timeout after 70 s); with `OverlayWindow.event` deleted the threaded loop renders and exits 0. The basic loop renders on the GUI thread, which is part of the idle CPU cost. Fix: detect hover without overriding `event()` (a `HoverHandler` in `Scene.qml` raising a bridge signal, or a native event filter), re-run the probe, then drop the env var.
2. **Fixed after review** (`__main__.py` now calls `os._exit(rc)` after the final save; checked: exit in 0.08 s with the state saved). Medium, `app.py:229-266` / `__main__.py`: quitting while a request is in flight keeps the process alive until the request returns (probe: a 4 s request kept the process 5 s after the window closed). The 5 s timeout does not cover DNS, so offline machines can keep a hidden `pythonw` process for longer. Fix: run requests on daemon `threading.Thread`s (result through the same queued signal) or call `os._exit(code)` after the final save in `main`.
3. Medium, `app.py:523-529` `_tick`: a stall longer than 60 s (sleep, hibernate, if the clock counts it) is replayed with the radiation of the current instant, so a laptop closed overnight and opened at 08:00 "grows" eight hours in daylight. `_load_state` already uses `mean_radiation` for the same situation. Fix: reuse `mean_radiation(None, lat, lon, time.time(), dt)` in the stall branch.
4. Medium, `sim.py` `Controls` / `app.py:719-746`: debug settings persist. `time_scale` (up to 1000) and `controls.forced` pins are saved and replayed by the next launch's catch-up, so a pinned value silently holds the plant after a restart until the hidden panel is opened and reset. Debatable (the scale is a documented control). Fix: drop `forced` on load, or show a hint when pins or a scale above 8 are active.
5. **Fixed after review** (Scene.qml wind clock now loops over 2*pi/0.1 s, a common period of the 0.9/2.3/4.1 rad/s gust sines; only the fast leaf flutter still jumps, unseen). Low, `qml/Scene.qml:26-31` with `shaders/wind.vert`: the wind clock wraps from 3600 s to 0 once an hour, and the sines (0.9, 2.3, 4.1 rad/s, flap 5-8 rad/s) do not close on a whole cycle at 3600 s, so the sway jumps by up to the amplitude (about 2.4 cm at the tips) for one frame every hour. Not edited (visual file). Fix: loop over a period that is a common multiple, or run the animation to 1e5 without looping.
6. Low, `app.py` no single-instance guard: starting `python -m fernal` twice gives two windows and two tray icons that overwrite each other's `state.json` (the writes are atomic, last writer wins). Fix: `QLockFile` next to the state file.
7. Low, `sky.py:95` `geocode` takes the first hit (`count=1`), so ambiguous names resolve silently; the status line shows only the city name. Fix: request `count=5` and show country or region, or let the user pick.
8. Low, `overlay.py:92` `OverlayWindow.geometryChanged` is emitted but nothing connects to it (public contract name, kept). Window geometry is only read at save time.
9. Low, docs drift: the spec and plan still describe values replaced in T11 (glow bloom 0.5, theme and panel colors, Pretendard font, 8 cm leaves, default time scale 1.0 versus first-run 8). `integration.md` (plan T10) was never written. Fix: add a "superseded by docs/design/design-plan.md" note to the spec, or update the tables.
10. Low, duplicates kept on purpose because `sim` and `tree` are Qt-free and import nothing: `_clamp` in sim/tree/app, `sim._THEMES` versus `themes.THEMES`, `app.CATCH_UP_CAP` versus the `sim.catch_up` default, `overlay.DEFAULT_SIZE` versus `PlantState.window`.
11. Low, `sim.from_dict` does not clamp `controls.time_scale`, `heater` or `window` sizes from a hand-edited file (`step` clamps heater; a huge window size is only fixed when it also misses every screen). Not reachable through the UI.
12. Low, `app.py:736` `_on_debug_changed` accepts any attribute name through `hasattr(st.env, name)` (only the debug panel emits it). `sim._ENV_FIELDS` would be tighter.

## Removal candidates (nothing was deleted)

- `scripts/spike_overlay.py`, `scripts/spike.qml`, `docs/superpowers/notes/spike.md`, `docs/screenshots/spike.png`, `docs/screenshots/spike_composite.png`: the T0 spike, answered and applied.
- `docs/screenshots/tree_preview.png`: T4 throwaway render.
- `scripts/preview_scene.py`, `scripts/preview_panels.py`: harnesses that made `scene_*.png` and `panels.png`; keep only if screenshots will be re-shot (`preview_panels.py:20` has an unused import `ui_font`; `panels.png` shows a sixth card, "식물 상태", that exists only in that script and not in the app).
- `docs/screenshots/app_*.png`, `scene_normal_young.png`, `growth_*` beyond what the README uses are evidence from T7-T11, not referenced by code.
- `.pytest_cache/` (already ignored by `.gitignore`).
