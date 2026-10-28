from __future__ import annotations

import heapq
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..core.models import Charger, Config, Plan, Route, Stop, Vehicle, IST
from ..services.routing import project


def consumption_wh_per_km(v: Vehicle, avg_kmh: float, temp_c: Optional[float]) -> float:
    speed = min(1.35, max(0.85, 1 + 0.008 * (avg_kmh - 70)))
    t = 22.0 if temp_c is None else temp_c
    temp = 1 + 0.01 * min(30.0, max(0.0, 15 - t)) + 0.01 * min(15.0, max(0.0, t - 28))
    return v.wh_per_km * speed * temp


def taper(s: float) -> float:
    if s <= 0.5:
        return 1.0
    if s <= 0.8:
        return 1.0 - (s - 0.5) / 0.3 * 0.4
    return max(0.6 - (s - 0.8) / 0.2 * 0.45, 0.15)


def charge_minutes(cap_kwh: float, soc_from: float, soc_to: float, power_kw: float) -> float:
    if soc_to <= soc_from:
        return 0.0
    minutes, s = 0.0, soc_from
    while s < soc_to - 1e-9:
        ds = min(0.01, soc_to - s)
        minutes += cap_kwh * ds / max(power_kw * taper(s + ds / 2), 3.0) * 60
        s += ds
    return minutes


def vehicle_power(c: Charger, v: Vehicle) -> float:
    ps = [kw for kind, kw in c.connectors.items() if kind in v.connectors]
    return min(max(ps), v.max_dc_kw) if ps else 0.0


def prepare_candidates(route: Route, chargers: list, v: Vehicle, cfg: Config) -> list:
    cands = []
    for c in chargers:
        kw = vehicle_power(c, v)
        if kw < cfg.min_kw or c.operational is False:
            continue
        pos, off = project(route, c.lat, c.lon)
        if off <= cfg.corridor_km:
            cands.append(replace(c, pos_km=pos, off_km=off, eff_kw=kw))
    buckets: dict = {}
    for c in sorted(cands, key=lambda c: (-c.eff_kw, c.off_km)):
        b = buckets.setdefault(int(c.pos_km // 5), [])
        if len(b) < 2:
            b.append(c)
    flat = sorted((c for b in buckets.values() for c in b), key=lambda c: c.pos_km)
    if len(flat) > cfg.max_candidates:
        flat = sorted(sorted(flat, key=lambda c: -c.eff_kw)[:cfg.max_candidates], key=lambda c: c.pos_km)
    return flat


def fmt_dur(mins: float) -> str:
    m = int(round(mins))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def fmt_time(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %H:%M")


class Planner:
    def __init__(self, route: Route, cands: list, v: Vehicle, start_soc: float, depart: datetime,
                 temp_c: Optional[float], cfg: Config):
        self.route, self.v, self.cfg, self.depart, self.temp_c = route, v, cfg, depart, temp_c
        self.start_soc = start_soc
        self.cap = v.usable_kwh
        self.whkm = consumption_wh_per_km(v, route.avg_kmh, temp_c)
        self.nodes = ([(0.0, 0.0, None)] + [(c.pos_km, c.off_km * cfg.road_factor, c) for c in cands]
                      + [(route.total_km, 0.0, None)])
        self.n = len(self.nodes) - 1  # destination index

    def dep_soc(self, i: int) -> float:
        return self.start_soc if i == 0 else self.cfg.target

    def leg(self, i: int, j: int) -> tuple:
        rk = self.nodes[j][0] - self.nodes[i][0]
        off = self.nodes[i][1] + self.nodes[j][1]
        energy = (rk + off) * self.whkm / 1000.0
        minutes = rk / self.route.avg_kmh * 60 + off / self.cfg.off_route_kmh * 60
        return rk, off, energy, minutes

    def penalty(self, c: Charger) -> float:
        p = 0.0
        if c.operational is None:
            p += self.cfg.unknown_status_penalty
        if self.is_stale(c):
            p += self.cfg.stale_penalty
        return p

    def is_stale(self, c: Charger) -> bool:
        if not c.updated:
            return True
        try:
            d = datetime.fromisoformat(c.updated.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - d).days > self.cfg.stale_days
        except ValueError:
            return True

    def edge(self, i: int, j: int) -> Optional[tuple]:
        """(cost_min, arrival_soc) or None if the leg is not drivable above the reserve."""
        _, _, energy, minutes = self.leg(i, j)
        arr = self.dep_soc(i) - energy / self.cap
        if arr < self.cfg.reserve:
            return None
        cost = minutes
        c = self.nodes[j][2]
        if c is not None:
            cost += (charge_minutes(self.cap, arr, self.cfg.target, c.eff_kw * self.cfg.charger_eff)
                     + self.cfg.stop_overhead_min + self.penalty(c))
        return cost, arr

    def dijkstra(self) -> Optional[list]:
        dist = {0: 0.0}
        prev: dict = {}
        heap = [(0.0, 0)]
        while heap:
            d, i = heapq.heappop(heap)
            if d > dist.get(i, 1e18):
                continue
            if i == self.n:
                break
            for j in range(i + 1, self.n + 1):
                e = self.edge(i, j)
                if e is None:
                    if self.nodes[j][0] - self.nodes[i][0] > 0:
                        break  # energy only grows with distance
                    continue
                nd = d + e[0]
                if nd < dist.get(j, 1e18):
                    dist[j], prev[j] = nd, i
                    heapq.heappush(heap, (nd, j))
        if self.n not in prev and self.n != 0:
            return None
        path, k = [self.n], self.n
        while k != 0:
            k = prev[k]
            path.append(k)
        return path[::-1]

    def greedy_path(self) -> Optional[list]:
        """Baseline: drive until SoC would hit 30%, then stop at the charger nearest to that point."""
        path, i = [0], 0
        while i != self.n:
            if self.edge(i, self.n) is not None:
                path.append(self.n)
                return path
            km_to_30 = max(0.0, (self.dep_soc(i) - 0.30) * self.cap * 1000 / self.whkm)
            target_pos = self.nodes[i][0] + km_to_30
            opts = [j for j in range(i + 1, self.n) if self.edge(i, j) is not None]
            if not opts:
                return None
            j = min(opts, key=lambda k: abs(self.nodes[k][0] - target_pos))
            path.append(j)
            i = j
        return path

    def path_cost(self, path: list) -> Optional[float]:
        total = 0.0
        for a, b in zip(path, path[1:]):
            e = self.edge(a, b)
            if e is None:
                return None
            total += e[0]
        return total

    def diagnose(self) -> str:
        reach, frontier = {0}, [0]
        while frontier:
            i = frontier.pop()
            for j in range(i + 1, self.n + 1):
                if j not in reach and self.edge(i, j) is not None:
                    reach.add(j)
                    frontier.append(j)
        far = max(reach, key=lambda k: self.nodes[k][0])
        pos = self.nodes[far][0]
        nxt = next((self.nodes[k][0] for k in range(far + 1, self.n + 1)), self.route.total_km)
        usable_km = (self.cfg.target - self.cfg.reserve) * self.cap * 1000 / self.whkm
        return (f"No feasible plan: the furthest point reachable with compatible chargers is about km {pos:.0f}, and the "
                f"next compatible charger (or the destination) is at km {nxt:.0f}, a gap of {nxt - pos:.0f} km. "
                f"At this consumption the car covers roughly {usable_km:.0f} km between charges (80% to reserve).")

    def build(self, path: list) -> Plan:
        cfg, cap = self.cfg, self.cap
        clock, soc = self.depart, self.start_soc
        stops: list = []
        drive = charge = detour = 0.0
        prev = 0
        for idx, j in enumerate(path[1:], 1):
            rk, off, energy, minutes = self.leg(prev, j)
            soc -= energy / cap
            drive += rk / self.route.avg_kmh * 60
            detour += off / cfg.off_route_kmh * 60
            clock += timedelta(minutes=minutes)
            c = self.nodes[j][2]
            if c is not None:
                arrive_soc, arrive_clock = soc, clock
                dep_target = cfg.target
                if path[idx + 1] == self.n:  # last stop: charge only what the final leg needs
                    need = cfg.reserve + self.leg(j, self.n)[2] / cap + cfg.final_buffer
                    dep_target = min(cfg.target, max(arrive_soc, need))
                cm = charge_minutes(cap, arrive_soc, dep_target, c.eff_kw * cfg.charger_eff) + cfg.stop_overhead_min
                clock += timedelta(minutes=cm)
                charge += cm
                soc = max(arrive_soc, dep_target)
                status = ("operational" if c.operational else "status unknown") + (", data may be stale" if self.is_stale(c) else "")
                stops.append(Stop(len(stops) + 1, c.name, c.network, c.lat, c.lon, round(self.nodes[j][0], 1),
                                  round(2 * self.nodes[j][1], 1), c.eff_kw, round(arrive_soc, 3), round(soc, 3),
                                  round(cm, 1), fmt_time(arrive_clock), fmt_time(clock), status))
            prev = j
        total = drive + charge + detour
        plan = Plan(True, "", round(self.route.total_km, 1), round(drive, 1), round(charge, 1), round(detour, 1),
                    round(total, 1), self.start_soc, round(soc, 3), fmt_time(self.depart), fmt_time(clock), stops,
                    {"wh_per_km": round(self.whkm, 1), "avg_speed_kmh": round(self.route.avg_kmh, 1),
                     "temperature_c": self.temp_c, "reserve_soc": cfg.reserve, "charge_to_soc": cfg.target,
                     "usable_kwh": round(cap, 1)})
        self.add_backups(plan, path)
        self.add_warnings(plan)
        return plan

    def add_backups(self, plan: Plan, path: list) -> None:
        cand_idx = [k for k in range(1, self.n)]
        for s, j in zip(plan.stops, path[1:-1]):
            prev = path[path.index(j) - 1]
            alts = [k for k in cand_idx if k != j and abs(self.nodes[k][0] - self.nodes[j][0]) <= 20
                    and self.edge(prev, k) is not None]
            if alts:
                k = max(alts, key=lambda a: (self.nodes[a][2].eff_kw, -abs(self.nodes[a][0] - self.nodes[j][0])))
                c = self.nodes[k][2]
                s.backup = {"name": c.name, "network": c.network, "pos_km": round(self.nodes[k][0], 1),
                            "power_kw": c.eff_kw}

    def add_warnings(self, plan: Plan) -> None:
        for s in plan.stops:
            if s.arrive_soc < self.cfg.reserve + 0.05:
                plan.warnings.append(f"Stop {s.index} ({s.name}) is a tight arrival at {s.arrive_soc * 100:.0f}% battery.")
            if "stale" in s.status or "unknown" in s.status:
                plan.warnings.append(f"Stop {s.index} ({s.name}): charger status is {s.status}. Check the app before relying on it.")
            if s.backup is None:
                plan.warnings.append(f"Stop {s.index} ({s.name}) has no backup charger within 20 km along the route.")
        if self.temp_c is None:
            plan.warnings.append("Weather data unavailable; a mild temperature was assumed.")


def plan_trip(route: Route, chargers: list, v: Vehicle, start_soc: float, depart: datetime,
              temp_c: Optional[float], cfg: Config) -> tuple:
    """Returns (Plan, Planner). The Planner is returned so callers can run baselines and checks."""
    cands = prepare_candidates(route, chargers, v, cfg)
    pl = Planner(route, cands, v, start_soc, depart, temp_c, cfg)
    if start_soc < cfg.reserve:
        return Plan(False, "Starting battery is already below the reserve."), pl
    path = pl.dijkstra()
    if path is None:
        return Plan(False, pl.diagnose(), total_km=round(route.total_km, 1), start_soc=start_soc), pl
    return pl.build(path), pl


def check_plan(plan: Plan, v: Vehicle, cfg: Config, start_soc: float) -> list:
    """Independent sanity check of a finished plan (does not reuse the Dijkstra code path)."""
    if not plan.feasible:
        return []
    problems, soc, last_pos = [], start_soc, 0.0
    cap, whkm = v.usable_kwh, plan.assumptions["wh_per_km"]
    for s in plan.stops:
        if s.pos_km < last_pos:
            problems.append(f"Stop {s.index} is out of order along the route.")
        soc -= ((s.pos_km - last_pos) + s.detour_km / 2) * whkm / 1000 / cap
        if abs(soc - s.arrive_soc) > 0.02:
            problems.append(f"Stop {s.index}: recorded arrival {s.arrive_soc:.2f} vs recomputed {soc:.2f}.")
        if soc < cfg.reserve - 0.005:
            problems.append(f"Stop {s.index}: battery {soc:.2f} falls below the reserve.")
        if s.depart_soc > 1.0 or s.depart_soc < s.arrive_soc - 1e-9:
            problems.append(f"Stop {s.index}: invalid departure SoC.")
        soc, last_pos = s.depart_soc, s.pos_km + 0.0
        soc -= (s.detour_km / 2) * whkm / 1000 / cap
    soc -= (plan.total_km - last_pos) * whkm / 1000 / cap
    if soc < cfg.reserve - 0.01:
        problems.append(f"Arrival battery {soc:.2f} is below the reserve.")
    return problems
