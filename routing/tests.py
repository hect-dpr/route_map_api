from django.test import SimpleTestCase, TestCase

from routing.services.fuel_optimizer import plan_fuel_stops
from routing.services.station_index import StationHit


def _station(mile: float, price: float, name: str = "S") -> StationHit:
    return StationHit(
        station_id=1,
        opis_id=1,
        name=name,
        address="addr",
        city="City",
        state="TX",
        retail_price=price,
        latitude=0.0,
        longitude=0.0,
        route_mile=mile,
        distance_to_route_miles=1.0,
    )


class FuelOptimizerTests(SimpleTestCase):
    def test_short_trip_needs_no_fuel(self):
        plan = plan_fuel_stops([_station(100, 3.0)], total_distance_miles=200)
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_cost, 0.0)

    def test_buys_only_what_is_needed_beyond_starting_tank(self):
        # 800 miles @ 10 MPG = 80 gal needed; start with 50 → buy ~30
        stations = [
            _station(400, 3.50, "mid"),
            _station(700, 3.00, "cheap"),
        ]
        plan = plan_fuel_stops(stations, total_distance_miles=800)
        self.assertAlmostEqual(plan.total_gallons, 30.0, places=2)
        self.assertGreater(plan.total_cost, 0)

    def test_prefers_cheaper_station(self):
        stations = [
            _station(300, 4.00, "expensive"),
            _station(400, 2.50, "cheap"),
        ]
        plan = plan_fuel_stops(stations, total_distance_miles=800)
        names = [s.name for s in plan.stops]
        self.assertIn("cheap", names)


class RouteApiSmokeTests(TestCase):
    def test_missing_params(self):
        resp = self.client.get("/api/route/")
        self.assertEqual(resp.status_code, 400)
