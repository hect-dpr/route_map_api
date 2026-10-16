from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from routing.services.planner import PlannerError, plan_route


def _parse_locations(request: HttpRequest) -> tuple[str, str]:
    start = (request.GET.get("start") or request.GET.get("from") or "").strip()
    finish = (request.GET.get("finish") or request.GET.get("to") or request.GET.get("end") or "").strip()
    return start, finish


@require_GET
def route_api(request: HttpRequest) -> JsonResponse:
    """
    GET /api/route/?start=Chicago,IL&finish=Dallas,TX

    Also accepts lat,lon: start=41.88,-87.63&finish=32.78,-96.80
    """
    start, finish = _parse_locations(request)
    if not start or not finish:
        return JsonResponse(
            {
                "error": "Query params 'start' and 'finish' are required "
                "(US place names or 'lat,lon')."
            },
            status=400,
        )

    try:
        result = plan_route(start, finish)
    except PlannerError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 — surface unexpected errors cleanly
        return JsonResponse({"error": f"Unexpected error: {exc}"}, status=500)

    return JsonResponse(result)


@require_GET
def route_map(request: HttpRequest) -> HttpResponse:
    """HTML Leaflet map of the route + fuel stops (uses the same planner)."""
    start, finish = _parse_locations(request)
    if not start or not finish:
        return HttpResponse(
            "Provide ?start=...&finish=... (US locations)",
            status=400,
            content_type="text/plain",
        )

    try:
        result = plan_route(start, finish)
    except PlannerError as exc:
        return HttpResponse(str(exc), status=400, content_type="text/plain")

    return render(
        request,
        "routing/map.html",
        {
            "start": start,
            "finish": finish,
            "result_json": json.dumps(result),
            "distance_miles": result["distance_miles"],
            "total_cost": result["fuel"]["total_fuel_cost_usd"],
            "stops_count": len(result["fuel"]["stops"]),
        },
    )
