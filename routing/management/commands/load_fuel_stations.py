"""Load fuel price CSV and attach coordinates from a US cities gazetteer.

No external API calls — city centroids are matched locally so the route API
stays fast and does not need to geocode ~8k truck stops per request.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from routing.models import FuelStation
from routing.services.station_index import station_index

STATE_NAME_TO_ABBR = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def _norm_city(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    name = name.replace(".", "")
    # Common suffixes that differ between datasets
    for suffix in (" city", " town", " village", " borough", " cdp"):
        if name.endswith(suffix) and name != suffix.strip():
            name = name[: -len(suffix)]
    return name.strip()


def _norm_state(raw: str) -> str:
    raw = raw.strip()
    if len(raw) == 2:
        return raw.upper()
    return STATE_NAME_TO_ABBR.get(raw.lower(), raw.upper()[:2])


def load_city_coords(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    """Map (norm_city, state_abbr) -> (lat, lon). Prefers denser / primary entries."""
    coords: dict[tuple[str, str], tuple[float, float]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # Support both kelvins/US-Cities-Database and simplemaps-style headers
        for row in reader:
            if "CITY" in row and "STATE_CODE" in row:
                city = row["CITY"]
                state = row["STATE_CODE"]
                lat = float(row["LATITUDE"])
                lon = float(row["LONGITUDE"])
            elif "city" in row and "state_id" in row:
                city = row["city"]
                state = row["state_id"]
                lat = float(row["lat"])
                lon = float(row["lng"])
            else:
                raise CommandError(f"Unrecognized cities CSV headers: {reader.fieldnames}")

            key = (_norm_city(city), _norm_state(state))
            # Keep first occurrence; gazetteer order is fine for centroids
            coords.setdefault(key, (lat, lon))
    return coords


class Command(BaseCommand):
    help = "Import fuel prices CSV and geocode stations via local US cities data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fuel-csv",
            default=str(settings.BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"),
            help="Path to fuel prices CSV",
        )
        parser.add_argument(
            "--cities-csv",
            default=str(settings.BASE_DIR / "data" / "us_cities.csv"),
            help="Path to US cities lat/lon CSV",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing FuelStation rows before import",
        )

    def handle(self, *args, **options):
        fuel_path = Path(options["fuel_csv"])
        cities_path = Path(options["cities_csv"])
        if not fuel_path.exists():
            raise CommandError(f"Fuel CSV not found: {fuel_path}")
        if not cities_path.exists():
            raise CommandError(f"Cities CSV not found: {cities_path}")

        self.stdout.write("Loading US city coordinates…")
        city_coords = load_city_coords(cities_path)
        self.stdout.write(self.style.SUCCESS(f"  {len(city_coords)} city centroids"))

        if options["replace"]:
            deleted, _ = FuelStation.objects.all().delete()
            self.stdout.write(f"Cleared {deleted} existing stations")

        matched = 0
        unmatched = 0
        batch: list[FuelStation] = []
        seen_keys: set[tuple] = set()

        with fuel_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                city = row["City"].strip()
                state = _norm_state(row["State"])
                key = (_norm_city(city), state)
                latlon = city_coords.get(key)
                # Deduplicate identical OPIS + address rows (CSV has some dupes)
                dedupe = (
                    row["OPIS Truckstop ID"].strip(),
                    row["Address"].strip(),
                    city,
                    state,
                )
                if dedupe in seen_keys:
                    continue
                seen_keys.add(dedupe)

                if latlon:
                    lat, lon = latlon
                    matched += 1
                else:
                    lat = lon = None
                    unmatched += 1

                batch.append(
                    FuelStation(
                        opis_id=int(row["OPIS Truckstop ID"]),
                        name=row["Truckstop Name"].strip(),
                        address=row["Address"].strip(),
                        city=city,
                        state=state,
                        rack_id=int(row["Rack ID"]) if row.get("Rack ID") else None,
                        retail_price=float(row["Retail Price"]),
                        latitude=lat,
                        longitude=lon,
                    )
                )

                if len(batch) >= 1000:
                    FuelStation.objects.bulk_create(batch, batch_size=1000)
                    batch.clear()

        if batch:
            FuelStation.objects.bulk_create(batch, batch_size=1000)

        total = FuelStation.objects.count()
        geocoded = FuelStation.objects.exclude(latitude__isnull=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {total} stations ({geocoded} geocoded, {unmatched} unmatched cities)"
            )
        )

        n = station_index.load()
        self.stdout.write(self.style.SUCCESS(f"Spatial index ready: {n} stations"))
