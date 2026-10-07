"""Sun position (NOAA approximation) and Open-Meteo weather/geocoding. Stdlib only."""

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FULL_SUN_WM2 = 800.0


def sun_position(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Return (elevation_deg, azimuth_deg) of the sun; azimuth is clockwise from north.

    `when` must be timezone-aware. Uses the NOAA fractional-year approximation
    (equation of time, declination, hour angle) without atmospheric refraction.
    """
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("when must be timezone-aware")
    utc = when.astimezone(timezone.utc)

    day_of_year = utc.timetuple().tm_yday
    hours = utc.hour + utc.minute / 60.0 + utc.second / 3600.0 + utc.microsecond / 3.6e9
    g = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (hours - 12.0) / 24.0)

    eq_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )  # minutes
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )  # radians

    solar_minutes = hours * 60.0 + eq_time + 4.0 * lon  # true solar time, UTC clock
    hour_angle = math.radians(solar_minutes / 4.0 - 180.0)

    phi = math.radians(lat)
    sin_elev = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))

    # atan2 form is measured from south, westward positive; +180 gives north-clockwise.
    south_based = math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(phi) - math.tan(decl) * math.cos(phi),
    )
    azimuth = (math.degrees(south_based) + 180.0) % 360.0
    return elevation, azimuth


def day_factor(elevation_deg: float) -> float:
    """Linear blend 0 (night) .. 1 (day) over elevation -6..+6 degrees."""
    return max(0.0, min(1.0, (elevation_deg + 6.0) / 12.0))


def _get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_weather(lat: float, lon: float, timeout: float = 5.0) -> "dict | None":
    """Current weather as {"temperature", "humidity" 0..1, "radiation" 0..1}, or None on any failure."""
    query = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,shortwave_radiation",
        },
        safe=",",
    )
    try:
        cur = _get_json(f"{_FORECAST_URL}?{query}", timeout)["current"]
        return {
            "temperature": float(cur["temperature_2m"]),
            "humidity": float(cur["relative_humidity_2m"]) / 100.0,
            "radiation": max(0.0, min(1.0, float(cur["shortwave_radiation"]) / _FULL_SUN_WM2)),
        }
    except Exception:
        return None


def geocode(name: str, timeout: float = 5.0) -> "dict | None":
    """Resolve a city name to {"city", "lat", "lon"} via Open-Meteo, or None if not found or on failure."""
    if not name or not name.strip():
        return None
    query = urllib.parse.urlencode({"name": name.strip(), "count": 1, "language": "ko"})
    try:
        hit = _get_json(f"{_GEOCODE_URL}?{query}", timeout)["results"][0]
        return {
            "city": str(hit["name"]),
            "lat": float(hit["latitude"]),
            "lon": float(hit["longitude"]),
        }
    except Exception:
        return None
