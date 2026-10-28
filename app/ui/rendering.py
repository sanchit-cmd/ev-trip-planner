from __future__ import annotations

import html as html_lib
import json

from ..core.models import Plan, Route
from ..engine.planner import fmt_dur


def render_text(s: dict) -> str:
    if s.get("clarification"):
        return s["clarification"]
    plan: Plan = s["plan"]
    head = f"=== EV trip: {s['origin_name']} -> {s['dest_name']} | {s['vehicle'].name} ==="
    if not plan.feasible:
        return f"{head}\n{plan.reason}"
    a = plan.assumptions
    out = [head,
           f"{plan.total_km:.0f} km | depart {plan.depart_time} | arrive {plan.arrive_time} | total {fmt_dur(plan.total_min)} "
           f"(driving {fmt_dur(plan.drive_min)}, charging {fmt_dur(plan.charge_min)}, detours {fmt_dur(plan.detour_min)})",
           f"Battery: {plan.start_soc * 100:.0f}% at start -> {plan.arrive_soc * 100:.0f}% on arrival",
           f"Assumptions: {a['wh_per_km']} Wh/km at {a['avg_speed_kmh']} km/h average, reserve {a['reserve_soc'] * 100:.0f}%, "
           f"charge to {a['charge_to_soc'] * 100:.0f}%, temperature "
           f"{'n/a' if a['temperature_c'] is None else str(round(a['temperature_c'])) + ' C'}", ""]
    if not plan.stops:
        out.append("No charging stop needed.")
    for st in plan.stops:
        out.append(f"Stop {st.index}: {st.name} ({st.network}) at km {st.pos_km:.0f}, detour {st.detour_km:.1f} km")
        out.append(f"   arrive {st.arrive_time} with {st.arrive_soc * 100:.0f}% -> charge {st.charge_min:.0f} min at up to "
                   f"{st.power_kw:.0f} kW -> leave {st.depart_time} with {st.depart_soc * 100:.0f}%  [{st.status}]")
        if st.backup:
            out.append(f"   backup: {st.backup['name']} ({st.backup['network']}) at km {st.backup['pos_km']:.0f}, "
                       f"{st.backup['power_kw']:.0f} kW")
    if s.get("explanation"):
        out += ["", "Summary:", s["explanation"]]
    if plan.warnings:
        out += ["", "Warnings:"] + [f"- {w}" for w in plan.warnings]
    out += ["", "Charger data: Open Charge Map (check the licence/attribution terms). Routing: OSRM / OpenStreetMap."]
    return "\n".join(out)


def render_map(s: dict) -> str:
    route: Route = s["route"]
    step = max(1, len(route.pts) // 1500)
    data = {"route": [[round(a, 5), round(b, 5)] for a, b in route.pts[::step]], "start": s["o_geo"][:2], "end": s["d_geo"][:2],
            "stops": [{"i": st.index, "name": st.name, "lat": st.lat, "lon": st.lon,
                       "info": f"arrive {st.arrive_soc * 100:.0f}% / leave {st.depart_soc * 100:.0f}% / {st.charge_min:.0f} min"}
                      for st in s["plan"].stops]}
    blob = json.dumps(data).replace("</", "<\\/")
    title = html_lib.escape(f"{s['origin_name']} to {s['dest_name']}")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>EV trip: {title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{{height:100%;margin:0}}</style></head><body><div id="m"></div><script>
const d={blob};const m=L.map('m');
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap contributors | chargers: Open Charge Map'}}).addTo(m);
const line=L.polyline(d.route,{{color:'#1565c0',weight:5}}).addTo(m);m.fitBounds(line.getBounds());
L.marker(d.start).addTo(m).bindPopup('Start');L.marker(d.end).addTo(m).bindPopup('Destination');
d.stops.forEach(s=>L.circleMarker([s.lat,s.lon],{{radius:9,color:'#2e7d32',fillOpacity:.9}}).addTo(m).bindPopup('<b>Stop '+s.i+': '+s.name+'</b><br>'+s.info));
</script></body></html>"""
