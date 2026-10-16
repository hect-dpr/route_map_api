"""Geocode US place names via Nominatim, with DB caching to minimize API calls."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests
from django.conf import settings

from routing.models import GeocodeCache

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = getattr(settings, "GEOCODER_USER_AGENT", "RouteMapAPI/1.0 (fuel-route-assessment)")

# Nominatim usage policy: max ~1 request/second
_last_request_at = 0.0


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    display_name: str = ""


class GeocodingError(Exception):
    pass


def _rate_limit() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _last_request_at = time.monotonic()


def geocode(location: str) -> GeoPoint:
    """Resolve a free-text US location to coordinates. Uses cache when possible."""
    query = location.strip()
    if not query:
        raise GeocodingError("Location is empty")

    # Normalize cache key
    cache_key = query.lower()
    cached = GeocodeCache.objects.filter(query=cache_key).first()
    if cached:
        return GeoPoint(cached.latitude, cached.longitude, cached.display_name)

    # Accept "lat,lon" directly to skip external geocoding
    if "," in query:
        parts = [p.strip() for p in query.split(",")]
        if len(parts) == 2:
            try:
                lat, lon = float(parts[0]), float(parts[1])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    # Heuristic: US-ish lon is typically negative; still allow explicit coords
                    GeocodeCache.objects.update_or_create(
                        query=cache_key,
                        defaults={
                            "latitude": lat,
                            "longitude": lon,
                            "display_name": f"{lat},{lon}",
                        },
                    )
                    return GeoPoint(lat, lon, f"{lat},{lon}")
            except ValueError:
                pass

    _rate_limit()
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding failed for '{query}': {exc}") from exc

    if not data:
        raise GeocodingError(f"Could not find location: {query}")

    result = data[0]
    point = GeoPoint(float(result["lat"]), float(result["lon"]), result.get("display_name", query))
    GeocodeCache.objects.update_or_create(
        query=cache_key,
        defaults={
            "latitude": point.latitude,
            "longitude": point.longitude,
            "display_name": point.display_name,
        },
    )
    return point
