from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from typing import Any

from ..services import cache
from ..core.models import IST, Plan, TripRequest
from .planner import fmt_dur


DEFAULT_MODEL = "gemini-3.1-flash-lite"  # check Google's model page; override with GEMINI_MODEL


USAGE = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}


def budget_ok() -> bool:
    limit = int(os.getenv("DAILY_TOKEN_BUDGET", "100000"))
    if limit <= 0:
        return True
    used = cache.get_usage(date.today().isoformat())
    return used < limit


def track_usage(msg: Any) -> None:
    um = getattr(msg, "usage_metadata", None) or {}
    i, o = int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))
    USAGE["llm_calls"] += 1
    USAGE["input_tokens"] += i
    USAGE["output_tokens"] += o
    cache.record_usage(date.today().isoformat(), i + o)



def get_llm():
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs: dict = {"model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL), "google_api_key": key, "max_output_tokens": 1500}
    if os.getenv("GEMINI_TEMPERATURE"):
        kwargs["temperature"] = float(os.environ["GEMINI_TEMPERATURE"])
    return ChatGoogleGenerativeAI(**kwargs)


def text_of(msg: Any) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, str):
        return c
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in c
                   if isinstance(p, str) or (isinstance(p, dict) and p.get("type") == "text"))


def parse_with_llm(text: str) -> TripRequest:
    from langchain_core.messages import HumanMessage, SystemMessage

    ck = "parse:" + hashlib.sha256(text.strip().lower().encode()).hexdigest()
    hit = cache.cache_get(ck)
    if hit:
        return TripRequest(**hit)
    if not budget_ok():
        raise RuntimeError("Daily token budget reached. Use --from/--to/--vehicle flags instead.")
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M (%A) +05:30")
    system = ("Extract EV trip details from the user's message. Only fill fields the user actually stated; use null "
              "otherwise. Never guess a vehicle, a battery level or locations. Express departure_time as ISO 8601 "
              f"with +05:30 resolved against the current time: {now}.")
    out = get_llm().with_structured_output(TripRequest, include_raw=True).invoke(
        [SystemMessage(content=system), HumanMessage(content=text)])
    track_usage(out.get("raw"))
    if out.get("parsed") is None:
        raise ValueError(f"Could not parse the request: {out.get('parsing_error')}")
    cache.cache_set(ck, out["parsed"].model_dump(), 86400)
    return out["parsed"]


def plan_facts(plan: Plan, origin: str, dest: str, vehicle: str) -> dict:
    """Rounded, display-ready facts. The LLM may only use numbers that appear here."""
    return {
        "origin": origin, "destination": dest, "vehicle": vehicle, "distance_km": round(plan.total_km),
        "start_battery_percent": round(plan.start_soc * 100), "arrival_battery_percent": round(plan.arrive_soc * 100),
        "depart": plan.depart_time, "arrive": plan.arrive_time, "total_time": fmt_dur(plan.total_min),
        "driving_time": fmt_dur(plan.drive_min), "charging_time": fmt_dur(plan.charge_min),
        "stops": [{"stop": s.index, "name": s.name, "network": s.network, "km_from_start": round(s.pos_km),
                   "arrive_battery_percent": round(s.arrive_soc * 100), "leave_battery_percent": round(s.depart_soc * 100),
                   "charge_minutes": round(s.charge_min), "power_kw": round(s.power_kw), "detour_km": round(s.detour_km, 1),
                   "status": s.status} for s in plan.stops],
        "warnings": plan.warnings, "assumptions": {k: v for k, v in plan.assumptions.items() if k != "temperature_c"},
    }


def template_explanation(f: dict) -> str:
    lines = [f"Drive {f['origin']} to {f['destination']} in a {f['vehicle']}: {f['distance_km']} km, about "
             f"{f['total_time']} door to door ({f['driving_time']} driving, {f['charging_time']} charging). "
             f"You leave with {f['start_battery_percent']}% and arrive with about {f['arrival_battery_percent']}%."]
    if not f["stops"]:
        lines.append("No charging stop is needed.")
    for s in f["stops"]:
        lines.append(f"Stop {s['stop']}: {s['name']} ({s['network']}) at km {s['km_from_start']}. Arrive with "
                     f"{s['arrive_battery_percent']}%, charge about {s['charge_minutes']} min at up to {s['power_kw']} kW "
                     f"to {s['leave_battery_percent']}%.")
    return "\n".join(lines)


def numbers_ok(text: str, facts: dict) -> bool:
    allowed = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(facts))) | {str(i) for i in range(1, len(facts["stops"]) + 2)}
    return all(n in allowed for n in re.findall(r"\d+(?:\.\d+)?", text))


def explain_with_llm(facts: dict) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    ck = "explain:" + hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
    hit = cache.cache_get(ck)
    if hit:
        return hit
    if not budget_ok():
        raise RuntimeError("Daily token budget reached")
    system = ("You write a short, friendly EV trip briefing (90 to 150 words) from the JSON provided. Use ONLY the "
              "facts in the JSON. Copy every number exactly as given; do not round, convert or add numbers. Mention each "
              "stop with its name, and end with the most important warning if any. No markdown headings.")
    resp = get_llm().invoke([SystemMessage(content=system), HumanMessage(content=json.dumps(facts))])
    track_usage(resp)
    out = text_of(resp).strip()
    cache.cache_set(ck, out, 86400)
    return out
