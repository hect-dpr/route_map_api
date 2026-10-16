"""In-memory spatial index of geocoded fuel stations for fast corridor queries."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.spatial import cKDTree

from routing.models import FuelStation

logger = logging.getLogger(__name__)

# Earth radius in miles — used to convert KDTree radian distances
EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class StationHit:
    station_id: int
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    retail_price: float
    latitude: float
    longitude: float
    route_mile: float
    distance_to_route_miles: float


class StationSpatialIndex:
    """KDTree over station lat/lon (in radians) for nearest-neighbor lookups."""

    def __init__(self) -> None:
        self._stations: list[FuelStation] = []
        self._tree: Optional[cKDTree] = None
        self._coords_rad: Optional[np.ndarray] = None

    @property
    def size(self) -> int:
        return len(self._stations)

    def load(self) -> int:
        qs = FuelStation.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
        self._stations = list(qs)
        if not self._stations:
            self._tree = None
            self._coords_rad = None
            return 0

        coords = np.array(
            [[math.radians(s.latitude), math.radians(s.longitude)] for s in self._stations],
            dtype=np.float64,
        )
        self._coords_rad = coords
        self._tree = cKDTree(coords)
        logger.info("Loaded %d fuel stations into spatial index", len(self._stations))
        return len(self._stations)

    def stations_near_route(
        self,
        route_coords: list[list[float]],
        cumulative_miles: list[float],
        corridor_miles: float = 8.0,
        sample_step_miles: float = 5.0,
    ) -> list[StationHit]:
        """
        Find stations within `corridor_miles` of the route.

        Samples the route every `sample_step_miles` and queries the KDTree,
        then assigns each station its nearest route mile marker.
        """
        if self._tree is None or not route_coords:
            return []

        # Build sampled route points for querying
        sample_indices = [0]
        last_mile = 0.0
        for i, mile in enumerate(cumulative_miles):
            if mile - last_mile >= sample_step_miles:
                sample_indices.append(i)
                last_mile = mile
        if sample_indices[-1] != len(route_coords) - 1:
            sample_indices.append(len(route_coords) - 1)

        # Angular radius for corridor
        radius_rad = corridor_miles / EARTH_RADIUS_MILES

        candidate_ids: set[int] = set()
        for idx in sample_indices:
            lon, lat = route_coords[idx]
            point = np.array([math.radians(lat), math.radians(lon)])
            neighbors = self._tree.query_ball_point(point, r=radius_rad)
            candidate_ids.update(neighbors)

        if not candidate_ids:
            return []

        # Build KDTree over route points to assign route_mile + distance-to-route
        route_rad = np.array(
            [[math.radians(lat), math.radians(lon)] for lon, lat in route_coords],
            dtype=np.float64,
        )
        route_tree = cKDTree(route_rad)

        hits: list[StationHit] = []
        for sid in candidate_ids:
            station = self._stations[sid]
            dist_rad, route_idx = route_tree.query(
                [math.radians(station.latitude), math.radians(station.longitude)]
            )
            dist_miles = float(dist_rad) * EARTH_RADIUS_MILES
            if dist_miles > corridor_miles:
                continue
            hits.append(
                StationHit(
                    station_id=station.pk,
                    opis_id=station.opis_id,
                    name=station.name,
                    address=station.address,
                    city=station.city,
                    state=station.state,
                    retail_price=station.retail_price,
                    latitude=station.latitude,
                    longitude=station.longitude,
                    route_mile=float(cumulative_miles[int(route_idx)]),
                    distance_to_route_miles=dist_miles,
                )
            )

        # Deduplicate by (opis_id, rounded route mile) keeping cheapest
        hits.sort(key=lambda h: (h.route_mile, h.retail_price))
        return hits


# Process-wide singleton loaded once at startup / after import command
station_index = StationSpatialIndex()
