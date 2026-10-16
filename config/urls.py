from django.contrib import admin
from django.urls import path

from routing.views import route_api, route_map

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/route/", route_api, name="route-api"),
    path("map/", route_map, name="route-map"),
]
