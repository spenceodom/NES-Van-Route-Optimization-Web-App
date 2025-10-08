import streamlit as st
import os
import math
from collections import OrderedDict
import copy
import pandas as pd
from datetime import time
from src.models.route_models import StopModel
from src.optimization.route_optimizer import RouteOptimizer

# Optional drag-and-drop support
try:
    from streamlit_sortables import sort_items  # type: ignore
    HAS_SORTABLES = True
except Exception:
    HAS_SORTABLES = False

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

def main():
    st.title("NES Van Route Optimizer")

    # Helper: render cards from current assignments with live metrics
    def render_cards_from_assignments(section_title: str, assignments: list[dict], is_wheelchair_section: bool):
        st.markdown(f"**{section_title}**")
        cards: list[str] = []
        for van in assignments:
            addr_to_pass = van['addr_to_passengers']
            address_order = van['address_order']
            stops_seq = [
                StopModel(address=a, passengers=list(addr_to_pass.get(a, [])), wheelchair=is_wheelchair_section)
                for a in address_order if a in addr_to_pass and addr_to_pass[a]
            ]
            metrics_optimizer = RouteOptimizer(depot_address, MAX_VAN_CAPACITY, api_key)
            metrics = metrics_optimizer.compute_metrics_for_sequence(stops_seq)
            duration_text_local = format_duration(metrics.get('duration', 0)) if metrics.get('is_feasible', False) else "—"
            stops_html_parts_local: list[str] = []
            stop_counter_local = 1
            for addr in address_order:
                names_here = addr_to_pass.get(addr, [])
                if not names_here:
                    continue
                passengers_html_local = "".join([f"<div class='passenger'>{p}</div>" for p in names_here])
                stops_html_parts_local.append(
                    f"<div class='stop'>"
                    f"<div class='stop-row'>"
                    f"<div class='stop-num'>{stop_counter_local}</div>"
                    f"<div class='stop-content'><div class='stop-address'>Stop {stop_counter_local} | {addr}</div>{passengers_html_local}</div>"
                    f"</div>"
                    f"</div>"
                )
                stop_counter_local += 1

            color_classes_local = ["title-blue", "title-green", "title-red", "title-purple", "title-amber"]
            title_class_local = color_classes_local[(van.get('vehicle_id', 0)) % len(color_classes_local)]
            card_html_local = (
                "<div class='card'><div class='card-body'>"
                f"<div class='card-header'><div class='card-title {title_class_local}'>Van {van.get('vehicle_id', 0) + 1}</div><span class='pill'>{len([a for a in address_order if addr_to_pass.get(a)])} Stops</span></div>"
                f"<div class='meta'><svg class='clock' xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path stroke-linecap='round' stroke-linejoin='round' d='M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'/></svg><span>Estimated time: {duration_text_local}</span></div>"
                + "".join(stops_html_parts_local) +
                "</div></div>"
            )
            cards.append(card_html_local)

        if cards:
            grid_html_local = "<div class='routes-grid'>" + "".join(cards) + "</div>"
            st.markdown(grid_html_local, unsafe_allow_html=True)

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
            min_value=1,
            max_value=4,
            value=1,
            help="How many wheelchair vans are available for this route?"
        )
        # Fixed route start time (time selection removed)
        start_time = time(8, 0)
        st.divider()

        # Optional debug toggle (admin only)
        debug = False
        if is_admin:
            debug = st.checkbox("Debug mode (show tracebacks)", value=False)

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
    # Card/grid CSS (lightweight, Tailwind-inspired)
    st.markdown(
        """
        <style>
        .routes-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
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
        .van-section-title { font-weight: 800; font-size: 22px; margin: 8px 0; }
        </style>
        """,
        unsafe_allow_html=True
    )
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
                    wc_grouped = wheelchair_df.groupby('address')['name'].apply(list).reset_index()
                    for _, row in wc_grouped.iterrows():
                        wheelchair_stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=True))
                
                # Process regular passengers
                if not regular_df.empty:
                    # Group regular passengers by address first
                    regular_grouped = regular_df.groupby('address')['name'].apply(list).reset_index()
                    
                    # Check if we can move 1 regular passenger to wheelchair van
                    # (only if wheelchair van exists and has capacity)
                    if wheelchair_stops and len(regular_grouped) > 0:
                        # Take the first regular passenger for wheelchair van
                        first_regular_row = regular_grouped.iloc[0]
                        wheelchair_van_regular_passenger = first_regular_row['name'][0]  # First passenger from first address
                        
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
                
                # Check capacity constraints for regular vans
                over_capacity = [s for s in regular_stops if len(s.passengers) > MAX_VAN_CAPACITY]
                if over_capacity:
                    st.error(f" One or more stops have more than {MAX_VAN_CAPACITY} passengers. Please adjust your selection.")
                    for s in over_capacity:
                        st.warning(f"Address: {s.address} has {len(s.passengers)} passengers.")
                    return
                
                # Check if total regular demand can be met with available vans
                total_regular_passengers = sum(len(s.passengers) for s in regular_stops)
                min_vans_needed = (total_regular_passengers + MAX_VAN_CAPACITY - 1) // MAX_VAN_CAPACITY if total_regular_passengers > 0 else 0
                if min_vans_needed > number_of_vans:
                    st.error(f" Not enough vans. {min_vans_needed} vans needed for {total_regular_passengers} regular passengers (max {MAX_VAN_CAPACITY} per van), but only {number_of_vans} vans available.")
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
                            # Force utilization of all available regular vans by tightening per-vehicle capacity
                            if regular_stops:
                                total_regular_passengers = sum(len(s.passengers) for s in regular_stops)
                                max_stop_load = max((len(s.passengers) for s in regular_stops), default=0)
                                forced_capacity = max(1, max_stop_load, math.ceil(total_regular_passengers / max(1, number_of_vans)))
                                forced_capacity = min(MAX_VAN_CAPACITY, forced_capacity)
                            else:
                                forced_capacity = MAX_VAN_CAPACITY

                            optimizer_regular = RouteOptimizer(depot_address, forced_capacity, api_key)

                            # Optimize regular routes
                            if regular_stops:
                                regular_result = optimizer_regular.optimize_route(regular_stops, start_time, number_of_vans)

                                if regular_result['geocoding_errors']:
                                    st.warning(" Some addresses could not be geocoded:")
                                    for error in regular_result['geocoding_errors']:
                                        st.write(f" {error}")

                                if not regular_result['is_feasible']:
                                    st.error(" Could not find feasible routes for regular passengers")
                                else:
                                    # Build assignments from optimized solution
                                    regular_assignments_built: list[dict] = []
                                    for route in regular_result['vehicle_routes']:
                                        if not route['stops']:
                                            continue
                                        address_to_names = OrderedDict()
                                        for stop_idx in route['stops']:
                                            if 0 <= stop_idx - 1 < len(regular_stops):
                                                stop = regular_stops[stop_idx - 1]
                                                addr = stop.address
                                                if addr not in address_to_names:
                                                    address_to_names[addr] = []
                                                address_to_names[addr].extend(stop.passengers)
                                        regular_assignments_built.append({
                                            'vehicle_id': route['vehicle_id'],
                                            'address_order': list(address_to_names.keys()),
                                            'addr_to_passengers': {a: list(p) for a, p in address_to_names.items()},
                                        })

                                    # Initialize/overwrite session state mappings and assignments
                                    if 'name_to_info' not in st.session_state:
                                        st.session_state['name_to_info'] = {
                                            row['name']: {
                                                'address': row['address'],
                                                'is_wheelchair': bool(row['is_wheelchair'])
                                            }
                                            for _, row in selected_df.iterrows()
                                        }
                                    # Always update to latest optimized result
                                    st.session_state['regular_vans_assignments'] = regular_assignments_built
                                    st.session_state['original_regular_vans_assignments'] = copy.deepcopy(regular_assignments_built)
                                    # Mark that we have results
                                    st.session_state['has_results'] = True

                                    # No overall totals per requirements

                            # Handle wheelchair routes (separate optimization)
                            if wheelchair_stops:
                                # For wheelchair vans, allow all wheelchair passengers plus at most 1 regular passenger per van
                                wc_capacity = sum(len(s.passengers) for s in wheelchair_stops)
                                optimizer_wheelchair = RouteOptimizer(depot_address, max(1, wc_capacity), api_key)
                                wheelchair_result = optimizer_wheelchair.optimize_route(
                                    wheelchair_stops,
                                    start_time,
                                    number_of_wheelchair_vans,
                                    max_regular_non_wheelchair=1
                                )

                                if wheelchair_result['geocoding_errors']:
                                    for error in wheelchair_result['geocoding_errors']:
                                        st.warning(f"Wheelchair geocoding error: {error}")

                                if wheelchair_result['is_feasible'] and wheelchair_result['vehicle_routes']:
                                    # Build wheelchair assignments only (render via shared renderer)
                                    wheelchair_assignments_built: list[dict] = []
                                    for wc_route in wheelchair_result['vehicle_routes']:
                                        if not wc_route['stops']:
                                            continue
                                        address_to_names_wc = OrderedDict()
                                        for stop_idx in wc_route['stops']:
                                            if 0 <= stop_idx - 1 < len(wheelchair_stops):
                                                stop = wheelchair_stops[stop_idx - 1]
                                                addr = stop.address
                                                if addr not in address_to_names_wc:
                                                    address_to_names_wc[addr] = []
                                                address_to_names_wc[addr].extend(stop.passengers)
                                        wheelchair_assignments_built.append({
                                            'vehicle_id': wc_route['vehicle_id'],
                                            'address_order': list(address_to_names_wc.keys()),
                                            'addr_to_passengers': {a: list(p) for a, p in address_to_names_wc.items()},
                                        })

                                    # Always update to latest optimized result and mark results
                                    st.session_state['wheelchair_vans_assignments'] = wheelchair_assignments_built
                                    st.session_state['original_wheelchair_vans_assignments'] = copy.deepcopy(wheelchair_assignments_built)
                                    st.session_state['has_results'] = True
                                else:
                                    st.write("No wheelchair passengers selected.")
                            else:
                                st.subheader("Wheelchair Van Route")
                                st.write("No wheelchair passengers selected.")

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

                        # Always-on editing with original cards + stop reorder + quick move
                        if st.session_state.get('has_results'):
                            st.divider()
                            # Reset control
                            col_reset, _ = st.columns([1, 3])
                            if col_reset.button("Reset to optimized"):
                                if 'original_regular_vans_assignments' in st.session_state:
                                    st.session_state['regular_vans_assignments'] = copy.deepcopy(st.session_state['original_regular_vans_assignments'])
                                if 'original_wheelchair_vans_assignments' in st.session_state:
                                    st.session_state['wheelchair_vans_assignments'] = copy.deepcopy(st.session_state['original_wheelchair_vans_assignments'])
                                st.success("Restored optimized plan.")
                                st.experimental_rerun()

                            name_to_info = st.session_state.get('name_to_info', {})

                            # Render current cards
                            if st.session_state.get('regular_vans_assignments'):
                                st.subheader("Regular Van Routes")
                                render_cards_from_assignments("Regular Van Routes", st.session_state['regular_vans_assignments'], is_wheelchair_section=False)
                            if st.session_state.get('wheelchair_vans_assignments'):
                                st.subheader("Wheelchair Van Routes")
                                render_cards_from_assignments("Wheelchair Van Routes", st.session_state['wheelchair_vans_assignments'], is_wheelchair_section=True)

                            # Stop reordering (per van) using streamlit-sortables
                            if HAS_SORTABLES:
                                st.markdown("**Reorder stops (addresses) within each van**")
                                # Regular vans
                                for idx_v, van in enumerate(st.session_state.get('regular_vans_assignments', [])):
                                    st.caption(f"Van {van.get('vehicle_id', 0) + 1} (Regular)")
                                    current_order = van['address_order']
                                    new_order = sort_items(current_order, key=f"reg_stop_order_{idx_v}")
                                    if new_order and new_order != current_order:
                                        van['address_order'] = [a for a in new_order if a in van['addr_to_passengers']]
                                        st.success("Stop order updated.")
                                        st.experimental_rerun()
                                # Wheelchair vans
                                for idx_v, van in enumerate(st.session_state.get('wheelchair_vans_assignments', [])):
                                    st.caption(f"Van {van.get('vehicle_id', 0) + 1} (Wheelchair)")
                                    current_order = van['address_order']
                                    new_order = sort_items(current_order, key=f"wc_stop_order_{idx_v}")
                                    if new_order and new_order != current_order:
                                        van['address_order'] = [a for a in new_order if a in van['addr_to_passengers']]
                                        st.success("Stop order updated.")
                                        st.experimental_rerun()
                            else:
                                st.info("Install 'streamlit-sortables' to enable stop reordering.")

                            # Quick move (temporary) per van
                            st.markdown("**Quick move passengers (temporary until full drag-and-drop)**")
                            def get_bucket(sec: str) -> str:
                                return 'regular_vans_assignments' if sec == 'regular' else 'wheelchair_vans_assignments'

                            def list_passengers(van: dict) -> list[tuple[str, str]]:
                                pairs: list[tuple[str, str]] = []
                                for addr, names in van['addr_to_passengers'].items():
                                    for nm in names:
                                        pairs.append((nm, addr))
                                return pairs

                            # Regular vans quick move
                            for idx_v, van in enumerate(st.session_state.get('regular_vans_assignments', [])):
                                with st.container():
                                    st.caption(f"Move from Van {van.get('vehicle_id', 0) + 1} (Regular)")
                                    options = [f"{nm} — {addr}" for nm, addr in list_passengers(van)]
                                    if not options:
                                        continue
                                    sel = st.selectbox("Passenger", options=options, key=f"reg_move_sel_{idx_v}")
                                    target_section = st.selectbox("To section", options=["Regular", "Wheelchair"], key=f"reg_move_sec_{idx_v}")
                                    if target_section == "Regular":
                                        tgt_bucket = 'regular_vans_assignments'
                                        tgt_vans = st.session_state.get(tgt_bucket, [])
                                    else:
                                        tgt_bucket = 'wheelchair_vans_assignments'
                                        tgt_vans = st.session_state.get(tgt_bucket, [])
                                    tgt_indices = [v.get('vehicle_id', 0) + 1 for v in tgt_vans]
                                    tgt_choice = st.selectbox("To van #", options=tgt_indices or [1], key=f"reg_move_tgt_{idx_v}")
                                    insert_pos = st.selectbox("Insert position", options=["Beginning", "End"], key=f"reg_move_pos_{idx_v}")
                                    if st.button("Move", key=f"reg_move_btn_{idx_v}"):
                                        # Parse selection
                                        sel_name = sel.split(" — ")[0].strip()
                                        sel_addr = sel.split(" — ")[1].strip()
                                        # Remove from source
                                        if sel_addr in van['addr_to_passengers'] and sel_name in van['addr_to_passengers'][sel_addr]:
                                            van['addr_to_passengers'][sel_addr].remove(sel_name)
                                            if not van['addr_to_passengers'][sel_addr]:
                                                van['addr_to_passengers'].pop(sel_addr, None)
                                                van['address_order'] = [a for a in van['address_order'] if a != sel_addr]
                                        # Determine target van
                                        target_van = None
                                        for v in tgt_vans:
                                            if v.get('vehicle_id', 0) + 1 == tgt_choice:
                                                target_van = v
                                                break
                                        if not target_van:
                                            st.error("Invalid target van")
                                            st.experimental_rerun()
                                        # Constraints
                                        info = name_to_info.get(sel_name, {"address": None, "is_wheelchair": False})
                                        p_is_wc = bool(info.get('is_wheelchair', False))
                                        if tgt_bucket == 'regular_vans_assignments' and p_is_wc:
                                            st.warning("Cannot move a wheelchair passenger into a regular van.")
                                            st.experimental_rerun()
                                        if tgt_bucket == 'wheelchair_vans_assignments':
                                            cnt_regular = 0
                                            for names in target_van['addr_to_passengers'].values():
                                                for nm in names:
                                                    if not name_to_info.get(nm, {}).get('is_wheelchair', False):
                                                        cnt_regular += 1
                                            if not p_is_wc and cnt_regular >= 1:
                                                st.warning("Wheelchair van can carry at most 1 regular passenger.")
                                                st.experimental_rerun()
                                        # Add to target
                                        p_addr = info.get('address')
                                        if p_addr in target_van['addr_to_passengers']:
                                            target_van['addr_to_passengers'][p_addr].append(sel_name)
                                        else:
                                            target_van['addr_to_passengers'][p_addr] = [sel_name]
                                            if insert_pos == "Beginning":
                                                target_van['address_order'] = [p_addr] + target_van['address_order']
                                            else:
                                                target_van['address_order'].append(p_addr)
                                        st.success("Passenger moved.")
                                        st.experimental_rerun()

                            # Wheelchair vans quick move
                            for idx_v, van in enumerate(st.session_state.get('wheelchair_vans_assignments', [])):
                                with st.container():
                                    st.caption(f"Move from Van {van.get('vehicle_id', 0) + 1} (Wheelchair)")
                                    options = [f"{nm} — {addr}" for nm, addr in list_passengers(van)]
                                    if not options:
                                        continue
                                    sel = st.selectbox("Passenger", options=options, key=f"wc_move_sel_{idx_v}")
                                    target_section = st.selectbox("To section", options=["Regular", "Wheelchair"], key=f"wc_move_sec_{idx_v}")
                                    if target_section == "Regular":
                                        tgt_bucket = 'regular_vans_assignments'
                                        tgt_vans = st.session_state.get(tgt_bucket, [])
                                    else:
                                        tgt_bucket = 'wheelchair_vans_assignments'
                                        tgt_vans = st.session_state.get(tgt_bucket, [])
                                    tgt_indices = [v.get('vehicle_id', 0) + 1 for v in tgt_vans]
                                    tgt_choice = st.selectbox("To van #", options=tgt_indices or [1], key=f"wc_move_tgt_{idx_v}")
                                    insert_pos = st.selectbox("Insert position", options=["Beginning", "End"], key=f"wc_move_pos_{idx_v}")
                                    if st.button("Move", key=f"wc_move_btn_{idx_v}"):
                                        sel_name = sel.split(" — ")[0].strip()
                                        sel_addr = sel.split(" — ")[1].strip()
                                        # Remove from source
                                        if sel_addr in van['addr_to_passengers'] and sel_name in van['addr_to_passengers'][sel_addr]:
                                            van['addr_to_passengers'][sel_addr].remove(sel_name)
                                            if not van['addr_to_passengers'][sel_addr]:
                                                van['addr_to_passengers'].pop(sel_addr, None)
                                                van['address_order'] = [a for a in van['address_order'] if a != sel_addr]
                                        # Determine target van
                                        target_van = None
                                        for v in tgt_vans:
                                            if v.get('vehicle_id', 0) + 1 == tgt_choice:
                                                target_van = v
                                                break
                                        if not target_van:
                                            st.error("Invalid target van")
                                            st.experimental_rerun()
                                        # Constraints
                                        info = name_to_info.get(sel_name, {"address": None, "is_wheelchair": False})
                                        p_is_wc = bool(info.get('is_wheelchair', False))
                                        if tgt_bucket == 'regular_vans_assignments' and p_is_wc:
                                            st.warning("Cannot move a wheelchair passenger into a regular van.")
                                            st.experimental_rerun()
                                        if tgt_bucket == 'wheelchair_vans_assignments':
                                            cnt_regular = 0
                                            for names in target_van['addr_to_passengers'].values():
                                                for nm in names:
                                                    if not name_to_info.get(nm, {}).get('is_wheelchair', False):
                                                        cnt_regular += 1
                                            if not p_is_wc and cnt_regular >= 1:
                                                st.warning("Wheelchair van can carry at most 1 regular passenger.")
                                                st.experimental_rerun()
                                        # Add to target
                                        p_addr = info.get('address')
                                        if p_addr in target_van['addr_to_passengers']:
                                            target_van['addr_to_passengers'][p_addr].append(sel_name)
                                        else:
                                            target_van['addr_to_passengers'][p_addr] = [sel_name]
                                            if insert_pos == "Beginning":
                                                target_van['address_order'] = [p_addr] + target_van['address_order']
                                            else:
                                                target_van['address_order'].append(p_addr)
                                        st.success("Passenger moved.")
                                        st.experimental_rerun()
        except Exception as e:
            st.error(f" Failed to read or process master list: {str(e)}")

if __name__ == "__main__":
    main()
