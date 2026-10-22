"""
EV Trip Planner (single file)
=============================
Natural-language EV trip request -> feasible multi-stop charging plan + friendly explanation.

Pipeline (LangGraph):
  parse (Gemini) -> geocode -> route -> weather -> chargers -> plan -> verify -> explain (Gemini) -> finalize

Design rules (cost and trust):
  * The charging plan is computed by deterministic Python (Dijkstra over charger nodes), never by the LLM.
  * Gemini is used for at most 2 calls per trip: parsing the request and explaining the finished plan.
    The explanation is number-checked against the plan; if it fails, a template explanation is used.
  * Every external API response is cached in SQLite, and LLM tokens are counted against a daily budget.
  * `--from/--to/--vehicle` flags skip the LLM entirely (works with no API key or when the budget is gone).

Free data sources (no card needed; read each one's usage terms):
  Nominatim (geocoding), OSRM public demo server (routing), Open-Meteo (weather),
  Open Charge Map (chargers; free API key required).

Setup:
  pip install requests pydantic langgraph langchain-google-genai
  export GEMINI_API_KEY="..."                               # Google AI Studio
  export OCM_API_KEY="..."                                  # openchargemap.org (free)
  export APP_USER_AGENT="ev-trip-planner you@example.com"   # Nominatim/OSRM want an identifying contact

Examples:
  python ev_trip_planner.py "Delhi to Jaipur in a Tata Nexon EV, leaving 7am tomorrow, start at 90%"
  python ev_trip_planner.py --from Delhi --to Agra --vehicle "MG ZS EV" --soc 85 --map trip.html
  python ev_trip_planner.py --list-vehicles
  python ev_trip_planner.py --selftest                      # offline tests, no network or keys

Optional env vars: GEMINI_MODEL, GEMINI_TEMPERATURE, DAILY_TOKEN_BUDGET (default 100000, 0 = off),
  OSRM_URL, OCM_COUNTRY (default IN), GEOCODE_COUNTRY (default in), EV_DB (default .ev_planner.db).

Limits to be honest about: energy use is a documented heuristic (no elevation data), charger data in
India is incomplete or stale in places, detours are estimated from straight-line distance, and queueing
at chargers is not modelled. Treat plans as decision support, not a guarantee.
"""
