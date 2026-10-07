from datetime import datetime, timedelta, timezone

from fernal import sky, tree
from fernal.app import clamp_window, effective_radiation, local_time_at, mean_radiation, params_moved

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
