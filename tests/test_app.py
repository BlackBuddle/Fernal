import argparse
import threading
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fernal import app as appmod
from fernal import sim, sky, themes, tree
from fernal.app import (PANEL_CASCADE, PANEL_GAP, clamp_window, effective_radiation, local_time_at, mean_radiation,
                        params_moved, place_beside)
from fernal.debug_panel import DebugPanel, pos_of_scale, scale_at
from fernal.overlay import THEME_LABELS
from fernal.tools import THEME_CHOICES, GlassPanel

SCREEN = (0, 0, 1920, 1080)
SECOND = (1920, 0, 1280, 1024)


def test_params_moved_without_previous_params():
    assert params_moved(None, tree.Params())


def test_params_moved_ignores_small_drift():
    assert not params_moved(tree.Params(), tree.Params(branch_factor=2.43, leaf_density=0.71, droop=0.02))


def test_params_moved_detects_three_percent_of_range():
    assert params_moved(tree.Params(), tree.Params(branch_factor=2.5))        # 0.1 of a 2.0 range
    assert params_moved(tree.Params(), tree.Params(leaf_density=0.74))        # 0.04 of a 1.0 range
    assert params_moved(tree.Params(), tree.Params(max_depth=7))


def test_params_moved_tropism_components_and_fruit():
    assert params_moved(tree.Params(), tree.Params(tropism=(0.1, 1.0, 0.0)))
    assert not params_moved(tree.Params(), tree.Params(tropism=(0.02, 1.0, 0.0)))
    assert params_moved(tree.Params(), tree.Params(fruit_ratio=0.05))


def test_clamp_window_keeps_visible_rect():
    rect = {"x": 100, "y": 100, "w": 420, "h": 640}
    assert clamp_window(rect, [SCREEN]) == rect


def test_clamp_window_off_screen_is_centered_on_primary():
    out = clamp_window({"x": 99999, "y": 100, "w": 420, "h": 640}, [SCREEN, SECOND])
    assert out == {"x": (1920 - 420) // 2, "y": (1080 - 640) // 2, "w": 420, "h": 640}


def test_clamp_window_on_second_screen_is_kept():
    rect = {"x": 2200, "y": 50, "w": 420, "h": 640}
    assert clamp_window(rect, [SCREEN, SECOND]) == rect


def test_clamp_window_barely_visible_is_recentered():
    out = clamp_window({"x": 1915, "y": 100, "w": 420, "h": 640}, [SCREEN])  # 5 px on screen
    assert out["x"] == (1920 - 420) // 2


def test_clamp_window_bad_size_and_extra_keys():
    out = clamp_window({"x": 10, "y": 10, "w": 0, "h": -5, "note": "kept"}, [SCREEN])
    assert (out["w"], out["h"], out["note"]) == (420, 640, "kept")


def test_clamp_window_shrinks_to_small_primary():
    out = clamp_window({"x": 5000, "y": 0, "w": 420, "h": 640}, [(0, 0, 400, 300)])
    assert (out["w"], out["h"]) == (400, 300) and (out["x"], out["y"]) == (0, 0)


def test_effective_radiation_is_dark_at_night():
    assert effective_radiation(0.9, -20.0) == 0.0
    assert effective_radiation(None, -20.0) == 0.0


def test_effective_radiation_synthesized_without_weather():
    assert abs(effective_radiation(None, 90.0) - 0.7) < 1e-9
    assert 0.0 < effective_radiation(None, 30.0) < 0.7


def test_effective_radiation_is_capped_by_the_sky():
    assert effective_radiation(0.9, 3.0) == sky.day_factor(3.0)   # dawn: sky allows 0.75
    assert effective_radiation(0.3, 50.0) == 0.3                   # a cloudy noon stays dim


def test_mean_radiation_between_night_and_day():
    seoul = (37.57, 126.98)
    # 2026-06-21 00:00 KST for 24 h: a full day-night cycle averages well below the peak.
    end = datetime(2026, 6, 22, tzinfo=timezone(timedelta(hours=9))).timestamp()
    mean = mean_radiation(None, *seoul, end, 86400.0)
    assert 0.1 < mean < 0.5
    night_end = datetime(2026, 6, 21, 3, tzinfo=timezone(timedelta(hours=9))).timestamp()
    assert mean_radiation(None, *seoul, night_end, 2 * 3600.0) == 0.0
    assert mean_radiation(0.9, *seoul, end, 0.0) >= 0.0   # zero span still samples once


def test_local_time_at_is_aware_and_on_today():
    now = datetime(2026, 10, 7, 21, 30).astimezone()
    when = local_time_at(14.5, now)
    assert when.tzinfo is not None
    assert (when.year, when.month, when.day, when.hour, when.minute) == (2026, 10, 7, 14, 30)


# ---- panel placement ------------------------------------------------------------------------

WINDOW = (100, 100, 420, 640)
PANEL = (280, 200)


def _xy(point):
    return point.x(), point.y()


def test_place_beside_prefers_the_right_side_top_aligned():
    assert _xy(place_beside(WINDOW, PANEL, [SCREEN])) == (100 + 420 + PANEL_GAP, 100)


def test_place_beside_falls_back_to_the_left():
    window = (1500, 200, 420, 640)                      # 1932 + 280 would leave the 1920 px screen
    assert _xy(place_beside(window, PANEL, [SCREEN])) == (1500 - PANEL_GAP - 280, 200)


def test_place_beside_cascades_away_from_the_window():
    assert _xy(place_beside(WINDOW, PANEL, [SCREEN], 2)) == (532 + 2 * PANEL_CASCADE, 100 + 2 * PANEL_CASCADE)
    left = place_beside((1500, 200, 420, 640), PANEL, [SCREEN], 1)
    assert _xy(left) == (1500 - PANEL_GAP - 280 - PANEL_CASCADE, 200 + PANEL_CASCADE)


def test_place_beside_stays_on_the_screen():
    low = place_beside((100, 1000, 420, 600), PANEL, [SCREEN])           # below the screen bottom
    assert low.y() == 1080 - 200
    crowded = place_beside((50, 100, 1800, 640), PANEL, [SCREEN])        # no room on either side
    assert 0 <= crowded.x() <= 1920 - 280
    tall = place_beside(WINDOW, (280, 5000), [SCREEN])                   # taller than the screen
    assert tall.y() == 0


def test_place_beside_uses_the_screen_holding_the_window():
    on_second = place_beside((2200, 50, 420, 640), PANEL, [SCREEN, SECOND])
    assert _xy(on_second) == (2200 + 420 + PANEL_GAP, 50)                # 2632 + 280 fits in 3200
    right_edge = place_beside((2700, 50, 420, 640), PANEL, [SCREEN, SECOND])
    assert _xy(right_edge) == (2700 - PANEL_GAP - 280, 50)               # left, still on the second screen


def test_place_beside_accepts_qt_types_and_no_screens():
    assert _xy(place_beside(QRect(*WINDOW), QSize(*PANEL), [SCREEN])) == (532, 100)
    assert _xy(place_beside(WINDOW, PANEL, [], 1)) == (532 + PANEL_CASCADE, 100 + PANEL_CASCADE)


# ---- debug panel ----------------------------------------------------------------------------

qapp = QApplication.instance() or QApplication([])


@pytest.fixture
def panel():
    p = DebugPanel("#5FA85A")
    p.got = []
    p.changed.connect(p.got.append)
    return p


def test_debug_panel_title_and_rows(panel):
    assert panel.windowTitle() == "디버그 도구"
    assert list(panel.force_rows) == ["water", "nutrients", "temperature", "humidity", "light", "affection"]
    assert all(not r.check.isChecked() and not r.slider.isEnabled() for r in panel.force_rows.values())


def test_debug_time_scale_slider_is_logarithmic(panel):
    assert (panel.time_slider.minimum(), panel.time_slider.maximum()) == (0, 1000)
    panel.time_slider.setValue(1000)
    panel.time_slider.setValue(0)
    panel.time_slider.setValue(500)
    assert panel.got == [{"time_scale": 1000.0}, {"time_scale": 0.1}, {"time_scale": 10.0}]
    assert panel.time_label.text() == "×10"
    for scale in (0.1, 1.0, 8.0, 123.0, 1000.0):
        assert abs(scale_at(pos_of_scale(scale)) - scale) / scale < 0.01
    assert pos_of_scale(0.0) == 0 and pos_of_scale(1e9) == 1000        # out of range is clamped


def test_debug_age_growth_reseed_reset_emit_one_key(panel):
    panel.age_spin.setValue(80.0)
    panel.growth_slider.setValue(500)
    QTest.mouseClick(panel.reseed_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel.reset_button, Qt.MouseButton.LeftButton)
    assert panel.got == [{"age": 80.0}, {"growth_percent": 50.0}, {"reseed": True}, {"reset": True}]


def test_debug_force_rows_pin_and_release(panel):
    row = panel.force_rows["water"]
    row.slider.setValue(300)                  # unchecked: a live readout, nothing is emitted
    assert panel.got == []
    row.check.setChecked(True)
    assert row.slider.isEnabled()
    row.slider.setValue(700)
    row.check.setChecked(False)
    assert panel.got == [{"force": {"water": pytest.approx(0.3)}}, {"force": {"water": pytest.approx(0.7)}},
                         {"force": {"water": None}}]
    temp = panel.force_rows["temperature"]
    temp.slider.setValue(1000)
    assert temp.value() == 45.0 and temp.value_label.text() == "45.0°C"
    temp.slider.setValue(0)
    assert temp.value() == -10.0


def test_debug_set_state_fills_controls_without_emitting(panel):
    state = sim.PlantState(age=50.0)
    state.controls.time_scale = 8.0
    state.controls.forced = {"light": 0.25, "temperature": 30.0}
    state.env.water = 0.4
    panel.set_state(state, mature_age=200.0)
    assert panel.got == []
    assert panel.time_slider.value() == pos_of_scale(8.0) and panel.time_label.text() == "×8.0"
    assert panel.age_spin.value() == 50.0
    assert panel.growth_slider.value() == 250 and panel.growth_label.text() == "25.0%"
    water, light, temp = (panel.force_rows[n] for n in ("water", "light", "temperature"))
    assert not water.check.isChecked() and not water.slider.isEnabled() and water.value() == pytest.approx(0.4)
    assert light.check.isChecked() and light.slider.isEnabled() and light.value() == pytest.approx(0.25)
    assert temp.check.isChecked() and temp.value() == pytest.approx(30.0, abs=0.06)   # 0.055 degC steps
    state.controls.forced = {}                # a released pin is shown released
    panel.set_state(state)                    # mature_age is remembered
    assert not light.check.isChecked() and panel.growth_label.text() == "25.0%"
    assert panel.got == []
    panel.set_state(sim.PlantState(age=1e6), mature_age=200.0)    # an overgrown plant reads 100 %
    assert panel.growth_label.text() == "100.0%" and panel.growth_slider.value() == 1000
    assert panel.got == []


def test_debug_panel_is_a_glass_panel_with_accent(panel):
    assert isinstance(panel, GlassPanel)
    panel.set_accent("#E2563A")
    assert panel.accent().name().upper() == "#E2563A"


# ---- controller (a real App with its window, never shown, on a temporary state file) ---------

def _args(tmp_path, **extra):
    return argparse.Namespace(screenshot=None, theme=None, age=None, seed=1, hour=None,
                              state=str(tmp_path / "state.json"), **extra)


def _wait_until(condition, timeout_ms=3000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    return condition()


@pytest.fixture
def controller(tmp_path):
    c = appmod.App(_args(tmp_path))
    yield c
    c._shutdown()
    c.window.destroy()


def test_pot_url_falls_back_to_the_default_pot(tmp_path):
    pot = tmp_path / "pot.glb"
    pot.write_bytes(b"glTF")
    assert appmod.pot_url("") == ""
    assert appmod.pot_url(str(tmp_path / "missing.glb")) == ""
    assert appmod.pot_url(str(pot)).startswith("file:///") and appmod.pot_url(str(pot)).endswith("/pot.glb")


def test_theme_labels_come_from_the_theme_table():
    expected = tuple((key, t["label"]) for key, t in themes.THEMES.items())
    assert THEME_LABELS == expected and THEME_CHOICES == expected


def test_regenerate_requests_are_coalesced(controller, monkeypatch):
    """Review focus 4: slider spam. A burst of requests costs one skeleton, not one per request."""
    calls = []
    real = tree.generate
    monkeypatch.setattr(tree, "generate", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(200):
        controller.regenerate()
    assert calls == []                      # nothing runs inside the 50 ms window
    assert _wait_until(lambda: calls)
    QTest.qWait(150)
    assert len(calls) == 1
    controller.regenerate(immediate=True)
    assert len(calls) == 2


def test_weather_arrives_on_the_main_thread_through_a_signal(controller, monkeypatch):
    seen = {}
    monkeypatch.setattr(sky, "fetch_weather", lambda lat, lon, timeout=5.0: (
        seen.__setitem__("worker", threading.get_ident()),
        {"temperature": 11.0, "humidity": 0.4, "radiation": 0.2})[1])
    real_slot = appmod.App._on_weather

    def on_weather(self, weather):
        seen["slot"] = threading.get_ident()
        real_slot(self, weather)

    monkeypatch.setattr(appmod.App, "_on_weather", on_weather)
    c = controller
    c._weather_signals.done.disconnect()
    c._weather_signals.done.connect(c._on_weather)   # reconnect to the patched slot
    c._start_weather_fetch()
    assert _wait_until(lambda: "slot" in seen)
    assert seen["worker"] != threading.get_ident()          # the request ran on a pool thread
    assert seen["slot"] == threading.get_ident()            # the result was applied on the main thread
    assert c.state.outdoor == sim.Outdoor(temperature=11.0, humidity=0.4, radiation=0.2)


def test_failed_weather_keeps_the_last_values(controller, monkeypatch):
    """Review focus 1 at app level: offline means fetch_weather gives None and nothing changes."""
    controller.state.outdoor = sim.Outdoor(temperature=5.0, humidity=0.3, radiation=0.1)
    monkeypatch.setattr(sky, "fetch_weather", lambda *a, **k: None)
    controller._start_weather_fetch()
    assert _wait_until(lambda: not controller._fetching)
    assert controller.state.outdoor == sim.Outdoor(temperature=5.0, humidity=0.3, radiation=0.1)
    assert not controller._weather_ok


def test_a_stale_geocode_answer_is_dropped(controller, monkeypatch):
    monkeypatch.setattr(sky, "fetch_weather", lambda *a, **k: None)
    controller._geocode_wanted = "Busan"
    controller._on_geocode("Seoul", {"city": "Seoul", "lat": 37.5, "lon": 127.0})
    assert controller.state.city == "Seoul" and controller.state.lat == 37.57      # the defaults, untouched
    controller._on_geocode("Busan", {"city": "Busan", "lat": 35.1, "lon": 129.0})
    assert (controller.state.city, controller.state.lat, controller.state.lon) == ("Busan", 35.1, 129.0)
    assert _wait_until(lambda: not controller._fetching)


def test_shutdown_stops_the_timers_and_saves_once(controller, monkeypatch):
    saves = []
    real = sim.save
    monkeypatch.setattr(sim, "save", lambda *a, **k: saves.append(1) or real(*a, **k))
    for timer in (controller._tick_timer, controller._save_timer, controller._weather_timer):
        timer.start()
    controller._shutdown()
    assert len(saves) == 1
    assert not any(t.isActive() for t in (controller._tick_timer, controller._save_timer, controller._weather_timer))
    assert controller._state_path.is_file()


def test_corrupt_state_file_starts_a_fresh_plant(tmp_path):
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    c = appmod.App(_args(tmp_path))
    try:
        assert (tmp_path / "state.json.bak").read_text(encoding="utf-8") == "{not json"
        assert c.state.controls.time_scale == appmod.FIRST_RUN_TIME_SCALE
        assert c.state.age == appmod.FIRST_RUN_AGE
    finally:
        c.window.destroy()


def test_offscreen_window_and_missing_pot_fall_back(tmp_path):
    """Review focus 5: a saved position on no screen is recentered, a pot file that is gone shows the default."""
    state = sim.PlantState(pot_path=str(tmp_path / "gone.glb"), window={"x": 99999, "y": 99999, "w": 420, "h": 640})
    sim.save(state, tmp_path / "state.json")
    c = appmod.App(_args(tmp_path))
    try:
        assert c.bridge.potSource == ""
        screens = appmod._screen_rects()
        g = c.window.geometry()
        assert any(sx <= g.center().x() < sx + sw and sy <= g.center().y() < sy + sh for sx, sy, sw, sh in screens)
        assert c.state.window["x"] != 99999
    finally:
        c.window.destroy()


def test_click_through_is_disabled_without_a_tray(tmp_path, monkeypatch):
    """With no tray icon there would be no way out of click-through, so the menu entry is disabled."""
    monkeypatch.setattr(appmod.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    c = appmod.App(_args(tmp_path))
    try:
        assert c.tray is None and not c.actions["clickthrough"].isEnabled()
    finally:
        c.window.destroy()
