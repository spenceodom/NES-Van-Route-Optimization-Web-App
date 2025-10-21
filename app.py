import streamlit as st
import os
import math
from collections import OrderedDict
import pandas as pd
from datetime import time
from src.models.route_models import StopModel
from src.optimization.route_optimizer import RouteOptimizer

st.set_page_config(
    page_title="NES Van Route Optimizer",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

MAX_VAN_CAPACITY = 10

def is_wheelchair(val):
    if pd.isnull(val):
        return False
    val_str = str(val).strip().lower()
    return val_str in ["y", "yes", "true", "1"]

def format_distance(meters):
    """Format distance in meters to human readable format"""
    try:
        if meters is None:
            return "—"
        meters_int = int(meters)
        if meters_int >= 1000:
            km = meters_int / 1000.0
            return f"{km:.1f} km"
        else:
            return f"{meters_int} m"
    except Exception:
        return str(meters)

def format_duration(seconds):
    """Format duration in seconds to human readable format"""
    minutes = seconds // 60
    if minutes >= 60:
        hours = minutes // 60
        remaining_minutes = minutes % 60
        return f"{hours}h {remaining_minutes}m"
    else:
        return f"{minutes}m"

def inject_route_css():
    """Inject CSS used by the van route cards and grid."""
    st.markdown(
        """
        <style>
        .routes-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
        .routes-section { margin-top: 12px; }
        @media (min-width: 900px) { .routes-grid { grid-template-columns: 1fr 1fr; } }
        @media (min-width: 1300px) { .routes-grid { grid-template-columns: 1fr 1fr 1fr; } }
        .card { background: #ffffff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06); }
        .card-body { padding: 16px; }
        .card-header { display: flex; align-items: center; justify-content: space-between; }
        .card-title { font-weight: 700; font-size: 20px; color: #111827; }
        .title-blue { color: #2563EB; }
        .title-green { color: #16A34A; }
        .title-red { color: #DC2626; }
        .title-purple { color: #7C3AED; }
        .title-amber { color: #D97706; }
        .pill { background: #EEF2FF; color: #4338CA; font-weight: 600; font-size: 12px; padding: 4px 10px; border-radius: 9999px; }
        .meta { display:flex; align-items:center; color:#6B7280; font-size: 14px; margin-top: 6px; }
        .meta .clock { width: 18px; height: 18px; margin-right: 6px; }
        .stop { padding-top: 16px; border-top: 1px solid #F3F4F6; }
        .stop:first-child { padding-top: 0; border-top: none; }
        .stop-row { display:flex; align-items:flex-start; }
        .stop-num { background:#E5E7EB; color:#374151; width:32px; height:32px; border-radius:9999px; display:flex; align-items:center; justify-content:center; font-weight:700; flex-shrink:0; }
        .stop-content { margin-left: 12px; }
        .stop-address { font-weight:600; color:#1F2937; }
        .passenger { color:#4B5563; margin-top: 4px; }
        .van-section-title { font-weight: 800; font-size: 22px; margin: 8px 0 6px; }
        .van-section-title.wheelchair { margin-top: 36px; }
        </style>
        """,
        unsafe_allow_html=True
    )

def main():
    st.title("NES Van Route Optimizer")

    # Always ensure card CSS is available
    inject_route_css()

    # Optional admin gate controlled by APP_PASSWORD in secrets/env
    required_password = None
    try:
        required_password = st.secrets.get("APP_PASSWORD")  # type: ignore[attr-defined]
    except Exception:
        required_password = None
    if not required_password:
        required_password = os.getenv("APP_PASSWORD")

    is_admin = False
    if required_password:
        with st.sidebar:
            if not st.session_state.get("authed", False):
                st.markdown("**Admin Access**")
                pwd = st.text_input("Admin password", type="password", key="admin_pw")
                if pwd:
                    if pwd == required_password:
                        st.session_state["authed"] = True
                        st.success("Access granted")
                    else:
                        st.error("Incorrect password")
            is_admin = bool(st.session_state.get("authed", False))
            if not is_admin:
                st.stop()
    else:
        is_admin = True  # no password configured, treat as admin for debug toggle

    # API Key Configuration
    with st.sidebar:
        # Depot address selection (radio buttons)
        st.markdown("**Day Program Address**")
        depot_option = st.radio(
            " ",
            ("Day Program", "Other"),
            index=0,
            label_visibility="collapsed"
        )
        if depot_option == "Day Program":
            depot_address = "10404 1055 W, South Jordan, UT 84095"
            st.info(f"Day Program address set to: {depot_address}")
        else:
            depot_address = st.text_input(
                "Enter Day Program Address",
                value="",
                help="Enter the starting and ending location for all routes"
            )
        # Number of regular vans
        number_of_vans = st.slider(
            "Number of Regular Vans",
            min_value=1,
            max_value=8,
            value=2,
            help="How many regular vans are available for this route? (Excludes wheelchair van)"
        )
        number_of_wheelchair_vans = st.slider(
            "Number of Wheelchair Vans",
            min_value=0,
            max_value=4,
            value=1,
            help="How many wheelchair vans are available for this route?"
        )
        # Per-van capacity controls for regular vans
        st.markdown("**Regular Van Capacities**")
        regular_capacities: list[int] = []
        for i in range(number_of_vans):
            cap = st.number_input(
                f"Capacity for Regular Van {i+1}",
                min_value=1,
                max_value=15,
                value=MAX_VAN_CAPACITY,
                key=f"reg_cap_{i}"
            )
            regular_capacities.append(int(cap))

        # Per-van capacity controls for wheelchair vans
        wheelchair_regular_caps: list[int] = []
        wheelchair_wheelchair_caps: list[int] = []
        if number_of_wheelchair_vans > 0:
            st.markdown("**Wheelchair Van Capacities**")
            for i in range(number_of_wheelchair_vans):
                cols_wc = st.columns(2)
                with cols_wc[0]:
                    rcap = st.number_input(
                        f"WC Van {i+1} regular seats",
                        min_value=0,
                        max_value=14,
                        value=1,
                        key=f"wc_reg_cap_{i}"
                    )
                with cols_wc[1]:
                    # Clamp default wheelchair seats so it never exceeds the max
                    max_wcap = 10
                    default_wcap = 5 if i == 0 else 10 - int(rcap)
                    if default_wcap < 0:
                        default_wcap = 0
                    if default_wcap > max_wcap:
                        default_wcap = max_wcap

                    wcap = st.number_input(
                        f"WC Van {i+1} wheelchair seats",
                        min_value=0,
                        max_value=max_wcap,
                        value=int(default_wcap),
                        key=f"wc_wc_cap_{i}"
                    )
                wheelchair_regular_caps.append(int(rcap))
                wheelchair_wheelchair_caps.append(int(wcap))
        # Fixed route start time (time selection removed)
        start_time = time(8, 0)
        st.divider()

        # Debug mode UI removed; default to False
        debug = False

        # API Key with server-managed fallback (hide UI when managed key exists)
        managed_api_key = None
        try:
            managed_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")  # type: ignore[attr-defined]
        except Exception:
            managed_api_key = None
        if not managed_api_key:
            managed_api_key = os.getenv("GOOGLE_MAPS_API_KEY")

        if managed_api_key:
            api_key = managed_api_key.strip()
        else:
            st.markdown("**Google Maps API Configuration**")
            api_key = st.text_input(
                "Google Maps API Key",
                type="password",
                help="Enter your Google Maps API key for geocoding and distance calculations"
            )
            api_key = api_key.strip() if api_key else api_key
            if not api_key:
                st.warning(" Google Maps API key is required for route optimization")
            else:
                st.success(" API key configured")

    st.header("Step 1: Upload Master List")
    master_file = st.file_uploader(
        "Upload Master List CSV (name, address, wheelchair)",
        type=['csv'],
        help="Upload a CSV with all individuals, their addresses, and wheelchair status."
    )
    if master_file is not None:
        try:
            master_df = pd.read_csv(master_file)
            master_df.columns = [col.lower() for col in master_df.columns]
            st.success(f" Loaded {len(master_df)} individuals from master list.")
            # Step 2: Select individuals for today (checkbox grid)
            st.header("Step 2: Select Individuals for Transport Today")
            all_names = master_df['name'].tolist()
            n = len(all_names)

            # Select All / Deselect All functionality
            col1, col2, _ = st.columns([1, 1, 2])
            if col1.button("✅ Select All"):
                for idx in range(n):
                    st.session_state[f"name_{idx}"] = True
            if col2.button("❌ Deselect All"):
                for idx in range(n):
                    st.session_state[f"name_{idx}"] = False

            # Show current selection status
            total_selected = 0
            cols = st.columns(3)
            selected_names = []

            for idx, name in enumerate(all_names):
                col = cols[idx % 3]
                key = f"name_{idx}"
                if key not in st.session_state:
                    st.session_state[key] = False
                if col.checkbox(name, key=key):
                    selected_names.append(name)
                    total_selected += 1

            # Display selection summary
            if total_selected > 0:
                st.info(f" {total_selected} of {len(all_names)} individuals selected for transport")
            else:
                st.info(f" No individuals selected yet. Click 'Select All' to choose everyone or select individuals manually.")

            if selected_names:
                selected_df = master_df[master_df['name'].isin(selected_names)].copy()
                # Prepare for optimization: split into wheelchair and regular
                selected_df['is_wheelchair'] = selected_df['wheelchair'].apply(is_wheelchair)
                wheelchair_df = selected_df[selected_df['is_wheelchair']]
                regular_df = selected_df[~selected_df['is_wheelchair']]
                
                # NEW: Handle wheelchair van constraint
                # Wheelchair van can carry ALL wheelchair passengers + 1 regular passenger
                wheelchair_stops = []
                regular_stops = []
                wheelchair_van_regular_passenger = None
                
                # Process wheelchair passengers (all go to wheelchair van)
                if not wheelchair_df.empty:
                    if number_of_wheelchair_vans == 0:
                        st.error(" Wheelchair passengers selected but wheelchair vans set to 0. Please increase wheelchair vans or deselect wheelchair passengers.")
                        return
                    wc_grouped = wheelchair_df.groupby('address')['name'].apply(list).reset_index()
                    for _, row in wc_grouped.iterrows():
                        wheelchair_stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=True))
                
                # Process regular passengers
                if not regular_df.empty:
                    # Group regular passengers by address first
                    regular_grouped = regular_df.groupby('address')['name'].apply(list).reset_index()
                    
                    # Check if we can move 1 regular passenger to wheelchair van
                    # (only if at least 1 wheelchair van exists)
                    if number_of_wheelchair_vans > 0 and len(regular_grouped) > 0 and wheelchair_stops:
                        # Take the first regular passenger for wheelchair van
                        first_regular_row = regular_grouped.iloc[0]
                        # Decide how many regular riders can be moved to wheelchair vans based on regular seat capacity
                        total_wc_regular_seats = sum(wheelchair_regular_caps) if wheelchair_regular_caps else 1
                        wheelchair_van_regular_passenger = first_regular_row['name'][0] if total_wc_regular_seats > 0 else None
                        
                        # Remove this passenger from regular processing
                        remaining_regular_names = []
                        for _, row in regular_grouped.iterrows():
                            if row['address'] == first_regular_row['address']:
                                # Remove the first passenger from this address
                                remaining_passengers = row['name'][1:] if len(row['name']) > 1 else []
                                if remaining_passengers:
                                    remaining_regular_names.extend(remaining_passengers)
                            else:
                                remaining_regular_names.extend(row['name'])
                        
                        # Create regular stops from remaining passengers
                        if remaining_regular_names:
                            remaining_regular_df = regular_df[regular_df['name'].isin(remaining_regular_names)]
                            remaining_grouped = remaining_regular_df.groupby('address')['name'].apply(list).reset_index()
                            for _, row in remaining_grouped.iterrows():
                                regular_stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=False))
                    else:
                        # No wheelchair van, all regular passengers go to regular vans
                        for _, row in regular_grouped.iterrows():
                            regular_stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=False))
                
                # Add the regular passenger to wheelchair van if we have one
                if wheelchair_van_regular_passenger:
                    # Find the passenger's address and add them to wheelchair stops
                    passenger_info = regular_df[regular_df['name'] == wheelchair_van_regular_passenger].iloc[0]
                    wheelchair_stops.append(StopModel(
                        address=passenger_info['address'], 
                        passengers=[wheelchair_van_regular_passenger], 
                        wheelchair=False
                    ))
                
                # Check per-stop capacity feasibility using the largest available regular van
                max_regular_capacity = max(regular_capacities) if regular_capacities else MAX_VAN_CAPACITY
                over_capacity = [s for s in regular_stops if len(s.passengers) > max_regular_capacity]
                if over_capacity:
                    st.error(f" One or more stops exceed your van capacity (max {max_regular_capacity}). Please adjust selections or increase capacities.")
                    for s in over_capacity:
                        st.warning(f"Address: {s.address} has {len(s.passengers)} passengers.")
                    return
                
                # Check if total regular demand can be met with available vans
                total_regular_passengers = sum(len(s.passengers) for s in regular_stops)
                total_capacity_available = sum(regular_capacities) if regular_capacities else number_of_vans * MAX_VAN_CAPACITY
                if total_regular_passengers > total_capacity_available:
                    st.error(f" Not enough total capacity. Need {total_regular_passengers}, but vans can carry {total_capacity_available}. Increase van count or capacities.")
                    return
                
                # Show passenger summary
                wheelchair_count = sum(len(stop.passengers) for stop in wheelchair_stops)
                regular_count = sum(len(stop.passengers) for stop in regular_stops)
                
                # Consolidated Passenger Summary into a single bubble
                summary_lines = ["**Passenger Summary:**"]
                if wheelchair_count > 0:
                    summary_lines.append(f"Wheelchair van: {wheelchair_count} passengers ({len(wheelchair_stops)} stops)")
                if regular_count > 0:
                    summary_lines.append(f"Regular vans: {regular_count} passengers ({len(regular_stops)} stops, using {number_of_vans} vans)")
                if wheelchair_van_regular_passenger:
                    summary_lines.append(f"Note: 1 regular passenger ({wheelchair_van_regular_passenger}) will ride in the wheelchair van to maximize efficiency")
                st.info("\n\n".join(summary_lines))

                # Optimize button
                if st.button(" Optimize Routes", disabled=not api_key):
                    if not api_key:
                        st.error(" Please configure Google Maps API key first")
                        return

                    with st.spinner(" Optimizing routes..."):
                        try:
                            # Initialize optimizer with API key
                            # Use user-defined per-van capacities when provided
                            effective_capacity = max(regular_capacities) if regular_capacities else MAX_VAN_CAPACITY
                            optimizer_regular = RouteOptimizer(depot_address, effective_capacity, api_key)

                            # Optimize regular routes
                            if regular_stops:
                                regular_result = optimizer_regular.optimize_route(
                                    regular_stops,
                                    start_time,
                                    number_of_vans,
                                    vehicle_capacities=regular_capacities if regular_capacities else None
                                )

                                # Suppress non-critical warnings in results-only view

                                if not regular_result['is_feasible']:
                                    st.error(" Could not find feasible routes for regular passengers")
                                else:
                                    # Display optimized routes as a single grid HTML block
                                    total_distance = 0
                                    total_duration = 0
                                    regular_cards: list[str] = []
                                    for route in regular_result['vehicle_routes']:
                                        if not route['stops']:
                                            continue
                                        duration_text = format_duration(route.get('duration', 0)) if 'duration' in route else "—"
                                        address_to_names = OrderedDict()
                                        for stop_idx in route['stops']:
                                            if 0 <= stop_idx - 1 < len(regular_stops):
                                                stop = regular_stops[stop_idx - 1]
                                                addr = stop.address
                                                if addr not in address_to_names:
                                                    address_to_names[addr] = []
                                                address_to_names[addr].extend(stop.passengers)

                                        stop_counter = 1
                                        stops_html_parts: list[str] = []
                                        for addr, names in address_to_names.items():
                                            passengers_html = "".join([f"<div class='passenger'>{p}</div>" for p in names])
                                            stops_html_parts.append(
                                                f"<div class='stop'>"
                                                f"<div class='stop-row'>"
                                                f"<div class='stop-num'>{stop_counter}</div>"
                                                f"<div class='stop-content'><div class='stop-address'>Stop {stop_counter} | {addr}</div>{passengers_html}</div>"
                                                f"</div>"
                                                f"</div>"
                                            )
                                            stop_counter += 1

                                        # Color classes for titles by van index
                                        color_classes = ["title-blue", "title-green", "title-red", "title-purple", "title-amber"]
                                        title_class = color_classes[(route['vehicle_id']) % len(color_classes)]

                                        card_html = (
                                            "<div class='card'><div class='card-body'>"
                                            f"<div class='card-header'><div class='card-title {title_class}'>Van {route['vehicle_id'] + 1}</div><span class='pill'>{len(address_to_names)} Stops</span></div>"
                                            f"<div class='meta'><svg class='clock' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path stroke-linecap='round' stroke-linejoin='round' d='M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'/></svg><span>Estimated time: {duration_text}</span></div>"
                                            + "".join(stops_html_parts) +
                                            "</div></div>"
                                        )

                                        regular_cards.append(card_html)
                                        total_distance += route['distance']
                                        if 'duration' in route:
                                            total_duration += route['duration']

                                    if regular_cards:
                                        grid_html = "<div class='routes-grid'>" + "".join(regular_cards) + "</div>"
                                        st.session_state["regular_grid_html"] = grid_html
                                        st.markdown("<div class='van-section-title'>Regular Vans</div>", unsafe_allow_html=True)
                                        st.markdown(f"<div class='routes-section'>{grid_html}</div>", unsafe_allow_html=True)

                            # Handle wheelchair routes (separate optimization)
                            if number_of_wheelchair_vans > 0 and wheelchair_stops:
                                # For wheelchair vans, allow all wheelchair passengers plus at most 1 regular passenger per van
                                wc_capacity = sum(len(s.passengers) for s in wheelchair_stops)
                                optimizer_wheelchair = RouteOptimizer(depot_address, max(1, wc_capacity), api_key)
                                wheelchair_result = optimizer_wheelchair.optimize_route(
                                    wheelchair_stops,
                                    start_time,
                                    number_of_wheelchair_vans,
                                    max_regular_non_wheelchair=None,
                                    vehicle_capacities=None,
                                    regular_non_wheelchair_capacities=wheelchair_regular_caps if wheelchair_regular_caps else None,
                                    wheelchair_capacities=wheelchair_wheelchair_caps if wheelchair_wheelchair_caps else None
                                )

                                # Suppress non-critical warnings in results-only view

                                if wheelchair_result['is_feasible'] and wheelchair_result['vehicle_routes']:
                                    wc_cards: list[str] = []
                                    for wc_route in wheelchair_result['vehicle_routes']:
                                        if not wc_route['stops']:
                                            continue
                                        duration_text = format_duration(wc_route.get('duration', 0)) if 'duration' in wc_route else "—"
                                        address_to_names_wc = OrderedDict()
                                        for stop_idx in wc_route['stops']:
                                            if 0 <= stop_idx - 1 < len(wheelchair_stops):
                                                stop = wheelchair_stops[stop_idx - 1]
                                                addr = stop.address
                                                if addr not in address_to_names_wc:
                                                    address_to_names_wc[addr] = []
                                                address_to_names_wc[addr].extend(stop.passengers)

                                        stop_counter_wc = 1
                                        wc_stops_html_parts: list[str] = []
                                        for addr, names in address_to_names_wc.items():
                                            passengers_html = "".join([f"<div class='passenger'>{p}</div>" for p in names])
                                            wc_stops_html_parts.append(
                                                f"<div class='stop'>"
                                                f"<div class='stop-row'>"
                                                f"<div class='stop-num'>{stop_counter_wc}</div>"
                                                f"<div class='stop-content'><div class='stop-address'>Stop {stop_counter_wc} | {addr}</div>{passengers_html}</div>"
                                                f"</div>"
                                                f"</div>"
                                            )
                                            stop_counter_wc += 1

                                        color_classes = ["title-blue", "title-green", "title-red", "title-purple", "title-amber"]
                                        title_class = color_classes[(wc_route['vehicle_id']) % len(color_classes)]

                                        wc_card_html = (
                                            "<div class='card'><div class='card-body'>"
                                            f"<div class='card-header'><div class='card-title {title_class}'>Van {wc_route['vehicle_id'] + 1}</div><span class='pill'>{len(address_to_names_wc)} Stops</span></div>"
                                            f"<div class='meta'><svg class='clock' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path stroke-linecap='round' stroke-linejoin='round' d='M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'/></svg><span>Estimated time: {duration_text}</span></div>"
                                            + "".join(wc_stops_html_parts) +
                                            "</div></div>"
                                        )
                                        wc_cards.append(wc_card_html)

                                    if wc_cards:
                                        wc_grid_html = "<div class='routes-grid'>" + "".join(wc_cards) + "</div>"
                                        st.session_state["wc_grid_html"] = wc_grid_html
                                        st.markdown("<div class='van-section-title'>Wheelchair Vans</div>", unsafe_allow_html=True)
                                        st.markdown(f"<div class='routes-section'>{wc_grid_html}</div>", unsafe_allow_html=True)

                            # Start over control under results (no page stop)
                            if st.session_state.get("regular_grid_html") or st.session_state.get("wc_grid_html"):
                                if st.button("Start Over"):
                                    for k in ["regular_grid_html", "wc_grid_html"]:
                                        if k in st.session_state:
                                            del st.session_state[k]
                                    try:
                                        st.rerun()
                                    except Exception:
                                        st.experimental_rerun()

                        except ValueError as ve:
                            st.error(f" Configuration Error: {str(ve)}")
                            if debug:
                                import traceback
                                st.text(traceback.format_exc())
                        except Exception as e:
                            st.error(f" Optimization failed: {str(e)}")
                            st.info(" Make sure your Google Maps API key is valid and has the required permissions")
                            if debug:
                                import traceback
                                st.text(traceback.format_exc())
        except Exception as e:
            st.error(f" Failed to read or process master list: {str(e)}")

if __name__ == "__main__":
    main()
