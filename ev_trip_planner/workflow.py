from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from . import cache, language, planner, rendering, routing
from .language import USAGE, plan_facts, template_explanation, numbers_ok
from .models import Config, IST, Plan, Route, Vehicle, VEHICLES, match_vehicle
from .planner import Planner


class State(TypedDict, total=False):
    text: str
    form: dict
    req: dict
    vehicle: Vehicle
    cfg: Config
    start_soc: float
    depart: datetime
    origin_name: str
    dest_name: str
    o_geo: tuple
    d_geo: tuple
    route: Route
    temp_c: Optional[float]
    chargers: list
    plan: Plan
    planner: Planner
    explanation: str
    clarification: str
    output: str


def log(msg: str) -> None:
    print(f"[agent] {msg}", file=sys.stderr)


def parse_departure(s: Optional[str]) -> datetime:
    now = datetime.now(IST)
    if not s:
        return now
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except ValueError:
        pass
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", s)
    if m:
        d = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        return d if d > now else d + timedelta(days=1)
    return now


def n_parse(s: State) -> dict:
    if s.get("form"):
        req = s["form"]
    else:
        log("Parsing the request with Gemini")
        try:
            req = language.parse_with_llm(s["text"]).model_dump()
        except Exception as exc:  # noqa: BLE001
            return {"clarification": f"I could not parse that request ({exc}). Try the flags: "
                                     "--from CITY --to CITY --vehicle NAME --soc 90"}
    missing = [k for k in ("origin", "destination") if not req.get(k)]
    if missing:
        return {"clarification": f"Please tell me your {' and '.join(missing)}."}
    custom = req.get("custom_vehicle")
    vehicle = custom or match_vehicle(req.get("vehicle"))
    if vehicle is None:
        return {"clarification": "Which EV are you driving? Known models: " + ", ".join(VEHICLES) +
                ". For another car pass --battery-kwh, --wh-per-km and --max-dc-kw."}
    cfg = Config()
    if req.get("reserve_percent") is not None:
        cfg.reserve = min(max(req["reserve_percent"], 5), 40) / 100
    if req.get("charge_to_percent") is not None:
        cfg.target = min(max(req["charge_to_percent"], 50), 100) / 100
    soc = req.get("start_soc_percent")
    return {"req": req, "vehicle": vehicle, "cfg": cfg, "start_soc": (90.0 if soc is None else min(max(soc, 0), 100)) / 100,
            "depart": parse_departure(req.get("departure_time"))}


def n_geocode(s: State) -> dict:
    log("Geocoding")
    o, d = routing.geocode(s["req"]["origin"]), routing.geocode(s["req"]["destination"])
    for name, g in (("origin", o), ("destination", d)):
        if g is None:
            return {"clarification": f"I could not find your {name} ({s['req'][name]}). Try a more specific place name."}
    return {"o_geo": o, "d_geo": d, "origin_name": s["req"]["origin"], "dest_name": s["req"]["destination"]}


def n_route(s: State) -> dict:
    log("Routing")
    return {"route": routing.osrm_route(s["o_geo"][:2], s["d_geo"][:2])}


def n_weather(s: State) -> dict:
    log("Fetching weather")
    mid = routing.point_at(s["route"], s["route"].total_km / 2)
    return {"temp_c": routing.temperature_at(mid[0], mid[1], s["depart"])}


def n_chargers(s: State) -> dict:
    log("Fetching chargers along the route")
    return {"chargers": routing.fetch_chargers(s["route"])}


def n_plan(s: State) -> dict:
    log("Planning charging stops")
    plan, pl = planner.plan_trip(s["route"], s["chargers"], s["vehicle"], s["start_soc"], s["depart"], s.get("temp_c"), s["cfg"])
    return {"plan": plan, "planner": pl}


def n_verify(s: State) -> dict:
    problems = planner.check_plan(s["plan"], s["vehicle"], s["cfg"], s["start_soc"])
    if problems:
        log(f"Plan failed verification: {problems}")
        return {"plan": Plan(False, "Internal check failed, so the plan was withheld: " + "; ".join(problems))}
    return {}


def n_explain(s: State) -> dict:
    facts = plan_facts(s["plan"], s["origin_name"], s["dest_name"], s["vehicle"].name)
    base = template_explanation(facts)
    if os.getenv("EV_NO_LLM") or s.get("form") is not None and os.getenv("EV_FORM_NO_LLM", "1") == "1":
        return {"explanation": base}
    try:
        log("Writing the explanation with Gemini")
        text = language.explain_with_llm(facts)
        return {"explanation": text if numbers_ok(text, facts) else base}
    except Exception as exc:  # noqa: BLE001  (no key, budget reached, API error: fall back to the template)
        log(f"Using the template explanation ({type(exc).__name__}: {exc})")
        return {"explanation": base}


def n_finalize(s: State) -> dict:
    out = rendering.render_text(s)
    if s.get("plan") and not s.get("clarification"):
        cache.get_db().execute("INSERT INTO trips(created, request, result) VALUES (?,?,?)",
                         (datetime.now(IST).isoformat(), json.dumps(s.get("req")), json.dumps(asdict(s["plan"]), default=str)))
        cache.get_db().commit()
    if USAGE["llm_calls"]:
        out += f"\n(LLM usage: {USAGE['llm_calls']} call(s), {USAGE['input_tokens']} in / {USAGE['output_tokens']} out tokens)"
    return {"output": out}


def build_graph():
    g = StateGraph(State)
    for name, fn in [("parse", n_parse), ("geocode", n_geocode), ("route", n_route), ("weather", n_weather),
                     ("chargers", n_chargers), ("plan", n_plan), ("verify", n_verify), ("explain", n_explain),
                     ("finalize", n_finalize)]:
        g.add_node(name, fn)
    g.set_entry_point("parse")
    halt = lambda nxt: (lambda s: "finalize" if s.get("clarification") else nxt)  # noqa: E731
    g.add_conditional_edges("parse", halt("geocode"), {"geocode": "geocode", "finalize": "finalize"})
    g.add_conditional_edges("geocode", halt("route"), {"route": "route", "finalize": "finalize"})
    g.add_edge("route", "weather")
    g.add_edge("weather", "chargers")
    g.add_edge("chargers", "plan")
    g.add_edge("plan", "verify")
    g.add_conditional_edges("verify", lambda s: "explain" if s["plan"].feasible else "finalize",
                            {"explain": "explain", "finalize": "finalize"})
    g.add_edge("explain", "finalize")
    g.add_edge("finalize", END)
    return g.compile()
