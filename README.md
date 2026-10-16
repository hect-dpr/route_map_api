# Route Map API

Django API that routes between two US locations, picks **cost-optimal fuel stops** along the drive (500 mi range, 10 MPG), and returns a map-ready GeoJSON payload plus total fuel cost.

## Stack


| Piece          | Choice                                                                                      |
| -------------- | ------------------------------------------------------------------------------------------- |
| Framework      | Django 6.1                                                                                  |
| Routing        | [OSRM](https://project-osrm.org) public demo (`router.project-osrm.org`) — free, no API key |
| Geocoding      | [Nominatim](https://nominatim.openstreetmap.org) (cached in DB)                             |
| Fuel prices    | `data/fuel-prices-for-be-assessment.csv`                                                    |
| Station coords | Local US cities gazetteer (no per-request geocoding of truck stops)                         |
| Map UI         | Leaflet + CARTO basemap (OSM data) at `/map/`                                               |




### External API budget


| Scenario                | Calls                  |
| ----------------------- | ---------------------- |
| Place names, cold cache | 2× Nominatim + 1× OSRM |
| Place names, warm cache | **1× OSRM**            |
| `lat,lon` inputs        | **1× OSRM**            |


Fuel-stop selection is entirely local (KDTree over preloaded stations).

## Setup

```bash
cd route_map_api
python3.14 -m venv .venv-3.14
source .venv-3.14/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py load_fuel_stations --replace
python manage.py runserver
```



## API



### `GET /api/route/`

**Query params**

- `start` — US place name or `lat,lon` (aliases: `from`)
- `finish` — US place name or `lat,lon` (aliases: `to`, `end`)

**Example**

```bash
curl -s 'http://127.0.0.1:8000/api/route/?start=Chicago,IL&finish=Dallas,TX' | python -m json.tool
```

**Response highlights**

- `route_geojson` — drive path as GeoJSON LineString
- `fuel_stops_geojson` — optimal fill-up points
- `fuel.stops` — name, price, gallons, cost, route mile
- `fuel.total_fuel_cost_usd` — money spent on fuel (starts with a full tank; that starting fuel is not charged)
- `map_url` — OpenStreetMap directions link
- `external_api_calls` — how many geocode/routing HTTP calls this request made



### `GET /map/?start=...&finish=...`

Interactive Leaflet map of the same plan.

## Fuel optimization

1. OSRM returns the full route geometry once.
2. Stations within ~10 miles of the route are candidates (spatial index).
3. Greedy optimal 1-D refueling: prefer cheaper stations ahead; fill only as much as needed to reach the next cheaper stop, otherwise fill up. Max range 500 miles @ 10 MPG.

