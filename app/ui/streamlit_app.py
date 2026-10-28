"""
Streamlit Web UI for EV Trip Planner
====================================
Interactive web application for natural-language and structured EV trip planning,
charging station optimization, and interactive route mapping.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, time
from typing import Any, Optional

import streamlit as st
import streamlit.components.v1 as components

# Ensure environment is loaded
from ..core.config import load_env
load_env()

from ..core.models import Config, IST, Plan, Vehicle, VEHICLES
from ..engine.planner import fmt_dur
from ..services import cache
from .rendering import render_map, render_text
from ..workflow.graph import build_graph, log


# -----------------------------------------------------------------------------
# Streamlit Page Setup & Custom CSS
# -----------------------------------------------------------------------------
def setup_page():
    st.set_page_config(
        page_title="EV Trip Planner | Smart Route & Charging",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
        <style>
        /* Base typography & fonts */
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        /* Hero Header */
        .hero-container {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(6, 182, 212, 0.12) 100%);
            border: 1px solid rgba(16, 185, 129, 0.25);
            border-radius: 16px;
            padding: 24px 28px;
            margin-bottom: 24px;
            position: relative;
            overflow: hidden;
        }
        .hero-title {
            font-size: 2.2rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            background: linear-gradient(90deg, #10b981 0%, #06b6d4 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .hero-subtitle {
            color: #94a3b8;
            font-size: 1.05rem;
            margin-top: 6px;
            margin-bottom: 0;
        }

        /* Metric cards */
        .metric-card {
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 12px;
            padding: 16px 20px;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .metric-card:hover {
            transform: translateY(-2px);
            border-color: rgba(16, 185, 129, 0.4);
        }
        .metric-label {
            color: #94a3b8;
            font-size: 0.85rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }
        .metric-val {
            font-size: 1.7rem;
            font-weight: 700;
            color: #f8fafc;
        }
        .metric-sub {
            font-size: 0.82rem;
            color: #10b981;
            margin-top: 2px;
        }

        /* Stop Card / Timeline */
        .stop-card {
            background: rgba(30, 41, 59, 0.6);
            border-left: 4px solid #10b981;
            border-top: 1px solid rgba(148, 163, 184, 0.1);
            border-right: 1px solid rgba(148, 163, 184, 0.1);
            border-bottom: 1px solid rgba(148, 163, 184, 0.1);
            border-radius: 0 12px 12px 0;
            padding: 16px 20px;
            margin-bottom: 14px;
        }
        .stop-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .stop-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: #f1f5f9;
        }
        .network-badge {
            background: rgba(6, 182, 212, 0.15);
            color: #38bdf8;
            border: 1px solid rgba(6, 182, 212, 0.3);
            border-radius: 9999px;
            padding: 3px 10px;
            font-size: 0.78rem;
            font-weight: 600;
        }
        .stop-stats {
            display: flex;
            gap: 20px;
            font-size: 0.92rem;
            color: #cbd5e1;
            flex-wrap: wrap;
        }
        .stat-item {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* Summary AI card */
        .ai-card {
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%);
            border: 1px solid rgba(99, 102, 241, 0.3);
            border-radius: 12px;
            padding: 18px 22px;
            margin-top: 16px;
            margin-bottom: 20px;
        }
        .ai-title {
            font-size: 0.95rem;
            font-weight: 700;
            color: #a5b4fc;
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .ai-content {
            font-size: 1rem;
            line-height: 1.6;
            color: #e2e8f0;
        }

        /* Buttons */
        .stButton>button {
            border-radius: 10px;
            font-weight: 600;
            transition: all 0.2s ease;
        }
        .stButton>button:hover {
            box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Sidebar: API Keys & Application Settings
# -----------------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown("### ⚙️ Planner Settings")

        with st.expander("🔑 API Configuration", expanded=False):
            st.caption("Keys are auto-loaded from `.env`. You can also override them here for this session.")
            gemini_key = st.text_input(
                "Gemini API Key",
                value=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "",
                type="password",
                help="Google AI Studio key for natural language parsing and explanations.",
            )
            ocm_key = st.text_input(
                "Open Charge Map Key",
                value=os.getenv("OCM_API_KEY") or "",
                type="password",
                help="Required to discover charging stations from Open Charge Map.",
            )
            user_agent = st.text_input(
                "User Agent Contact",
                value=os.getenv("APP_USER_AGENT") or "ev-trip-planner",
                help="Nominatim / OSRM contact identifier (e.g., ev-trip-planner user@example.com).",
            )
            if gemini_key:
                os.environ["GEMINI_API_KEY"] = gemini_key
            if ocm_key:
                os.environ["OCM_API_KEY"] = ocm_key
            if user_agent:
                os.environ["APP_USER_AGENT"] = user_agent

        # Key Status Badges
        has_gemini = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        has_ocm = bool(os.getenv("OCM_API_KEY"))

        st.markdown(
            f"""
            <div style="font-size: 0.85rem; padding: 10px; background: rgba(30,41,59,0.5); border-radius: 8px; margin-bottom: 16px;">
                <div>{'🟢' if has_gemini else '🟡'} <b>Gemini AI:</b> {'Configured' if has_gemini else 'Missing (Form mode still works)'}</div>
                <div>{'🟢' if has_ocm else '🔴'} <b>Open Charge Map:</b> {'Configured' if has_ocm else 'Missing API Key'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("### 🚘 Vehicle Database")
        selected_preview_vehicle = st.selectbox(
            "Quick View Specs",
            list(VEHICLES.keys()),
            index=2,  # Nexon EV
        )
        v = VEHICLES[selected_preview_vehicle]
        st.markdown(
            f"""
            <div style="font-size: 0.88rem; background: rgba(15,23,42,0.6); padding: 12px; border-radius: 8px; border: 1px solid rgba(148,163,184,0.15);">
                <b>{v.name}</b><br>
                🔋 Battery: <b>{v.battery_kwh} kWh</b> ({v.usable_kwh:.1f} kWh usable)<br>
                ⚡ Consumption: <b>{v.wh_per_km} Wh/km</b><br>
                🔌 Max DC Speed: <b>{v.max_dc_kw} kW</b> (CCS2)<br>
                🛣️ Est. Max Range: <b>~{(v.usable_kwh * 1000 / v.wh_per_km):.0f} km</b>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")
        with st.expander("🛠️ Advanced Options", expanded=False):
            use_llm = st.toggle("Enable Gemini AI Explanations", value=True)
            if not use_llm:
                os.environ["EV_NO_LLM"] = "1"
            else:
                os.environ.pop("EV_NO_LLM", None)

            token_limit = st.number_input("Daily Token Budget", value=int(os.getenv("DAILY_TOKEN_BUDGET", "100000")), step=10000)
            os.environ["DAILY_TOKEN_BUDGET"] = str(token_limit)

            ocm_country = st.text_input("Country Code (OCM)", value=os.getenv("OCM_COUNTRY", "IN"))
            os.environ["OCM_COUNTRY"] = ocm_country

            if st.button("🧹 Clear Local Cache"):
                try:
                    cache.clear_cache()
                    st.success("Cache cleared!")
                except Exception as err:
                    st.error(f"Error clearing cache: {err}")


        st.caption("EV Trip Planner v0.1.0 • Built with Streamlit & LangGraph")


# -----------------------------------------------------------------------------
# Main Application Flow
# -----------------------------------------------------------------------------
def main():
    setup_page()
    render_sidebar()

    # Hero Banner
    st.markdown(
        """
        <div class="hero-container">
            <h1 class="hero-title">⚡ EV Trip Planner</h1>
            <p class="hero-subtitle">
                Plan long-distance EV journeys with optimal multi-stop DC fast charging recommendations,
                terrain/weather adjustments, and interactive route mapping.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Input Mode Tabs
    tab_nl, tab_form = st.tabs(["💬 Natural Language Prompt (AI)", "🛠️ Structured Route Planner"])

    init_state: Optional[dict] = None

    # Tab 1: Natural Language
    with tab_nl:
        st.markdown("Describe your trip in plain English. The Gemini model parses your origin, destination, vehicle, and timing.")
        
        # Quick suggestion chips
        st.markdown("<span style='font-size:0.85rem; color:#94a3b8;'>Try one of these examples:</span>", unsafe_allow_html=True)
        col_c1, col_c2, col_c3 = st.columns(3)
        sample_prompt = None
        if col_c1.button("🚗 Delhi to Jaipur (Nexon EV)", use_container_width=True):
            sample_prompt = "Delhi to Jaipur in a Tata Nexon EV, leaving 7am tomorrow, start at 90%"
        if col_c2.button("🚗 Mumbai to Pune (MG ZS EV)", use_container_width=True):
            sample_prompt = "Mumbai to Pune in an MG ZS EV, leaving 8:30am with 80% battery"
        if col_c3.button("🚗 Bengaluru to Mysuru (Punch EV)", use_container_width=True):
            sample_prompt = "Bengaluru to Mysuru in a Tata Punch EV with 95% charge"

        default_text = sample_prompt or "Delhi to Jaipur in a Tata Nexon EV, leaving 7am tomorrow, start at 90%"
        prompt_input = st.text_area(
            "Trip description",
            value=default_text,
            height=100,
            placeholder="e.g. Plan a drive from Delhi to Agra in an MG ZS EV, start battery 85%, reserve 15%",
            label_visibility="collapsed",
        )

        col_run1, _ = st.columns([1, 4])
        if col_run1.button("🚀 Plan Trip (AI)", type="primary", use_container_width=True):
            if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
                st.warning("⚠️ No Gemini API Key configured in `.env` or sidebar! Natural language parsing requires a key. Switch to the Structured Planner tab to plan without an LLM key.")
            else:
                init_state = {"text": prompt_input.strip()}

    # Tab 2: Structured Form
    with tab_form:
        st.markdown("Set exact waypoints and battery constraints directly without calling an LLM.")
        with st.form("structured_trip_form"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                origin = st.text_input("Origin City / Landmark", value="Delhi", placeholder="e.g. New Delhi, Connaught Place")
            with col_f2:
                dest = st.text_input("Destination City / Landmark", value="Jaipur", placeholder="e.g. Jaipur, Rajasthan")

            col_v1, col_v2 = st.columns([2, 1])
            with col_v1:
                vehicle_choice = st.selectbox(
                    "Vehicle Model",
                    list(VEHICLES.keys()) + ["Custom EV..."],
                    index=2,  # Tata Nexon EV
                )
            with col_v2:
                depart_time_input = st.time_input("Departure Time (IST)", value=time(7, 0))

            custom_vehicle = None
            if vehicle_choice == "Custom EV...":
                st.markdown("##### Custom Vehicle Specifications")
                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    custom_bat = st.number_input("Battery Capacity (kWh)", min_value=10.0, max_value=200.0, value=50.0, step=1.0)
                with cc2:
                    custom_wh = st.number_input("Consumption (Wh/km)", min_value=50.0, max_value=400.0, value=160.0, step=5.0)
                with cc3:
                    custom_kw = st.number_input("Max DC Charge Speed (kW)", min_value=10.0, max_value=350.0, value=60.0, step=5.0)
                custom_vehicle = Vehicle("Custom EV", custom_bat, custom_wh, custom_kw)

            col_b1, col_b2, col_b3 = st.columns(3)
            with col_b1:
                soc_start = st.slider("Starting Battery (%)", min_value=20, max_value=100, value=90, step=5)
            with col_b2:
                soc_reserve = st.slider("Arrival Reserve (%)", min_value=5, max_value=30, value=10, step=1, help="Safety buffer on arrival")
            with col_b3:
                soc_target = st.slider("Target Charge at Stops (%)", min_value=50, max_value=100, value=80, step=5, help="Standard fast-charge cutoff")

            submit_form = st.form_submit_button("🚀 Plan Trip (Form)", type="primary", use_container_width=True)
            if submit_form:
                form_data = {
                    "origin": origin.strip(),
                    "destination": dest.strip(),
                    "vehicle": None if vehicle_choice == "Custom EV..." else vehicle_choice,
                    "start_soc_percent": float(soc_start),
                    "departure_time": depart_time_input.strftime("%H:%M"),
                    "reserve_percent": float(soc_reserve),
                    "charge_to_percent": float(soc_target),
                }
                if custom_vehicle:
                    form_data["custom_vehicle"] = custom_vehicle
                init_state = {"form": form_data}

    # Execute Plan if triggered
    if init_state is not None:
        run_planner(init_state)


# -----------------------------------------------------------------------------
# Planning Execution & Result Display
# -----------------------------------------------------------------------------
def run_planner(init_state: dict):
    st.markdown("---")
    status_holder = st.status("⚡ Optimizing route & calculating charging stops...", expanded=True)

    try:
        with status_holder:
            st.write("🔍 Initializing workflow graph...")
            graph = build_graph()

            st.write("📍 Geocoding route and requesting OSRM road geometry...")
            st.write("🌤️ Checking Open-Meteo weather forecasts...")
            st.write("🔌 Searching Open Charge Map stations along route corridor...")
            st.write("🧠 Computing deterministic Dijkstra multi-stop charging schedule...")

            # Execute LangGraph pipeline
            final_state = graph.invoke(init_state)
            status_holder.update(label="✅ Route and charging plan complete!", state="complete", expanded=False)

    except Exception as exc:
        status_holder.update(label="❌ Planning failed", state="error", expanded=True)
        st.error(f"**Error executing trip planner:** {exc}")
        return

    # Check for clarification request from LLM
    if final_state.get("clarification"):
        st.info(f"ℹ️ **Clarification Needed:** {final_state['clarification']}")
        return

    plan: Optional[Plan] = final_state.get("plan")
    if not plan:
        st.error("No plan was generated. Please check your origin and destination.")
        return

    # Check feasibility
    if not plan.feasible:
        st.error(f"### ❌ Infeasible Trip Plan\n**Reason:** {plan.reason}")
        if plan.warnings:
            st.warning("⚠️ **Warnings:**\n" + "\n".join(f"- {w}" for w in plan.warnings))
        return

    # Display Feasible Plan
    display_results(final_state)


def display_results(state: dict):
    plan: Plan = state["plan"]
    vehicle: Vehicle = state.get("vehicle", VEHICLES.get("Tata Nexon EV"))
    origin = state.get("origin_name", "Origin")
    dest = state.get("dest_name", "Destination")

    # Header summary banner
    st.markdown(
        f"""
        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 12px; padding: 16px 20px; margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.35rem; font-weight: 700; color: #f8fafc;">📍 {origin} ➔ {dest}</span>
                    <span style="margin-left: 12px; background: rgba(16,185,129,0.2); color:#10b981; padding: 4px 10px; border-radius: 9999px; font-weight: 600; font-size: 0.85rem;">Feasible Plan</span>
                </div>
                <div style="color: #94a3b8; font-size: 0.95rem;">
                    Vehicle: <b style="color: #f1f5f9;">{vehicle.name}</b>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Key Metrics Cards Row
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Total Distance</div>
                <div class="metric-val">{plan.total_km:.0f} <span style="font-size: 1rem;">km</span></div>
                <div class="metric-sub">Road Route</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Total Duration</div>
                <div class="metric-val">{fmt_dur(plan.total_min)}</div>
                <div class="metric-sub">{plan.depart_time} ➔ {plan.arrive_time}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Charging Time</div>
                <div class="metric-val">{fmt_dur(plan.charge_min)}</div>
                <div class="metric-sub">{len(plan.stops)} stop(s)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m4:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Arrival Battery</div>
                <div class="metric-val">{plan.arrive_soc * 100:.0f}%</div>
                <div class="metric-sub">Start: {plan.start_soc * 100:.0f}%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m5:
        temp_val = plan.assumptions.get("temperature_c")
        temp_str = f"{round(temp_val)}°C" if temp_val is not None else "N/A"
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">Avg Efficiency</div>
                <div class="metric-val">{plan.assumptions.get('wh_per_km', 150)} <span style="font-size: 0.9rem;">Wh/km</span></div>
                <div class="metric-sub">Temp: {temp_str}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Main columns: Left for Map & Details, Right for Stops Timeline
    col_map, col_timeline = st.columns([3, 2])

    with col_map:
        st.markdown("### 🗺️ Interactive Route Map")
        map_html = render_map(state)
        components.html(map_html, height=520, scrolling=False)

        # AI Trip Explanation / Narrative
        if state.get("explanation"):
            st.markdown(
                f"""
                <div class="ai-card">
                    <div class="ai-title">✨ AI Trip Insights</div>
                    <div class="ai-content">{state["explanation"]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with col_timeline:
        st.markdown(f"### 🔌 Charging Itinerary ({len(plan.stops)} Stops)")

        if not plan.stops:
            st.markdown(
                """
                <div style="background: rgba(16, 185, 129, 0.15); border: 1px dashed #10b981; border-radius: 12px; padding: 24px; text-align: center;">
                    <div style="font-size: 2rem; margin-bottom: 8px;">🎉</div>
                    <h4 style="margin: 0; color: #10b981;">Direct Trip - No Stops Needed!</h4>
                    <p style="color: #94a3b8; margin-top: 8px; font-size: 0.95rem;">
                        Your battery has sufficient range to reach the destination comfortably with reserve to spare.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            for st_item in plan.stops:
                st.markdown(
                    f"""
                    <div class="stop-card">
                        <div class="stop-header">
                            <span class="stop-title">Stop {st_item.index}: {st_item.name}</span>
                            <span class="network-badge">{st_item.network}</span>
                        </div>
                        <div class="stop-stats">
                            <div class="stat-item">📍 <b>km {st_item.pos_km:.0f}</b> (+{st_item.detour_km:.1f} km detour)</div>
                            <div class="stat-item">⚡ <b>{st_item.power_kw:.0f} kW DC</b></div>
                            <div class="stat-item">⏱️ <b>{st_item.charge_min:.0f} min</b> charge</div>
                        </div>
                        <div style="margin-top: 10px; font-size: 0.92rem; color: #38bdf8;">
                            🔋 Arrive at <b>{st_item.arrive_time} ({st_item.arrive_soc * 100:.0f}%)</b> ➔ Leave at <b>{st_item.depart_time} ({st_item.depart_soc * 100:.0f}%)</b>
                        </div>
                        {f'<div style="margin-top: 6px; font-size: 0.82rem; color: #94a3b8;">🛡️ Backup: {st_item.backup["name"]} ({st_item.backup["power_kw"]:.0f} kW) at km {st_item.backup["pos_km"]:.0f}</div>' if st_item.backup else ''}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # Warnings / Notes
        if plan.warnings:
            st.markdown("#### ⚠️ Advisory Warnings")
            for w in plan.warnings:
                st.warning(w)

    st.markdown("---")

    # Exports and Raw Data
    with st.expander("📥 Export Itinerary & Inspect Data", expanded=False):
        c_exp1, c_exp2, c_exp3 = st.columns(3)
        with c_exp1:
            raw_text = render_text(state)
            st.download_button(
                "📄 Download Text Itinerary",
                data=raw_text,
                file_name="ev_trip_itinerary.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with c_exp2:
            st.download_button(
                "🗺️ Download HTML Map",
                data=map_html,
                file_name="trip_map.html",
                mime="text/html",
                use_container_width=True,
            )
        with c_exp3:
            json_blob = json.dumps(asdict(plan), indent=2, default=str)
            st.download_button(
                "💾 Download Plan JSON",
                data=json_blob,
                file_name="ev_plan.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("##### Plan Details (JSON)")
        st.json(asdict(plan))


if __name__ == "__main__":
    main()
