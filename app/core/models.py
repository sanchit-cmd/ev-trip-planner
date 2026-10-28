from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field


IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class Vehicle:
    name: str
    battery_kwh: float
    wh_per_km: float
    max_dc_kw: float
    connectors: tuple = ("CCS2",)
    usable_frac: float = 0.95

    @property
    def usable_kwh(self) -> float:
        return self.battery_kwh * self.usable_frac


VEHICLES = {v.name: v for v in [
    Vehicle("Tata Tiago EV", 24.0, 125, 25),
    Vehicle("Tata Punch EV", 35.0, 145, 50),
    Vehicle("Tata Nexon EV", 40.5, 155, 50),
    Vehicle("Mahindra XUV400", 39.4, 160, 50),
    Vehicle("MG Windsor EV", 38.0, 150, 45),
    Vehicle("MG ZS EV", 50.3, 170, 76),
    Vehicle("Hyundai Creta Electric", 51.4, 160, 100),
    Vehicle("BYD Atto 3", 60.5, 175, 88),
]}


def match_vehicle(name: Optional[str]) -> Optional[Vehicle]:
    if not name:
        return None
    key = name.strip().lower()
    for n, v in VEHICLES.items():
        if key == n.lower() or key in n.lower() or n.lower() in key:
            return v
    close = difflib.get_close_matches(key, [n.lower() for n in VEHICLES], n=1, cutoff=0.6)
    return next((v for n, v in VEHICLES.items() if close and n.lower() == close[0]), None)


@dataclass
class Config:
    reserve: float = 0.10            # never plan to arrive anywhere below this SoC
    target: float = 0.80             # charge to this SoC at intermediate stops
    min_kw: float = 25.0             # ignore slow chargers
    corridor_km: float = 5.0         # max straight-line distance from the route to a charger
    road_factor: float = 1.4         # straight-line -> road distance for detours
    off_route_kmh: float = 30.0      # speed for the off-route part of a detour
    stop_overhead_min: float = 5.0   # plugging in, payment, etc.
    charger_eff: float = 0.90        # real-world charging efficiency
    unknown_status_penalty: float = 15.0  # minutes of "cost" for chargers with unknown status
    stale_penalty: float = 10.0
    stale_days: int = 548            # about 18 months
    max_candidates: int = 200
    final_buffer: float = 0.03       # extra SoC kept when trimming the last charge


@dataclass
class Charger:
    id: str
    name: str
    network: str
    lat: float
    lon: float
    connectors: dict            # kind -> max kW, e.g. {"CCS2": 60.0}
    operational: Optional[bool]
    updated: Optional[str]
    pos_km: float = 0.0
    off_km: float = 0.0
    eff_kw: float = 0.0


@dataclass
class Route:
    pts: list        # [(lat, lon)], resampled
    cum: list        # km along the route at each point
    total_km: float
    duration_min: float

    @property
    def avg_kmh(self) -> float:
        return self.total_km / (self.duration_min / 60.0) if self.duration_min > 0 else 60.0


@dataclass
class Stop:
    index: int
    name: str
    network: str
    lat: float
    lon: float
    pos_km: float
    detour_km: float
    power_kw: float
    arrive_soc: float
    depart_soc: float
    charge_min: float
    arrive_time: str
    depart_time: str
    status: str
    backup: Optional[dict] = None


@dataclass
class Plan:
    feasible: bool
    reason: str = ""
    total_km: float = 0.0
    drive_min: float = 0.0
    charge_min: float = 0.0
    detour_min: float = 0.0
    total_min: float = 0.0
    start_soc: float = 0.0
    arrive_soc: float = 0.0
    depart_time: str = ""
    arrive_time: str = ""
    stops: list = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class TripRequest(BaseModel):
    origin: Optional[str] = Field(None, description="Starting place, as written by the user")
    destination: Optional[str] = Field(None, description="Destination place, as written by the user")
    vehicle: Optional[str] = Field(None, description="EV model name, e.g. 'Tata Nexon EV'")
    start_soc_percent: Optional[float] = Field(None, description="Battery percent at departure, 0-100")
    departure_time: Optional[str] = Field(None, description="ISO 8601 local India time (+05:30) if stated, else null")
    reserve_percent: Optional[float] = Field(None, description="Minimum battery % the user wants on arrival, if stated")
    charge_to_percent: Optional[float] = Field(None, description="Max battery % to charge to at stops, if stated")
