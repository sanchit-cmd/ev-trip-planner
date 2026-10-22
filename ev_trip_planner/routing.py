from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Optional

from . import cache
from .models import Charger, IST, Route


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def fast_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2)) * 111.32
    return math.hypot(dx, (lat2 - lat1) * 110.57)


def make_route(coords_lonlat: list, distance_km: float, duration_min: float, step_km: float = 0.5) -> Route:
    pts = [(c[1], c[0]) for c in coords_lonlat]
    raw = [0.0]
    for a, b in zip(pts, pts[1:]):
        raw.append(raw[-1] + haversine(a[0], a[1], b[0], b[1]))
    scale = distance_km / raw[-1] if raw[-1] > 0 else 1.0
    keep_pts, keep_cum, last = [pts[0]], [0.0], 0.0
    for p, d in zip(pts[1:], raw[1:]):
        d *= scale
        if d - last >= step_km:
            keep_pts.append(p)
            keep_cum.append(d)
            last = d
    if keep_cum[-1] < distance_km - 1e-6:
        keep_pts.append(pts[-1])
        keep_cum.append(distance_km)
    return Route(keep_pts, keep_cum, distance_km, duration_min)


def project(route: Route, lat: float, lon: float) -> tuple:
    """(position along route in km, straight-line distance from route in km), nearest-vertex based."""
    best_i, best_d = 0, 1e18
    for i, (a, b) in enumerate(route.pts):
        d = fast_km(lat, lon, a, b)
        if d < best_d:
            best_i, best_d = i, d
    return route.cum[best_i], best_d


def point_at(route: Route, pos_km: float) -> tuple:
    i = min(range(len(route.cum)), key=lambda k: abs(route.cum[k] - pos_km))
    return route.pts[i]


def geocode(place: str) -> Optional[tuple]:
    data = cache.http_get_json("https://nominatim.openstreetmap.org/search",
                         {"q": place, "format": "json", "limit": 1, "countrycodes": os.getenv("GEOCODE_COUNTRY", "in")},
                         ttl=30 * 86400, min_interval=1.1)  # Nominatim policy: max 1 request/second
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", place)


def osrm_route(a: tuple, b: tuple) -> Route:
    base = os.getenv("OSRM_URL", "https://router.project-osrm.org")
    data = cache.http_get_json(f"{base}/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}",
                         {"overview": "full", "geometries": "geojson", "steps": "false"}, ttl=86400)
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"No route found: {data.get('code')}")
    r = data["routes"][0]
    return make_route(r["geometry"]["coordinates"], r["distance"] / 1000.0, r["duration"] / 60.0)


def temperature_at(lat: float, lon: float, when: datetime) -> Optional[float]:
    try:
        data = cache.http_get_json("https://api.open-meteo.com/v1/forecast",
                             {"latitude": round(lat, 2), "longitude": round(lon, 2), "hourly": "temperature_2m",
                              "forecast_days": 3, "timezone": "Asia/Kolkata"}, ttl=3600)
        target = when.astimezone(IST).replace(tzinfo=None)
        times = [datetime.fromisoformat(t) for t in data["hourly"]["time"]]
        i = min(range(len(times)), key=lambda k: abs(times[k] - target))
        return float(data["hourly"]["temperature_2m"][i])
    except Exception:  # noqa: BLE001  (weather is optional; fall back to a mild default)
        return None


def conn_kind(title: str) -> Optional[str]:
    t = (title or "").lower()
    if "ccs" in t or "combo" in t:
        return "CCS1" if "type 1" in t else "CCS2"
    if "chademo" in t:
        return "CHAdeMO"
    if "gb/t" in t:
        return "GBT"
    if "type 2" in t:
        return "Type2"
    if "type 1" in t:
        return "Type1"
    return None


def parse_ocm(pois: list) -> list:
    out = []
    for poi in pois:
        ai = poi.get("AddressInfo") or {}
        if ai.get("Latitude") is None or ai.get("Longitude") is None:
            continue
        if "private" in ((poi.get("UsageType") or {}).get("Title") or "").lower():
            continue
        kinds: dict = {}
        for c in poi.get("Connections") or []:
            k = conn_kind((c.get("ConnectionType") or {}).get("Title", ""))
            if k:
                kinds[k] = max(kinds.get(k, 0.0), float(c.get("PowerKW") or 0.0))
        if not kinds:
            continue
        out.append(Charger(
            id=str(poi.get("ID")), name=ai.get("Title") or "Charging station",
            network=(poi.get("OperatorInfo") or {}).get("Title") or "Unknown network",
            lat=float(ai["Latitude"]), lon=float(ai["Longitude"]), connectors=kinds,
            operational=(poi.get("StatusType") or {}).get("IsOperational"),
            updated=poi.get("DateLastStatusUpdate") or poi.get("DateLastVerified")))
    return out


def fetch_chargers(route: Route, spacing_km: float = 40.0, radius_km: float = 25.0) -> list:
    key = os.getenv("OCM_API_KEY")
    if not key:
        raise SystemExit("Set OCM_API_KEY (free key from openchargemap.org).")
    seen: dict = {}
    s = 0.0
    while True:
        lat, lon = point_at(route, min(s, route.total_km))
        pois = cache.http_get_json("https://api.openchargemap.io/v3/poi",
                             {"output": "json", "latitude": round(lat, 3), "longitude": round(lon, 3),
                              "distance": radius_km, "distanceunit": "KM", "maxresults": 200,
                              "countrycode": os.getenv("OCM_COUNTRY", "IN"), "verbose": "false", "key": key},
                             ttl=7 * 86400)
        for c in parse_ocm(pois):
            seen[c.id] = c
        if s >= route.total_km:
            break
        s += spacing_km
    return list(seen.values())
