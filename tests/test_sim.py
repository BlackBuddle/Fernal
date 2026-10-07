import json
import time

import pytest

from fernal import sim
from fernal.sim import Env, Outdoor, PlantState


def day_outdoor(radiation=0.5):
    return Outdoor(temperature=22.0, humidity=0.5, radiation=radiation)


def test_water_evaporates_faster_in_light():
    dark, lit = PlantState(), PlantState()
    sim.step(dark, day_outdoor(0.0), 3600.0)
    sim.step(lit, day_outdoor(1.0), 3600.0)
    assert lit.env.water < dark.env.water < 0.6
    # 22 degC outdoor: 0.01 + 0.02 * light + 0.001 * 2 per hour
    assert dark.env.water == pytest.approx(0.6 - 0.012)
    assert lit.env.water == pytest.approx(0.6 - 0.032)


def test_nutrients_decay_per_day():
    state = PlantState()
    sim.step(state, day_outdoor(), 86400.0)
    assert state.env.nutrients == pytest.approx(0.5 - 0.1)
    assert state.env.affection == pytest.approx(0.5 - 0.1)


def test_vitality_is_one_at_optimum_and_lower_outside():
    assert sim.vitality_of(Env(water=0.6, nutrients=0.6, temperature=22.0,
                               humidity=0.6, light=0.6, affection=0.6)) == pytest.approx(1.0)
    best = Env(light=0.6)
    assert sim.vitality_of(best) == pytest.approx(1.0)
    dry = Env(light=0.6, water=0.0)       # 0.4 below the band: water score 0 (weight 0.25)
    assert sim.vitality_of(dry) == pytest.approx(0.75)
    cold = Env(light=0.6, temperature=7.0)  # 10 degC below the band: temperature score 0 (weight 0.20)
    assert sim.vitality_of(cold) == pytest.approx(0.80)
    flooded = Env(light=0.6, water=1.0)   # 0.2 above the band: water score 0.5
    assert sim.vitality_of(flooded) == pytest.approx(1.0 - 0.25 * 0.5)
    worst = Env(water=0.0, nutrients=0.0, temperature=-50.0, humidity=0.0, light=0.0, affection=0.0)
    # water and temperature score 0; the wide bands of the others leave partial scores at 0
    expected = 0.15 * 0.5 + 0.10 * (1 - 0.35 / 0.45) + 0.20 * (1 - 0.3 / 0.7) + 0.10 * (1 - 0.3 / 0.7)
    assert sim.vitality_of(worst) == pytest.approx(expected)


def test_growth_rate_bell_on_temperature():
    peak = sim.growth_rate(Env(temperature=22.0, light=1.0), 1.0)
    assert peak == pytest.approx(1.0)
    cool = sim.growth_rate(Env(temperature=12.0, light=1.0), 1.0)
    warm = sim.growth_rate(Env(temperature=32.0, light=1.0), 1.0)
    assert cool == pytest.approx(warm)
    assert 0.0 < cool < sim.growth_rate(Env(temperature=17.0, light=1.0), 1.0) < peak
    # light factor 0.3 + 0.7 * light, vitality scales linearly
    assert sim.growth_rate(Env(temperature=22.0, light=0.0), 1.0) == pytest.approx(0.3)
    assert sim.growth_rate(Env(temperature=22.0, light=1.0), 0.5) == pytest.approx(0.5)


def test_catch_up_is_capped():
    week, month = PlantState(), PlantState()
    sim.catch_up(week, day_outdoor(), 7 * 86400.0)
    start = time.perf_counter()
    sim.catch_up(month, day_outdoor(), 30 * 86400.0)
    assert time.perf_counter() - start < 1.0
    assert month.age > 0.0
    assert month.age == pytest.approx(week.age)
    assert month.env == week.env
    # a short replay matches a single step of the same length
    a, b = PlantState(), PlantState()
    sim.catch_up(a, day_outdoor(), 300.0)
    sim.step(b, day_outdoor(), 300.0)
    assert a == b


def test_json_round_trip(tmp_path):
    state = PlantState(seed=7, age=12.5, vitality=0.8, theme="fruit", pot_path="pots/a.glb",
                       city="서울", lat=35.1, lon=129.0)
    state.env = Env(water=0.3, nutrients=0.2, temperature=15.5, humidity=0.4, light=0.7, affection=0.9)
    state.controls = sim.Controls(heater=-3.0, time_scale=60.0, forced={"water": 0.3})
    state.window = {"x": -20, "y": 40, "w": 500, "h": 700}
    state.outdoor = Outdoor(temperature=3.0, humidity=0.8, radiation=0.25)
    data = sim.to_dict(state)
    assert isinstance(data["env"], dict) and isinstance(data["controls"], dict)
    assert sim.from_dict(json.loads(json.dumps(data))) == state

    path = tmp_path / "sub" / "state.json"
    sim.save(state, path)
    assert state.last_saved > 0.0
    assert not path.with_name("state.json.tmp").exists()
    assert sim.load(path) == state


def test_from_dict_ignores_unknown_keys():
    data = sim.to_dict(PlantState(seed=5))
    data["bogus"] = 1
    data["env"]["bogus"] = 2
    data["controls"]["bogus"] = 3
    data["controls"]["forced"] = {"water": 0.3, "nonsense": 1.0}
    del data["theme"]
    del data["env"]["water"]
    del data["outdoor"]
    state = sim.from_dict(data)
    assert state.seed == 5
    assert state.theme == "normal"
    assert state.env.water == 0.6
    assert state.outdoor == Outdoor()
    assert state.controls.forced == {"water": 0.3}
    assert sim.from_dict({}) == PlantState()
    assert sim.from_dict({"window": {"x": 5}}).window == {"x": 5, "y": 100, "w": 420, "h": 640}


@pytest.mark.parametrize("text", ["{not json", "", "[1, 2, 3]", '{"age": "abc"}',
                                  '{"env": 5}', '{"age": NaN}'])
def test_load_corrupt_file_backs_up(tmp_path, text):
    path = tmp_path / "state.json"
    path.write_text(text, encoding="utf-8")
    assert sim.load(path) == PlantState()
    backup = tmp_path / "state.json.bak"
    assert not path.exists()
    assert backup.read_text(encoding="utf-8") == text


def test_load_missing_file_returns_default(tmp_path):
    assert sim.load(tmp_path / "state.json") == PlantState()
    assert not (tmp_path / "state.json.bak").exists()


def test_forced_values_pin_env():
    state = PlantState()
    state.controls.forced = {"water": 0.3, "temperature": 35.0, "nonsense": 1.0}
    free = PlantState()
    for _ in range(6):
        sim.step(state, day_outdoor(), 600.0)
        sim.step(free, day_outdoor(), 600.0)
        assert state.env.water == 0.3
        assert state.env.temperature == 35.0
    # pinned values feed vitality and growth
    assert state.vitality == pytest.approx(sim.vitality_of(state.env))
    assert state.vitality < free.vitality
    assert state.age < free.age
    state.controls.forced = {"water": 5.0}
    sim.step(state, day_outdoor(), 600.0)
    assert state.env.water == 1.0


def test_tool_actions_raise_values_and_clamp():
    state = PlantState()
    sim.water(state)
    sim.feed(state)
    sim.spray(state)
    sim.touch(state)
    assert state.env.water == pytest.approx(0.8)
    assert state.env.nutrients == pytest.approx(0.8)
    assert state.env.humidity == pytest.approx(0.65)
    assert state.env.affection == pytest.approx(0.55)
    sim.water(state, 5.0)
    assert state.env.water == 1.0
