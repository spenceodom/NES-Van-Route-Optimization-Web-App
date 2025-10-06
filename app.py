import streamlit as st
import os
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

def main():
    st.title("NES Van Route Optimizer")
    st.markdown("Optimize daily van routes to save time, fuel, and ensure on-time pickups")

    # Optional admin gate controlled by APP_PASSWORD in secrets/env
    required_password = None
    try:
        required_password = st.secrets.get("APP_PASSWORD")  # type: ignore[attr-defined]
    except Exception:
        required_password = None
    if not required_password:
        required_password = os.getenv("APP_PASSWORD")

    if required_password:
        with st.sidebar:
            st.markdown("**Admin Access**")
            if not st.session_state.get("authed", False):
                pwd = st.text_input("Admin password", type="password", key="admin_pw")
                if pwd:
                    if pwd == required_password:
                        st.session_state["authed"] = True
                        st.success("Access granted")
                    else:
                        st.error("Incorrect password")
            if not st.session_state.get("authed", False):
                st.stop()

    # API Key Configuration
    with st.sidebar:
        # Depot address selection (radio buttons)
        st.markdown("**Depot Address**")
        depot_option = st.radio(
            "Select Depot Address",
            ("Day Program", "Other"),
            index=0
        )
        if depot_option == "Day Program":
            depot_address = "10404 1055 W, South Jordan, UT 84095"
            st.info(f"Depot address set to: {depot_address}")
        else:
            depot_address = st.text_input(
                "Enter Depot Address",
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
        # Route Start Time (AM/PM dropdowns)
        st.markdown("**Route Start Time**")
        hour = st.selectbox("Hour", list(range(1, 13)), index=7)
        minute = st.selectbox("Minute", ["00", "15", "30", "45"], index=0)
        am_pm = st.selectbox("AM/PM", ["AM", "PM"], index=0)
        hour_24 = hour % 12 if am_pm == "AM" else (hour % 12) + 12
        start_time = time(hour_24, int(minute))
        st.caption(f"Selected start time: {hour}:{minute} {am_pm}")
        st.divider()

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
                checked = st.session_state.get(f"name_{idx}", False)
                if col.checkbox(name, key=f"name_{idx}", value=checked):
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
                
                st.info(f" **Passenger Summary:**")
                if wheelchair_count > 0:
                    st.info(f" Wheelchair van: {wheelchair_count} passengers ({len(wheelchair_stops)} stops)")
                if regular_count > 0:
                    st.info(f" Regular vans: {regular_count} passengers ({len(regular_stops)} stops, {min_vans_needed} vans needed)")
                
                if wheelchair_van_regular_passenger:
                    st.info(f"Note: 1 regular passenger ({wheelchair_van_regular_passenger}) will ride in the wheelchair van to maximize efficiency")

                # Optimize button
                if st.button(" Optimize Routes", disabled=not api_key):
                    if not api_key:
                        st.error(" Please configure Google Maps API key first")
                        return

                    with st.spinner(" Optimizing routes with real-time traffic data..."):
                        try:
                            # Initialize optimizer with API key
                            optimizer_regular = RouteOptimizer(depot_address, MAX_VAN_CAPACITY, api_key)

                            # Optimize regular routes
                            if regular_stops:
                                st.subheader("Regular Van Routes")
                                regular_result = optimizer_regular.optimize_route(regular_stops, start_time, number_of_vans)

                                if regular_result['geocoding_errors']:
                                    st.warning(" Some addresses could not be geocoded:")
                                    for error in regular_result['geocoding_errors']:
                                        st.write(f" {error}")

                                if not regular_result['is_feasible']:
                                    st.error(" Could not find feasible routes for regular passengers")
                                else:
                                    # Display optimized routes
                                    total_distance = 0
                                    total_duration = 0
                                    for route in regular_result['vehicle_routes']:
                                        if route['stops']:  # Only show routes with stops
                                            st.markdown(f"**Van {route['vehicle_id'] + 1}:**")
                                            duration_text = format_duration(route.get('duration', 0)) if 'duration' in route else "—"
                                            st.write(f" Distance: {format_distance(route['distance'])} | Duration: {duration_text} | Passengers: {route['load']}")

                                            # Show stops in route order
                                            for stop_idx in route['stops']:
                                                if 0 <= stop_idx - 1 < len(regular_stops):  # Convert back to 0-based index
                                                    stop = regular_stops[stop_idx - 1]  # -1 because depot is index 0
                                                    st.write(f"   {stop.address}: {len(stop.passengers)} passengers - {', '.join(stop.passengers)}")

                                            total_distance += route['distance']
                                            if 'duration' in route:
                                                total_duration += route['duration']

                                    if total_distance > 0:
                                        if total_duration > 0:
                                            st.info(f" Total regular distance: {format_distance(total_distance)} | Total duration: {format_duration(total_duration)}")
                                        else:
                                            st.info(f" Total regular van distance: {format_distance(total_distance)}")

                            # Handle wheelchair routes (separate optimization)
                            if wheelchair_stops:
                                st.subheader("Wheelchair Van Route")
                                # For wheelchair van, allow all wheelchair passengers plus at most 1 regular passenger
                                wc_capacity = sum(len(s.passengers) for s in wheelchair_stops)
                                optimizer_wheelchair = RouteOptimizer(depot_address, max(1, wc_capacity), api_key)
                                wheelchair_result = optimizer_wheelchair.optimize_route(wheelchair_stops, start_time, 1)

                                if wheelchair_result['geocoding_errors']:
                                    for error in wheelchair_result['geocoding_errors']:
                                        st.warning(f"Wheelchair geocoding error: {error}")

                                if wheelchair_result['is_feasible'] and wheelchair_result['vehicle_routes']:
                                    route = wheelchair_result['vehicle_routes'][0]
                                    duration_text = format_duration(route.get('duration', 0)) if 'duration' in route else "—"
                                    st.write(f" Distance: {format_distance(route['distance'])} | Duration: {duration_text} | Passengers: {route['load']}")
                                    
                                    if wheelchair_van_regular_passenger:
                                        st.info(f"? This route includes 1 regular passenger ({wheelchair_van_regular_passenger}) along with wheelchair passengers")

                                    for stop_idx in route['stops']:
                                        if 0 <= stop_idx - 1 < len(wheelchair_stops):
                                            stop = wheelchair_stops[stop_idx - 1]
                                            passenger_type = " wheelchair" if stop.wheelchair else " regular"
                                            st.write(f"   {stop.address}: {len(stop.passengers)} passengers ({passenger_type}) - {', '.join(stop.passengers)}")
                                else:
                                    st.write("No wheelchair passengers selected.")
                            else:
                                st.subheader("Wheelchair Van Route")
                                st.write("No wheelchair passengers selected.")

                        except ValueError as ve:
                            st.error(f" Configuration Error: {str(ve)}")
                        except Exception as e:
                            st.error(f" Optimization failed: {str(e)}")
                            st.info(" Make sure your Google Maps API key is valid and has the required permissions")
        except Exception as e:
            st.error(f" Failed to read or process master list: {str(e)}")

if __name__ == "__main__":
    main()
