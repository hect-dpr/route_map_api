"""Orchestrates geocoding → OSRM route → local fuel optimization.

External HTTP calls per request (worst case):
  1. Nominatim geocode start  (skipped if cached or lat,lon provided)
  2. Nominatim geocode finish (skipped if cached or lat,lon provided)
  3. OSRM route               (always one call)

Ideal path after warm cache: exactly 1 external call (OSRM).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from django.conf import settings

from routing.services.fuel_optimizer import FuelPlan, FuelPlanningError, plan_fuel_stops
from routing.services.geocoding import GeocodingError, GeoPoint, geocode
from routing.services.osrm import RouteResult, RoutingError, get_route
from routing.services.station_index import station_index


@dataclass
class RoutePlanResponse:
    start: dict[str, Any]
    finish: dict[str, Any]
    distance_miles: float
    duration_hours: float
    fuel: dict[str, Any]
    route_geojson: dict[str, Any]
    fuel_stops_geojson: dict[str, Any]
    map_url: str
    map_embed_url: str
    attribution: str
    external_api_calls: dict[str, int]


class PlannerError(Exception):
    pass


def _point_dict(label: str, point: GeoPoint) -> dict[str, Any]:
    return {
        "input": label,
        "latitude": point.latitude,
        "longitude": point.longitude,
        "display_name": point.display_name,
    }


def _build_map_url(start: GeoPoint, finish: GeoPoint, stops: list) -> str:
    """OpenStreetMap directions link (no extra API call)."""
    # OSM directions: lat,lon pairs
    return (
        "https://www.openstreetmap.org/directions?"
        f"engine=fossgis_osrm_car&route={start.latitude}%2C{start.longitude}%3B"
        f"{finish.latitude}%2C{finish.longitude}"
    )


def _build_embed_url(start_location: str, finish_location: str) -> str:
    """Point clients at this app's Leaflet map (OSM.org embed often 403s apps)."""
    from urllib.parse import urlencode

    return "/map/?" + urlencode({"start": start_location, "finish": finish_location})


def plan_route(start_location: str, finish_location: str) -> dict[str, Any]:
    if station_index.size == 0:
        station_index.load()
    if station_index.size == 0:
        raise PlannerError("No geocoded fuel stations loaded. Run: python manage.py load_fuel_stations")

    api_calls = {"geocode": 0, "routing": 0}

    from routing.models import GeocodeCache

    def _is_lat_lon(raw: str) -> bool:
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 2:
            return False
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            return False
        return -90 <= lat <= 90 and -180 <= lon <= 180

    def _geocode_counted(raw: str) -> GeoPoint:
        key = raw.strip().lower()
        if _is_lat_lon(raw):
            return geocode(raw)  # no external HTTP
        was_cached = GeocodeCache.objects.filter(query=key).exists()
        point = geocode(raw)
        if not was_cached:
            api_calls["geocode"] += 1
        return point

    try:
        start = _geocode_counted(start_location)
        finish = _geocode_counted(finish_location)
    except GeocodingError as exc:
        raise PlannerError(str(exc)) from exc

    try:
        route = get_route(start.longitude, start.latitude, finish.longitude, finish.latitude)
        api_calls["routing"] += 1
    except RoutingError as exc:
        raise PlannerError(str(exc)) from exc

    corridor = getattr(settings, "FUEL_CORRIDOR_MILES", 10.0)
    nearby = station_index.stations_near_route(
        route.coordinates,
        route.cumulative_miles,
        corridor_miles=corridor,
    )

    try:
        fuel_plan: FuelPlan = plan_fuel_stops(nearby, route.distance_miles)
    except FuelPlanningError as exc:
        raise PlannerError(str(exc)) from exc

    route_geojson = {
        "type": "Feature",
        "properties": {
            "distance_miles": round(route.distance_miles, 2),
            "duration_seconds": round(route.duration_seconds, 1),
        },
        "geometry": {
            "type": "LineString",
            "coordinates": route.coordinates,
        },
    }

    stop_features = []
    for i, stop in enumerate(fuel_plan.stops, start=1):
        stop_features.append(
            {
                "type": "Feature",
                "properties": {
                    "stop_number": i,
                    "name": stop.name,
                    "address": stop.address,
                    "city": stop.city,
                    "state": stop.state,
                    "retail_price_per_gallon": stop.retail_price,
                    "route_mile": stop.route_mile,
                    "gallons_purchased": stop.gallons_purchased,
                    "cost_usd": stop.cost,
                    "distance_to_route_miles": stop.distance_to_route_miles,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [stop.longitude, stop.latitude],
                },
            }
        )

    fuel_stops_geojson = {
        "type": "FeatureCollection",
        "features": stop_features,
    }

    result = RoutePlanResponse(
        start=_point_dict(start_location, start),
        finish=_point_dict(finish_location, finish),
        distance_miles=round(route.distance_miles, 2),
        duration_hours=round(route.duration_seconds / 3600.0, 2),
        fuel={
            "mpg": fuel_plan.mpg,
            "max_range_miles": fuel_plan.max_range_miles,
            "tank_gallons": fuel_plan.max_range_miles / fuel_plan.mpg,
            "stations_considered": len(nearby),
            "stops": [asdict(s) for s in fuel_plan.stops],
            "total_gallons": fuel_plan.total_gallons,
            "total_fuel_cost_usd": fuel_plan.total_cost,
            "note": (
                "Vehicle is assumed to start with a full tank (not charged). "
                "Cost covers fuel purchased at optimal stops along the route."
            ),
        },
        route_geojson=route_geojson,
        fuel_stops_geojson=fuel_stops_geojson,
        map_url=_build_map_url(start, finish, fuel_plan.stops),
        map_embed_url=_build_embed_url(start_location, finish_location),
        attribution=(
            "Routing © OSRM / OpenStreetMap contributors (ODbL). "
            "Geocoding © Nominatim / OpenStreetMap contributors."
        ),
        external_api_calls=api_calls,
    )
    payload = asdict(result)
    # Convenience link to this app's Leaflet map for the same query
    from urllib.parse import urlencode

    payload["interactive_map_path"] = "/map/?" + urlencode(
        {"start": start_location, "finish": finish_location}
    )
    return payload
