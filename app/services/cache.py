from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests


_DB: Optional[sqlite3.Connection] = None
_LOCK = threading.RLock()
_LAST_CALL: dict = {}



def get_db() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        with _LOCK:
            if _DB is None:
                _DB = sqlite3.connect(os.getenv("EV_DB", ".ev_planner.db"), check_same_thread=False)
                _DB.executescript(
                    "CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT, exp REAL);"
                    "CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY, tokens INTEGER);"
                    "CREATE TABLE IF NOT EXISTS trips(id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, request TEXT, result TEXT);"
                )
    return _DB


def cache_get(key: str) -> Optional[Any]:
    with _LOCK:
        row = get_db().execute("SELECT v, exp FROM kv WHERE k=?", (key,)).fetchone()
    return json.loads(row[0]) if row and row[1] > time.time() else None


def cache_set(key: str, value: Any, ttl: float) -> None:
    with _LOCK:
        get_db().execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (key, json.dumps(value), time.time() + ttl))
        get_db().commit()


def clear_cache() -> None:
    with _LOCK:
        get_db().execute("DELETE FROM kv")
        get_db().commit()



def record_trip(created: str, request: Any, result: Any) -> None:
    with _LOCK:
        get_db().execute(
            "INSERT INTO trips(created, request, result) VALUES (?,?,?)",
            (created, json.dumps(request), json.dumps(result, default=str)),
        )
        get_db().commit()


def record_usage(day: str, tokens: int) -> None:
    with _LOCK:
        get_db().execute(
            "INSERT INTO usage VALUES (?,?) ON CONFLICT(day) DO UPDATE SET tokens = tokens + ?",
            (day, tokens, tokens),
        )
        get_db().commit()


def get_usage(day: str) -> int:
    with _LOCK:
        row = get_db().execute("SELECT tokens FROM usage WHERE day=?", (day,)).fetchone()
    return row[0] if row else 0


def http_get_json(url: str, params: Optional[dict] = None, ttl: float = 3600, min_interval: float = 0.2) -> Any:
    full = url + ("?" + urlencode(sorted((params or {}).items())) if params else "")
    ck = "http:" + hashlib.sha256(full.encode()).hexdigest()
    hit = cache_get(ck)
    if hit is not None:
        return hit
    ua = os.getenv("APP_USER_AGENT", "").strip()
    if "@" not in ua:
        raise RuntimeError("Set APP_USER_AGENT to e.g. 'ev-trip-planner you@example.com' (public map APIs want a contact).")
    host = url.split("/")[2]
    for attempt in range(3):
        wait = min_interval - (time.time() - _LAST_CALL.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[host] = time.time()
        try:
            r = requests.get(url, params=params, headers={"User-Agent": ua}, timeout=45)
        except requests.RequestException:
            time.sleep(2**attempt)
            continue
        if r.status_code == 200:
            data = r.json()
            cache_set(ck, data, ttl)
            return data
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** (attempt + 1))
            continue
        raise RuntimeError(f"HTTP {r.status_code} from {host}: {r.text[:200]}")
    raise RuntimeError(f"Could not reach {host}")
