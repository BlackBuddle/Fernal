"""Plant environment simulation and the state file (standard library only)."""
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field, fields, is_dataclass
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

_WEIGHTS = {"water": 0.25, "nutrients": 0.15, "temperature": 0.20,
            "humidity": 0.10, "light": 0.20, "affection": 0.10}
_FALLOFF = {"temperature": 10.0}    # score reaches 0 at this distance; others use the band width
_ENV_FIELDS = tuple(f.name for f in fields(Env))
_THEMES = ("erdtree", "normal", "fruit")


def _clamp(value, lo=0.0, hi=1.0):
    return lo if value < lo else hi if value > hi else value


def _clamp_env(name, value):
    """Clamp one Env value to its range (temperature in degC has no 0..1 range)."""
    return float(value) if name == "temperature" else _clamp(float(value))


def vitality_of(env: Env) -> float:
    """Weighted score 0..1: 1.0 inside every OPTIMUM band, falling linearly outside it."""
    total = 0.0
    for name, weight in _WEIGHTS.items():
        lo, hi = OPTIMUM[name]
        value = getattr(env, name)
        distance = max(lo - value, value - hi, 0.0)
        total += weight * max(0.0, 1.0 - distance / _FALLOFF.get(name, hi - lo))
    return _clamp(total)


def growth_rate(env: Env, vitality: float) -> float:
    """Plant hours gained per real hour: temperature bell x light factor x vitality.

    The bell is exp(-(d/10)^2) with d the distance from 22 degC, so it peaks at 1.0
    and falls to 1/e at 12 and 32 degC.
    """
    bell = math.exp(-(((env.temperature - 22.0) / 10.0) ** 2))
    return bell * (0.3 + 0.7 * _clamp(env.light)) * vitality


def step(state: PlantState, outdoor: Outdoor, dt_seconds: float) -> None:
    """Advance the environment and the plant age by dt_seconds. Never touches state.outdoor."""
    h = max(0.0, dt_seconds) / 3600.0
    env, controls = state.env, state.controls
    env.temperature = outdoor.temperature + _clamp(controls.heater, -10.0, 10.0)
    env.light = _clamp(outdoor.radiation)
    env.water = _clamp(env.water - h * (0.01 + 0.02 * env.light
                                        + 0.001 * max(0.0, env.temperature - 20.0)))
    env.nutrients = _clamp(env.nutrients - h * 0.1 / 24.0)
    env.affection = _clamp(env.affection - h * 0.1 / 24.0)
    target = _clamp(0.3 + 0.5 * env.water + 0.2 * outdoor.humidity
                    - 0.15 * env.light - 0.005 * (env.temperature - 22.0))
    env.humidity = _clamp(env.humidity + (target - env.humidity) * min(1.0, 0.5 * h))
    for name, value in controls.forced.items():
        if name in _ENV_FIELDS:
            setattr(env, name, _clamp_env(name, value))
    state.vitality = vitality_of(env)
    state.age += h * max(0.0, controls.time_scale) * growth_rate(env, state.vitality)


def catch_up(state: PlantState, outdoor: Outdoor, elapsed_seconds: float,
             slice_seconds: float = 600.0, cap_seconds: float = 7 * 86400.0) -> None:
    """Replay elapsed time (capped) through step() in fixed slices."""
    remaining = min(elapsed_seconds, cap_seconds)
    slice_seconds = max(slice_seconds, 1.0)
    while remaining > 0.0:
        dt = min(slice_seconds, remaining)
        step(state, outdoor, dt)
        remaining -= dt


def water(state: PlantState, amount: float = 0.2) -> None:
    state.env.water = _clamp(state.env.water + amount)


def feed(state: PlantState, amount: float = 0.3) -> None:
    state.env.nutrients = _clamp(state.env.nutrients + amount)


def spray(state: PlantState, amount: float = 0.15) -> None:
    state.env.humidity = _clamp(state.env.humidity + amount)


def touch(state: PlantState, amount: float = 0.05) -> None:
    state.env.affection = _clamp(state.env.affection + amount)


def to_dict(state: PlantState) -> dict:
    """JSON-ready dict; nested dataclasses and dicts are copied."""
    return asdict(state)


def _coerce(default, value):
    """Convert a JSON value to the type of its field default; raise on nonsense."""
    kind = type(default)
    if kind is float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return value
    if kind is int:
        return int(value)
    if kind is str:
        if not isinstance(value, str):
            raise TypeError("expected a string")
        return value
    return value


def _dict_field(name, default, value):
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a dict")
    if name == "forced":    # only Env fields can be pinned
        return {k: _coerce(0.0, v) for k, v in value.items() if k in _ENV_FIELDS}
    merged = dict(default)  # window: defaults for missing keys, extra keys kept
    for key, item in value.items():
        merged[key] = _coerce(default[key], item) if key in default else item
    return merged


def _build(cls, data):
    """Build dataclass cls from data: unknown keys ignored, missing keys keep defaults."""
    if not isinstance(data, dict):
        raise TypeError(f"{cls.__name__} data must be a dict")
    obj = cls()
    for f in fields(cls):
        if f.name not in data:
            continue
        current, value = getattr(obj, f.name), data[f.name]
        if is_dataclass(current):
            value = _build(type(current), value)
        elif isinstance(current, dict):
            value = _dict_field(f.name, current, value)
        else:
            value = _coerce(current, value)
        setattr(obj, f.name, value)
    return obj


def from_dict(d: dict) -> PlantState:
    """Inverse of to_dict. Raises TypeError/ValueError/OverflowError on malformed values."""
    state = _build(PlantState, d)
    if state.theme not in _THEMES:
        state.theme = PlantState().theme
    return state


def save(state: PlantState, path: Path) -> None:
    """Stamp last_saved and write the state atomically (temp file, then os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.last_saved = time.time()
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(to_dict(state), f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path: Path) -> PlantState:
    """Read the state file. Missing -> fresh state. Corrupt -> move to .bak, fresh state."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            return from_dict(json.load(f))
    except FileNotFoundError:
        return PlantState()
    except (OSError, ValueError, TypeError, OverflowError):
        try:
            os.replace(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass
        return PlantState()
