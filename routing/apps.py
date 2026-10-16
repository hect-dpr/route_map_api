from django.apps import AppConfig


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "routing"
    # Spatial index is loaded lazily on first API request (see planner.plan_route).
