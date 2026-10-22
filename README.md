# EV Trip Planner

EV Trip Planner turns a trip request into a route and a practical charging-stop
plan. It can accept a natural-language request or explicit command-line options.
It estimates energy use, looks for compatible chargers along the route, checks
the resulting plan, and prints an itinerary. It can also save a map and a JSON
copy of the plan.

> **Planning aid, not a guarantee.** Vehicle energy figures are approximate,
> public charger information can be incomplete or out of date, and the planner
> does not model elevation or charger queues. Check the route, charger status,
> and vehicle specifications before travelling.

## Features

- Parses natural-language trip requests with Gemini, or accepts explicit
  origin, destination, vehicle, battery level, and timing options.
- Uses a deterministic charging planner; the language model does not choose
  charging stops.
- Retrieves road routes, weather, and nearby charging stations from public
  data services.
- Caches external responses locally in SQLite and tracks Gemini token usage
  against a configurable daily budget.
- Produces a text itinerary and optional Leaflet map and JSON output.
- Includes an offline self-test that does not require API keys or network
  access.

## Requirements

- Python 3.12 or newer
- An Open Charge Map API key for trip planning
- An identifying contact in `APP_USER_AGENT` for the public map services
- A Gemini API key only when using natural-language trip requests or
  Gemini-generated explanations; explicit trip flags work without Gemini

## Installation

From the project directory, create and activate a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install the project dependencies:

```bash
python -m pip install requests pydantic langgraph langchain-google-genai
```

Alternatively, if you use `uv`, sync the dependencies from the project lock
file:

```bash
uv sync
```

Set the required environment variables. Replace the example contact with your
own identifying email address:

```bash
export OCM_API_KEY="your-open-charge-map-api-key"
export APP_USER_AGENT="ev-trip-planner you@example.com"
```

For natural-language requests, also set a Gemini key:

```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

`GOOGLE_API_KEY` is also accepted by the application. API keys should be kept
private and should not be committed to the repository.

## Usage

Run commands from the project root. The existing script remains available, and
the application can also be launched as a Python package.

### Plan a trip with natural language

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), as well as the Open Charge Map
and user-agent configuration:

```bash
python ev_trip_planner.py "Delhi to Jaipur in a Tata Nexon EV, leaving 7am tomorrow, start at 90%"
```

### Plan a trip with explicit options

This mode skips Gemini:

```bash
python ev_trip_planner.py \
  --from Delhi \
  --to Agra \
  --vehicle "MG ZS EV" \
  --soc 85 \
  --map trip.html \
  --json trip.json
```

Open `trip.html` in a browser to view the route map. The map uses Leaflet and
OpenStreetMap tiles, so an internet connection is needed to load its map assets.

The package entry point supports the same options:

```bash
python -m ev_trip_planner --from Delhi --to Agra --vehicle "MG ZS EV" --soc 85
```

### Other commands

List the built-in vehicle estimates:

```bash
python ev_trip_planner.py --list-vehicles
```

Run the offline self-test:

```bash
python ev_trip_planner.py --selftest
```

The self-test also works through the package entry point:

```bash
python -m ev_trip_planner --selftest
```

## Command-line options

| Option | Description |
| --- | --- |
| `text` | Optional trip request in plain language. |
| `--from CITY` | Trip origin. Use together with `--to`. |
| `--to CITY` | Trip destination. Use together with `--from`. |
| `--vehicle NAME` | Built-in EV model name, for example `"MG ZS EV"`. |
| `--soc PERCENT` | Starting battery percentage. Defaults to 90% when omitted. |
| `--depart TIME` | Departure time as `HH:MM` or an ISO datetime. Times without a timezone are treated as India time. |
| `--reserve PERCENT` | Minimum battery percentage to keep on arrival. Defaults to 10%. |
| `--charge-to PERCENT` | Target charge percentage at intermediate stops. Defaults to 80%. |
| `--battery-kwh KWH` | Battery capacity for a custom vehicle. |
| `--wh-per-km VALUE` | Estimated energy use for a custom vehicle. |
| `--max-dc-kw KW` | Maximum DC charging power for a custom vehicle. |
| `--map PATH` | Write an HTML Leaflet map when a feasible plan is found. |
| `--json PATH` | Write the plan as JSON. |
| `--list-vehicles` | Print the built-in vehicle estimates and exit. |
| `--selftest` | Run the offline self-test and exit. |

For a custom vehicle, provide all three vehicle specifications:

```bash
python ev_trip_planner.py \
  --from Delhi --to Agra \
  --vehicle "My EV" \
  --battery-kwh 60 \
  --wh-per-km 180 \
  --max-dc-kw 100
```

The built-in vehicle specifications are estimates; verify them against the
vehicle manufacturer's information before relying on a plan.

## Configuration

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `OCM_API_KEY` | Open Charge Map API key. Required to retrieve chargers. | None |
| `APP_USER_AGENT` | Identifying user-agent/contact for public map APIs. Required for uncached HTTP requests. | None |
| `GEMINI_API_KEY` | Google AI Studio key for Gemini. | None |
| `GOOGLE_API_KEY` | Alternate Gemini key variable. | None |
| `GEMINI_MODEL` | Gemini model name. | `gemini-3.1-flash-lite` |
| `GEMINI_TEMPERATURE` | Optional Gemini temperature. | Provider default |
| `DAILY_TOKEN_BUDGET` | Daily Gemini token limit; set to `0` to disable the limit. | `100000` |
| `EV_NO_LLM` | Use the template explanation instead of calling Gemini. | Unset |
| `EV_FORM_NO_LLM` | Use template explanations for explicit-form requests. | `1` |
| `EV_DB` | SQLite database path for cache and trip records. | `.ev_planner.db` |
| `OSRM_URL` | OSRM routing server base URL. | `https://router.project-osrm.org` |
| `OCM_COUNTRY` | Country code for Open Charge Map searches. | `IN` |
| `GEOCODE_COUNTRY` | Country code for Nominatim searches. | `in` |

Public services have usage policies and availability limits. Use them
responsibly and review their terms before relying on them.

## How it works

The LangGraph workflow performs these steps:

1. Parse the request and identify the vehicle and trip settings.
2. Geocode the origin and destination with Nominatim.
3. Request a road route from OSRM.
4. Retrieve weather from Open-Meteo and charger listings from Open Charge Map.
5. Estimate consumption and compute a feasible charging plan with a
   deterministic Dijkstra search.
6. Independently check the plan, then produce the itinerary and optional
   outputs.

Gemini is used only for interpreting a natural-language request and, when
enabled, writing the final explanation. Explicit `--from`, `--to`, and vehicle
options skip request parsing with Gemini. The charging plan itself is
calculated by Python code, not generated by the language model.

## Project structure

```text
ev_trip_planner/
├── __init__.py    # Original application reference docstring
├── __main__.py    # python -m ev_trip_planner entry point
├── cache.py       # SQLite cache, HTTP requests, and request throttling
├── cli.py         # Command-line arguments and output files
├── language.py    # Gemini parsing, explanations, and token budget
├── models.py      # Vehicle, trip, route, charger, and plan models
├── planner.py     # Energy estimates and deterministic charging planner
├── rendering.py   # Text itinerary and Leaflet map output
├── routing.py     # Geocoding, routing, weather, and charger data
├── selftest.py    # Offline self-test
└── workflow.py    # LangGraph orchestration

ev_trip_planner.py # Compatibility launcher
```

The original application docstring is preserved in
[`ev_trip_planner/__init__.py`](./ev_trip_planner/__init__.py) for reference.
