"""OSRM public demo server — free routing, no API key required.

Docs: https://project-osrm.org/docs/v5.24.0/api/#route-service
Demo: https://router.project-osrm.org
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings

OSRM_BASE = getattr(settings, "OSRM_BASE_URL", "https://router.project-osrm.org")
USER_AGENT = getattr(settings, "GEOCODER_USER_AGENT", "RouteMapAPI/1.0 (fuel-route-assessment)")
METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class RouteResult:
    distance_miles: float
    duration_seconds: float
    # GeoJSON coordinates as [lon, lat] pairs
    coordinates: list[list[float]]
    # Cumulative distance in miles at each coordinate
    cumulative_miles: list[float]


class RoutingError(Exception):
    pass


def _haversine_miles(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in miles between two WGS84 points."""
    from math import asin, cos, radians, sin, sqrt

    r = 3958.7613  # Earth radius miles
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def get_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float) -> RouteResult:
    """Fetch a driving route. Single HTTP call to OSRM."""
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"{OSRM_BASE}/route/v1/driving/{coords}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise RoutingError(f"OSRM request failed: {exc}") from exc

    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RoutingError(f"OSRM could not find a route: {payload.get('code', 'unknown')}")

    route = payload["routes"][0]
    coordinates: list[list[float]] = route["geometry"]["coordinates"]
    if len(coordinates) < 2:
        raise RoutingError("OSRM returned an empty route geometry")

    cumulative = [0.0]
    for i in range(1, len(coordinates)):
        lon1, lat1 = coordinates[i - 1]
        lon2, lat2 = coordinates[i]
        cumulative.append(cumulative[-1] + _haversine_miles(lon1, lat1, lon2, lat2))

    # Prefer OSRM's reported distance (road network) as authoritative total
    distance_miles = route["distance"] / METERS_PER_MILE
    # Scale cumulative distances to match OSRM total (haversine underestimates roads)
    if cumulative[-1] > 0:
        scale = distance_miles / cumulative[-1]
        cumulative = [d * scale for d in cumulative]

    return RouteResult(
        distance_miles=distance_miles,
        duration_seconds=route["duration"],
        coordinates=coordinates,
        cumulative_miles=cumulative,
    )
