# ⚡ EV Trip Planner

An intelligent, multi-stop electric vehicle (EV) route and charging planner built with **Python**, **LangGraph**, **Gemini AI**, and **Streamlit**.

EV Trip Planner turns a trip query into an optimal route with calculated charging stops. It supports both **natural-language requests** powered by Google Gemini and **direct structured inputs**. It computes energy consumption based on temperature and vehicle characteristics, queries public charging stations along the route corridor, and uses a **deterministic Dijkstra graph search** to recommend optimal DC fast charging stops.

> ⚠️ **Planning Aid, Not a Guarantee:** Vehicle energy consumption figures are estimated heuristics, public charger information can be incomplete or outdated, and the planner does not model elevation changes or charger queues. Always verify charger availability in provider apps (Tata Power EZ Charge, Statiq, Jio-bp pulse, etc.) before travelling.

---

## 🌟 Key Features

- **🌐 Interactive Streamlit Web UI**:
  - **Natural-Language Prompting**: Ask naturally (e.g., *"Delhi to Jaipur in a Tata Nexon EV, leaving 7am tomorrow, start at 90%"*).
  - **Structured Route Planner**: Choose origin, destination, vehicle model, departure time, and battery thresholds with responsive sliders.
  - **Interactive Leaflet Route Map**: Visual road polyline, start/destination pins, and clickable charging stop nodes with detailed popups.
  - **Charging Stops Timeline**: Visual cards detailing arrival/departure battery %, charge duration, charger kW speed, and backup stations.
  - **Trip Metrics Dashboard**: Real-time breakdown of driving time, charging time, total distance, and battery on arrival.
  - **One-Click Exports**: Download interactive HTML maps (`trip.html`), plain-text itineraries (`itinerary.txt`), and raw JSON plans (`plan.json`).
- **🧠 Trustworthy & Deterministic**:
  - The charging plan is computed by **deterministic Python algorithms (Dijkstra shortest path)**, *never* hallucinated by the LLM.
  - Gemini is used only for interpreting natural-language input and drafting friendly explanations.
  - Every LLM explanation is number-checked against the computed plan; if numbers mismatch, a verified template is used.
- **🔌 Live Open Data Integrations**:
  - **Nominatim / OpenStreetMap**: Geocoding locations.
  - **OSRM**: Real road geometry and driving distances.
  - **Open-Meteo**: Ambient weather & temperature forecasts.
  - **Open Charge Map (OCM)**: Live DC fast-charging points along the route corridor.
- **⚡ Thread-Safe & Efficient**:
  - All external API calls are cached locally in SQLite.
  - Fully thread-safe database handling (`RLock` + `check_same_thread=False`) for seamless multi-threaded Streamlit and LangGraph execution.
  - Built-in token budget tracking for Gemini.

---

## 🚀 Quick Start (Under 2 Minutes)

### 1. Clone & Install

Clone the repository and install dependencies using **`uv`** (recommended) or standard **`pip`**:

#### Option A: Using `uv` (Fastest)
```bash
# Sync all dependencies from lockfile
uv sync
```

#### Option B: Using standard Python venv
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install requests pydantic langgraph langchain-google-genai python-dotenv streamlit
```

---

### 2. Configure Environment (`.env`)

A `.env` file is loaded automatically on launch. Edit `.env` (or copy `.env.example` to `.env`):

```bash
cp .env.example .env
```

Open `.env` and configure your keys:

```dotenv
# 1. Google Gemini API (Required for natural-language mode)
# Free key at: https://aistudio.google.com/
GEMINI_API_KEY="your-gemini-api-key"

# 2. Open Charge Map API (Required for live EV charger data)
# Free key at: https://openchargemap.org/site/develop/api
OCM_API_KEY="your-open-charge-map-api-key"

# 3. User-Agent Contact (Required by Nominatim/OSRM usage policies)
# Must include an email contact!
APP_USER_AGENT="ev-trip-planner your.email@example.com"
```

> 💡 **Note**: If you don't have a Gemini API key yet, the **Structured Form mode** works 100% offline without any LLM! Only an Open Charge Map key and a valid `APP_USER_AGENT` email are required for real charging plans.

---

## 🖥️ Running the Application

### Option 1: Streamlit Web UI (Recommended)

Launch the interactive web interface:

```bash
# Using uv:
uv run streamlit run streamlit_app.py

# Or within an activated virtual environment:
streamlit run streamlit_app.py
```

Open your browser at **`http://localhost:8501`**.

#### What You Can Do in the Web App:
- Toggle between **Natural Language Prompt (AI)** and **Structured Route Planner**.
- Select from built-in Indian EVs (Tata Nexon EV, Punch EV, Tiago EV, MG ZS EV, Mahindra XUV400, etc.) or configure a custom vehicle.
- Adjust Starting Battery (%), Arrival Reserve (%), and Target Charge at Stops (%).
- Pan, zoom, and explore the interactive Leaflet map.
- Inspect the charging itinerary cards and download your trip artifacts with one click.

---

### Option 2: Command-Line Interface (CLI)

The CLI supports both natural-language queries and direct flags:

#### Natural Language Query (requires Gemini key)
```bash
uv run ev_trip_planner.py "Delhi to Jaipur in a Tata Nexon EV, leaving 7am tomorrow, start at 90%"
```

#### Explicit Structured Flags (skips LLM request parsing)
```bash
uv run ev_trip_planner.py \
  --from Delhi \
  --to Agra \
  --vehicle "Tata Tiago EV" \
  --soc 100 \
  --map trip.html \
  --json plan.json
```
*(Open `trip.html` in your browser to inspect the route map).*

#### Equivalent Package Invocation
```bash
uv run python -m app --from Delhi --to Agra --vehicle "MG ZS EV" --soc 85
```

#### Built-in Vehicle Database
```bash
uv run ev_trip_planner.py --list-vehicles
```

#### Offline Self-Test
Runs end-to-end synthetic planning tests with no network or API keys required:
```bash
uv run ev_trip_planner.py --selftest
# or: uv run python -m app --selftest
```

---

## 📋 CLI Reference Options

| Option | Type | Description |
|---|---|---|
| `text` | `string` | Optional plain-English trip request (e.g. `"Delhi to Agra in Nexon EV"`). |
| `--from` | `string` | Trip origin city or landmark. |
| `--to` | `string` | Trip destination city or landmark. |
| `--vehicle` | `string` | Built-in EV model name (e.g. `"Tata Nexon EV"`, `"MG ZS EV"`). |
| `--soc` | `float` | Starting battery percentage (default: `90`). |
| `--depart` | `string` | Departure time as `HH:MM` or ISO timestamp (India Standard Time). |
| `--reserve` | `float` | Minimum battery percentage to preserve on arrival (default: `10`). |
| `--charge-to` | `float` | Target battery percentage at intermediate stops (default: `80`). |
| `--battery-kwh` | `float` | Battery capacity in kWh (for custom vehicles). |
| `--wh-per-km` | `float` | Estimated consumption in Wh/km (for custom vehicles). |
| `--max-dc-kw` | `float` | Maximum DC charging rate in kW (for custom vehicles). |
| `--map` | `path` | Output path for interactive Leaflet HTML map (e.g. `trip.html`). |
| `--json` | `path` | Output path for full plan JSON (e.g. `plan.json`). |
| `--list-vehicles`| `flag` | Print built-in EV specifications and exit. |
| `--selftest` | `flag` | Run offline unit tests and mock graph verification. |

---

## ⚙️ Environment Variables & Configuration

All variables can be defined in `.env` or set in your environment:

| Variable | Description | Default |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio API key for request parsing & narrative explanations. | None |
| `GOOGLE_API_KEY` | Alternative key variable recognized by Google GenAI. | None |
| `OCM_API_KEY` | Open Charge Map API key for discovering EV charging points. | None |
| `APP_USER_AGENT` | Contact identifier for OpenStreetMap/Nominatim (e.g., `app user@example.com`). | `ev-trip-planner` |
| `GEMINI_MODEL` | Gemini model identifier. | `gemini-3.1-flash-lite` |
| `GEMINI_TEMPERATURE` | Model temperature (0.0 to 1.0). | `0.2` |
| `DAILY_TOKEN_BUDGET` | Maximum LLM tokens allowed per day (`0` disables limit). | `100000` |
| `EV_NO_LLM` | Set to `1` to bypass LLM calls entirely and use rule-based explanations. | Unset |
| `EV_FORM_NO_LLM` | Use template explanations for structured form inputs. | `1` |
| `EV_DB` | Path to SQLite database for caching and trip history. | `.ev_planner.db` |
| `OSRM_URL` | Base URL for OSRM routing service. | `https://router.project-osrm.org` |
| `OCM_COUNTRY` | Country code for Open Charge Map search. | `IN` |
| `GEOCODE_COUNTRY`| Country code for Nominatim geocoding. | `in` |

---

## 🏗️ Architecture & Pipeline

The planning workflow is orchestrated using **LangGraph**:

```
[User Request] 
      │
      ▼
   n_parse ──────── (Natural language parsed by Gemini, or Form direct input)
      │
      ▼
  n_geocode ────── (Nominatim geocodes origin & destination)
      │
      ▼
   n_route ─────── (OSRM fetches road geometry & distance)
      │
      ▼
  n_weather ────── (Open-Meteo fetches temperature along route)
      │
      ▼
  n_chargers ───── (Open Charge Map queries corridor for fast chargers)
      │
      ▼
   n_plan ──────── (Deterministic Dijkstra algorithm finds optimal charging stops)
      │
      ▼
   n_verify ────── (Strict rule verification: battery never below reserve)
      │
      ├─ Feasible ──► n_explain ──── (Gemini narrative explanation + number check)
      │                                     │
      └─ Infeasible ────────────────────────┴─► n_finalize ─► [Results & Map]
```

### Modular Codebase Structure

```text
ev-trip-planner/
├── app/
│   ├── __init__.py          # Package initialization & load_env
│   ├── __main__.py          # python -m app entry point
│   ├── core/                # Data models, vehicle DB, automatic .env loading
│   │   ├── __init__.py
│   │   ├── config.py        # Environment loader (.env)
│   │   └── models.py        # Vehicle, Plan, Route, Stop, Charger dataclasses
│   ├── engine/              # Core computational logic & AI
│   │   ├── __init__.py
│   │   ├── language.py      # Gemini parser, explainer & token budget guard
│   │   └── planner.py       # Deterministic Dijkstra EV charging algorithm
│   ├── services/            # External APIs & thread-safe caching
│   │   ├── __init__.py
│   │   ├── cache.py         # Thread-safe SQLite cache (RLock) & HTTP throttler
│   │   └── routing.py       # Nominatim, OSRM, OCM & Open-Meteo integrations
│   ├── tests/               # Offline test suite
│   │   ├── __init__.py
│   │   └── selftest.py      # Mock unit & graph verification tests
│   ├── ui/                  # User interfaces
│   │   ├── __init__.py
│   │   ├── cli.py           # Command-line interface parser
│   │   ├── rendering.py     # Terminal output & Leaflet HTML map generator
│   │   └── streamlit_app.py # Interactive Streamlit web application
│   └── workflow/            # LangGraph pipeline
│       ├── __init__.py
│       └── graph.py         # StateGraph orchestration & node definitions
├── .env                     # Local API keys & configuration (git-ignored)
├── .env.example             # Template for configuration
├── ev_trip_planner.py       # Root CLI compatibility launcher
├── streamlit_app.py         # Root Streamlit web app launcher
├── pyproject.toml           # Package configuration & dependencies
└── README.md                # Documentation
```

---

## 🔒 Security & Privacy

- **API Keys**: Private keys (`GEMINI_API_KEY`, `OCM_API_KEY`) stay strictly local in `.env`, which is ignored by `.gitignore`.
- **Local SQLite Caching**: External API responses and trip histories are stored in `.ev_planner.db` locally on your machine.
- **Budget Protection**: The `DAILY_TOKEN_BUDGET` prevents accidental over-usage of Google Gemini API quotas.

---

## 📄 License

This project is licensed under the MIT License. Free third-party services utilized (Nominatim, OSRM, Open-Meteo, Open Charge Map) have their own usage terms and attribution requirements.
