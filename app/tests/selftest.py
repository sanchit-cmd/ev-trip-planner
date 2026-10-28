from __future__ import annotations

import os
import random
from datetime import datetime
from typing import Any, Optional

from ..services import cache
from ..engine import language
from ..engine.language import numbers_ok, plan_facts, template_explanation
from ..core.models import Charger, Config, IST, TripRequest, VEHICLES, match_vehicle
from ..engine.planner import (charge_minutes, check_plan, consumption_wh_per_km, fmt_dur, plan_trip)
from ..ui.rendering import render_map
from ..services.routing import conn_kind, haversine, make_route, point_at
from ..workflow.graph import build_graph


def selftest() -> None:
    os.environ["EV_DB"] = ":memory:"
    os.environ["OCM_API_KEY"] = "test"
    cache._DB = None
    real = (cache.http_get_json, language.parse_with_llm, language.explain_with_llm)

    # --- unit checks ---------------------------------------------------------
    assert abs(haversine(28.6139, 77.2090, 26.9124, 75.7873) - 237) < 8
    v = VEHICLES["Tata Nexon EV"]
    assert consumption_wh_per_km(v, 70, 22) == v.wh_per_km
    assert consumption_wh_per_km(v, 70, 0) > consumption_wh_per_km(v, 70, 22) > 0
    assert charge_minutes(38.0, 0.2, 0.8, 50) > charge_minutes(38.0, 0.2, 0.5, 50) > 0
    assert charge_minutes(38.0, 0.2, 0.5, 100) < charge_minutes(38.0, 0.2, 0.5, 25)
    assert match_vehicle("nexon").name == "Tata Nexon EV" and match_vehicle("zs ev").name == "MG ZS EV"
    assert match_vehicle("Toyota Corolla") is None
    assert conn_kind("CCS (Type 2)") == "CCS2" and conn_kind("Type 2 (Socket Only)") == "Type2" and conn_kind("CHAdeMO") == "CHAdeMO"
    print("ok: energy, charging, vehicle matching, connector mapping")

    # --- synthetic corridor: Delhi -> Jaipur ---------------------------------
    A, B = (28.6139, 77.2090), (26.9124, 75.7873)
    coords = [[A[1] + (B[1] - A[1]) * t / 300, A[0] + (B[0] - A[0]) * t / 300] for t in range(301)]
    route = make_route(coords, 280.0, 300.0)
    assert abs(route.total_km - 280) < 1e-6 and route.pts[0] == (A[0], A[1]) and 0 < len(route.pts) < 600

    def charger(cid: str, frac: float, kw: float = 50, kind: str = "CCS2", op: Optional[bool] = True, off: float = 0.01) -> Charger:
        lat, lon = point_at(route, route.total_km * frac)
        return Charger(cid, f"Charger {cid}", "TestNet", lat + off, lon, {kind: kw}, op, "2026-06-01T00:00:00Z")

    depart = datetime(2026, 10, 23, 7, 0, tzinfo=IST)
    cfg = Config()
    chargers = [charger("c1", .20), charger("c2", .45), charger("c3", .70), charger("slow", .6, kw=7)]
    plan, _ = plan_trip(route, chargers, v, 0.9, depart, 25.0, cfg)
    assert plan.feasible and 1 <= len(plan.stops) <= 3, plan
    assert all(s.arrive_soc >= cfg.reserve - 1e-6 for s in plan.stops) and plan.arrive_soc >= cfg.reserve - 0.01
    assert check_plan(plan, v, cfg, 0.9) == [], check_plan(plan, v, cfg, 0.9)
    assert all(s.name != "Charger slow" for s in plan.stops)
    short, _ = plan_trip(make_route(coords[:60], 50.0, 55.0), chargers, v, 0.9, depart, 25.0, cfg)
    assert short.feasible and short.stops == []
    print(f"ok: planner found {len(plan.stops)} stop(s), total {fmt_dur(plan.total_min)}; short trip needs none")

    none_plan, _ = plan_trip(route, [], v, 0.9, depart, 25.0, cfg)
    assert not none_plan.feasible and "gap" in none_plan.reason
    wrong, _ = plan_trip(route, [charger("g", .3, kind="CHAdeMO")], v, 0.9, depart, 25.0, cfg)
    assert not wrong.feasible
    far, _ = plan_trip(route, [charger("far", .5, off=0.2)], v, 0.9, depart, 25.0, cfg)  # ~22 km off route
    assert not far.feasible
    print("ok: failures are reported with reasons (no chargers, wrong connector, charger too far from route)")

    # --- planner vs greedy baseline on random synthetic layouts ---------------
    rnd = random.Random(7)
    feas_p = feas_g = 0
    for _ in range(60):
        cs = [charger(f"r{k}", rnd.uniform(0.05, 0.95), kw=rnd.choice([30, 50, 60, 120]), op=rnd.choice([True, True, None]))
              for k in range(rnd.randint(1, 6))]
        veh, soc = rnd.choice(list(VEHICLES.values())), rnd.uniform(0.5, 1.0)
        p, planner = plan_trip(route, cs, veh, soc, depart, 25.0, cfg)
        gp = planner.greedy_path()
        feas_p += p.feasible
        feas_g += gp is not None
        if gp is not None:
            assert p.feasible, "planner must be feasible whenever the greedy baseline is"
            assert planner.path_cost(planner.dijkstra()) <= planner.path_cost(gp) + 1e-6
        if p.feasible:
            assert check_plan(p, veh, cfg, soc) == []
    assert feas_p >= feas_g
    print(f"ok: planner feasible in {feas_p}/60 synthetic cases vs greedy baseline {feas_g}/60 (synthetic, not for your resume)")

    # --- explanation number check ----------------------------------------------
    facts = plan_facts(plan, "Delhi", "Jaipur", v.name)
    assert numbers_ok(template_explanation(facts), facts)
    assert not numbers_ok("You will arrive with 99% after 12345 km.", facts)
    print("ok: explanation number check")

    # --- full graph with fake APIs and fake LLM --------------------------------
    scenario = {"chargers": "normal"}

    def fake_http(url: str, params: Optional[dict] = None, ttl: float = 0, min_interval: float = 0) -> Any:
        del ttl, min_interval
        if "nominatim" in url:
            return [{"lat": str(A[0] if "delhi" in params["q"].lower() else B[0]),
                     "lon": str(A[1] if "delhi" in params["q"].lower() else B[1]), "display_name": params["q"]}]
        if "/route/v1/" in url:
            return {"code": "Ok", "routes": [{"distance": 280000, "duration": 18000, "geometry": {"coordinates": coords}}]}
        if "open-meteo" in url:
            return {"hourly": {"time": ["2026-10-23T07:00"], "temperature_2m": [24.0]}}
        if "openchargemap" in url:
            if scenario["chargers"] == "none":
                return []
            return [{"ID": c.id, "AddressInfo": {"Title": c.name, "Latitude": c.lat, "Longitude": c.lon},
                     "OperatorInfo": {"Title": "TestNet"}, "StatusType": {"IsOperational": True},
                     "DateLastStatusUpdate": "2026-06-01T00:00:00Z",
                     "Connections": [{"ConnectionType": {"Title": "CCS (Type 2)"}, "PowerKW": 50}]}
                    for c in [charger("c1", .20), charger("c3", .70)]]
        raise AssertionError(url)

    def fake_parse(_text: str) -> TripRequest:
        del _text
        return TripRequest(origin="Delhi", destination="Jaipur", vehicle="Tata Nexon EV",
                           start_soc_percent=90, departure_time="2026-10-23T07:00:00+05:30")

    def fake_explanation(_facts: dict) -> str:
        del _facts
        return "You will arrive with 77% battery."

    def fake_parse_missing_vehicle(_text: str) -> TripRequest:
        del _text
        return TripRequest(origin="Delhi", destination="Jaipur")

    cache.http_get_json = fake_http
    language.parse_with_llm = fake_parse
    language.explain_with_llm = fake_explanation
    try:
        graph = build_graph()
        out = graph.invoke({"text": "Delhi to Jaipur in a Nexon EV, leaving 7am, start at 90%"})
        assert out["plan"].feasible and "Stop 1" in out["output"], out["output"]
        assert "77%" not in out["output"] and "Summary:" in out["output"]  # fake LLM text rejected, template used
        assert "<script>" in render_map(out) and "Charger" in render_map(out)
        scenario["chargers"] = "none"
        bad = graph.invoke({"text": "x"})
        assert not bad["plan"].feasible and "No feasible plan" in bad["output"]
        scenario["chargers"] = "normal"
        language.parse_with_llm = fake_parse_missing_vehicle
        ask = graph.invoke({"text": "take me to Jaipur"})
        assert "Which EV" in ask["clarification"]
        form = graph.invoke({"form": {"origin": "Delhi", "destination": "Jaipur", "vehicle": "MG ZS EV", "start_soc_percent": 85}})
        assert form["plan"].feasible
    finally:
        cache.http_get_json, language.parse_with_llm, language.explain_with_llm = real
    print("ok: full graph offline (LLM path, explanation rejection, no-charger failure, clarification, form path)")
    print("\nAll self-tests passed.")
