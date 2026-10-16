"""Cost-optimal fuel-stop planner for a fixed route.

Assumptions
-----------
- Vehicle range: 500 miles (full tank)
- Fuel economy: 10 MPG  →  tank = 50 gallons
- Depart with a full tank (starting fuel is not charged)
- Fuel is only purchased at stations from the provided price list
- Stations have already been projected onto route mile markers

Algorithm
---------
While the destination is not reachable on remaining fuel:
  1. Consider stations within the current remaining range.
  2. Choose where to stop:
       - First stop (no prior fill price): cheapest reachable station.
       - Later: if any reachable station is cheaper than the last fill,
         drive to the nearest of those; otherwise the cheapest reachable.
  3. At that station buy the minimum gallons needed:
       - enough to reach the next cheaper station within a full tank, or
       - enough to reach the destination if it lies within a full tank, or
       - a full tank when the destination is still more than one tank away.
"""

from __future__ import annotations

from dataclasses import dataclass

from routing.services.station_index import StationHit

MAX_RANGE_MILES = 500.0
MPG = 10.0


@dataclass
class FuelStop:
    name: str
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    retail_price: float
    route_mile: float
    gallons_purchased: float
    cost: float
    distance_to_route_miles: float


@dataclass
class FuelPlan:
    stops: list[FuelStop]
    total_cost: float
    total_gallons: float
    max_range_miles: float
    mpg: float


class FuelPlanningError(Exception):
    pass


def plan_fuel_stops(
    stations: list[StationHit],
    total_distance_miles: float,
    max_range_miles: float = MAX_RANGE_MILES,
    mpg: float = MPG,
) -> FuelPlan:
    if total_distance_miles <= 0:
        return FuelPlan(
            stops=[],
            total_cost=0.0,
            total_gallons=0.0,
            max_range_miles=max_range_miles,
            mpg=mpg,
        )

    tank = max_range_miles / mpg
    along = sorted(stations, key=lambda s: (s.route_mile, s.retail_price))
    along = [s for s in along if 0.5 < s.route_mile < total_distance_miles - 0.5]

    fuel = tank  # start full — not charged
    position = 0.0
    last_price = float("inf")
    stops: list[FuelStop] = []
    total_cost = 0.0
    total_gallons = 0.0

    for _ in range(10_000):
        miles_left = total_distance_miles - position
        if fuel * mpg >= miles_left - 1e-6:
            break

        reach = position + fuel * mpg
        reachable = [s for s in along if position < s.route_mile <= reach + 1e-6]
        if not reachable:
            raise FuelPlanningError(
                f"Cannot reach destination: no fuel station within range "
                f"from mile {position:.1f} (can reach mile {reach:.1f} of "
                f"{total_distance_miles:.1f})"
            )

        # First fill: last_price is +inf, so every station looks "cheaper" and
        # picking the nearest would stop at the earliest station in range.
        # With no prior purchase price, choose the cheapest reachable instead.
        if last_price == float("inf"):
            target = min(reachable, key=lambda s: (s.retail_price, s.route_mile))
        else:
            cheaper = [s for s in reachable if s.retail_price < last_price]
            if cheaper:
                target = min(cheaper, key=lambda s: s.route_mile)
            else:
                target = min(reachable, key=lambda s: (s.retail_price, s.route_mile))

        # Drive to target
        fuel -= (target.route_mile - position) / mpg
        position = target.route_mile
        if fuel < -1e-6:
            raise FuelPlanningError("Internal error: arrived with negative fuel")
        fuel = max(0.0, fuel)

        # Gallons still required to finish the trip from here
        gallons_to_finish = max(0.0, (total_distance_miles - position) / mpg - fuel)

        # Cheaper station within one full tank ahead?
        ahead_limit = position + max_range_miles
        cheaper_ahead = [
            s
            for s in along
            if position < s.route_mile <= ahead_limit and s.retail_price < target.retail_price
        ]

        if cheaper_ahead:
            next_cheap_mile = min(s.route_mile for s in cheaper_ahead)
            # Buy just enough to reach the next cheaper stop
            need = max(0.0, (next_cheap_mile - position) / mpg - fuel)
            gallons = min(need, tank - fuel, gallons_to_finish)
        elif position + max_range_miles >= total_distance_miles:
            # Destination reachable on a full tank — don't overfill
            gallons = min(tank - fuel, gallons_to_finish)
        else:
            # Need maximum range to keep options open
            gallons = tank - fuel

        gallons = max(0.0, gallons)
        cost = gallons * target.retail_price
        fuel += gallons
        total_cost += cost
        total_gallons += gallons
        last_price = target.retail_price

        if gallons > 1e-3:
            stops.append(
                FuelStop(
                    name=target.name,
                    address=target.address,
                    city=target.city,
                    state=target.state,
                    latitude=target.latitude,
                    longitude=target.longitude,
                    retail_price=target.retail_price,
                    route_mile=round(target.route_mile, 2),
                    gallons_purchased=round(gallons, 3),
                    cost=round(cost, 2),
                    distance_to_route_miles=round(target.distance_to_route_miles, 2),
                )
            )
    else:
        raise FuelPlanningError("Fuel planning aborted (loop limit)")

    return FuelPlan(
        stops=stops,
        total_cost=round(total_cost, 2),
        total_gallons=round(total_gallons, 3),
        max_range_miles=max_range_miles,
        mpg=mpg,
    )
