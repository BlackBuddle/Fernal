import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from fernal import sky

KST = timezone(timedelta(hours=9))
SEOUL = (37.5665, 126.9780)


class FakeResponse:
    def __init__(self, payload):
        self._body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def patch_urlopen(monkeypatch, payload):
    calls = []

    def fake(url, timeout=None):
        calls.append((url, timeout))
        return FakeResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def patch_urlopen_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)


def seoul_sun(hour, minute=0, day=21, month=6):
    return sky.sun_position(*SEOUL, datetime(2026, month, day, hour, minute, tzinfo=KST))


def test_noon_is_max_elevation():
    noon, _ = seoul_sun(12, 30)
    morning, _ = seoul_sun(6)
    evening, _ = seoul_sun(18)
    assert noon > morning
    assert noon > evening
    # Summer solstice at 37.57N: 90 - 37.57 + 23.44 = 75.87 degrees
    assert 75.0 < noon < 76.5


def test_azimuth_clockwise_from_north():
    _, noon_az = seoul_sun(12, 30)
    _, morning_az = seoul_sun(9)
    _, evening_az = seoul_sun(16)
    assert abs(noon_az - 180.0) < 5.0
    assert 60.0 < morning_az < 120.0  # east in the morning
    assert 240.0 < evening_az < 300.0  # west in the afternoon


def test_night_elevation_negative():
    elevation, _ = seoul_sun(0)
    assert elevation < -6.0
    assert sky.day_factor(elevation) == 0.0


def test_same_instant_in_other_timezone_matches():
    a = sky.sun_position(*SEOUL, datetime(2026, 6, 21, 12, 30, tzinfo=KST))
    b = sky.sun_position(*SEOUL, datetime(2026, 6, 21, 3, 30, tzinfo=timezone.utc))
    assert a == pytest.approx(b)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        sky.sun_position(*SEOUL, datetime(2026, 6, 21, 12, 0))


def test_day_factor_bounds():
    assert sky.day_factor(-90.0) == 0.0
    assert sky.day_factor(-6.0) == 0.0
    assert sky.day_factor(0.0) == pytest.approx(0.5)
    assert sky.day_factor(6.0) == 1.0
    assert sky.day_factor(90.0) == 1.0
    values = [sky.day_factor(e) for e in range(-10, 11)]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert values == sorted(values)


def test_fetch_weather_failure_returns_none(monkeypatch):
    patch_urlopen_failure(monkeypatch)
    assert sky.fetch_weather(*SEOUL) is None


def test_fetch_weather_malformed_returns_none(monkeypatch):
    patch_urlopen(monkeypatch, {"current": {"temperature_2m": 21.5}})
    assert sky.fetch_weather(*SEOUL) is None
    patch_urlopen(monkeypatch, b"not json")
    assert sky.fetch_weather(*SEOUL) is None


def test_fetch_weather_parses(monkeypatch):
    calls = patch_urlopen(
        monkeypatch,
        {"current": {"temperature_2m": 21.5, "relative_humidity_2m": 60, "shortwave_radiation": 400}},
    )
    result = sky.fetch_weather(37.5, 127.0, timeout=3.0)
    assert result == {"temperature": 21.5, "humidity": 0.6, "radiation": 0.5}
    url, timeout = calls[0]
    assert url.startswith("https://api.open-meteo.com/v1/forecast?")
    assert "latitude=37.5" in url and "longitude=127.0" in url
    assert "current=temperature_2m,relative_humidity_2m,shortwave_radiation" in url
    assert timeout == 3.0


def test_fetch_weather_radiation_clamped(monkeypatch):
    patch_urlopen(
        monkeypatch,
        {"current": {"temperature_2m": 30.0, "relative_humidity_2m": 40, "shortwave_radiation": 1000}},
    )
    assert sky.fetch_weather(*SEOUL)["radiation"] == 1.0


def test_geocode_parses(monkeypatch):
    calls = patch_urlopen(
        monkeypatch,
        {"results": [{"name": "서울", "latitude": 37.566, "longitude": 126.978, "country": "KR"}]},
    )
    assert sky.geocode("Seoul") == {"city": "서울", "lat": 37.566, "lon": 126.978}
    url, timeout = calls[0]
    assert url.startswith("https://geocoding-api.open-meteo.com/v1/search?")
    assert "name=Seoul" in url and "count=1" in url and "language=ko" in url
    assert timeout == 5.0


def test_geocode_no_results_or_failure_returns_none(monkeypatch):
    patch_urlopen(monkeypatch, {"generationtime_ms": 0.5})
    assert sky.geocode("Nowhereville") is None
    patch_urlopen_failure(monkeypatch)
    assert sky.geocode("Seoul") is None
    assert sky.geocode("   ") is None
