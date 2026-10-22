from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .models import VEHICLES, Vehicle
from .rendering import render_map
from .selftest import selftest
from .workflow import build_graph, log


def main() -> None:
    ap = argparse.ArgumentParser(description="Plan an EV trip with charging stops.")
    ap.add_argument("text", nargs="?", help="Trip request in plain English")
    ap.add_argument("--from", dest="origin"), ap.add_argument("--to", dest="dest")
    ap.add_argument("--vehicle"), ap.add_argument("--soc", type=float, help="Start battery percent")
    ap.add_argument("--depart", help="ISO datetime or HH:MM (India time)")
    ap.add_argument("--reserve", type=float, help="Minimum battery percent on arrival (default 10)")
    ap.add_argument("--charge-to", type=float, help="Charge to this percent at stops (default 80)")
    ap.add_argument("--battery-kwh", type=float), ap.add_argument("--wh-per-km", type=float)
    ap.add_argument("--max-dc-kw", type=float)
    ap.add_argument("--map", help="Write a Leaflet map to this .html path")
    ap.add_argument("--json", help="Write the plan to this .json path")
    ap.add_argument("--list-vehicles", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if a.list_vehicles:
        for v in VEHICLES.values():
            print(f"{v.name}: {v.battery_kwh} kWh, {v.wh_per_km} Wh/km, {v.max_dc_kw} kW DC (approximate, verify)")
        return
    init: dict = {}
    if a.origin and a.dest:
        form = {"origin": a.origin, "destination": a.dest, "vehicle": a.vehicle, "start_soc_percent": a.soc,
                "departure_time": a.depart, "reserve_percent": a.reserve, "charge_to_percent": a.charge_to}
        if a.battery_kwh and a.wh_per_km and a.max_dc_kw:
            form["custom_vehicle"] = Vehicle(a.vehicle or "Custom EV", a.battery_kwh, a.wh_per_km, a.max_dc_kw)
        init["form"] = form
    elif a.text:
        init["text"] = a.text
    else:
        ap.error("give a trip request in quotes, or --from and --to")
    state = build_graph().invoke(init)
    print(state["output"])
    if a.map and state.get("plan") and state["plan"].feasible:
        with open(a.map, "w", encoding="utf-8") as f:
            f.write(render_map(state))
        log(f"Map written to {a.map}")
    if a.json and state.get("plan"):
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(asdict(state["plan"]), f, indent=2, default=str)
