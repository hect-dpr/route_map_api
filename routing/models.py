from django.db import models


class FuelStation(models.Model):
    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=512)
    city = models.CharField(max_length=128, db_index=True)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.IntegerField(null=True, blank=True)
    retail_price = models.FloatField()
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["state", "city"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.retail_price:.3f}"


class GeocodeCache(models.Model):
    """Cache Nominatim results so repeat requests avoid external geocoding calls."""

    query = models.CharField(max_length=512, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    display_name = models.CharField(max_length=1024, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.query
