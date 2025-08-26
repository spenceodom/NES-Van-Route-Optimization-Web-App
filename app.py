import streamlit as st
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
    if meters >= 1000:
        return ".1f"
    else:
        return f"{meters}m"

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
    st.title(" NES Van Route Optimizer")
    st.markdown("Optimize daily van routes to save time, fuel, and ensure on-time pickups")

    # API Key Configuration
    with st.sidebar:
        st.header("Configuration")
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

        # API Key input
        st.markdown("**Google Maps API Configuration**")
        api_key = st.text_input(
            "Google Maps API Key",
            type="password",
            help="Enter your Google Maps API key for geocoding and distance calculations"
        )
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
            cols = st.columns(3)
            selected_names = []
            for idx, name in enumerate(all_names):
                col = cols[idx % 3]
                if col.checkbox(name, key=f"name_{idx}"):
                    selected_names.append(name)
            if selected_names:
                selected_df = master_df[master_df['name'].isin(selected_names)].copy()
                # Prepare for optimization: split into wheelchair and regular
                selected_df['is_wheelchair'] = selected_df['wheelchair'].apply(is_wheelchair)
                wheelchair_df = selected_df[selected_df['is_wheelchair']]
                regular_df = selected_df[~selected_df['is_wheelchair']]
                # Group regular passengers by address
                grouped = regular_df.groupby('address')['name'].apply(list).reset_index()
                stops = []
                for _, row in grouped.iterrows():
                    stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=False))
                # Check if any stop exceeds van capacity
                over_capacity = [s for s in stops if len(s.passengers) > MAX_VAN_CAPACITY]
                if over_capacity:
                    st.error(f" One or more stops have more than {MAX_VAN_CAPACITY} passengers. Please adjust your selection.")
                    for s in over_capacity:
                        st.warning(f"Address: {s.address} has {len(s.passengers)} passengers.")
                    return
                # Check if total demand can be met with available vans
                total_passengers = sum(len(s.passengers) for s in stops)
                min_vans_needed = (total_passengers + MAX_VAN_CAPACITY - 1) // MAX_VAN_CAPACITY
                if min_vans_needed > number_of_vans:
                    st.error(f" Not enough vans. {min_vans_needed} vans needed for {total_passengers} passengers (max {MAX_VAN_CAPACITY} per van), but only {number_of_vans} vans available.")
                    return
                # Prepare wheelchair stops
                wheelchair_stops = []
                if not wheelchair_df.empty:
                    wc_grouped = wheelchair_df.groupby('address')['name'].apply(list).reset_index()
                    for _, row in wc_grouped.iterrows():
                        wheelchair_stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=True))
                # Optimize button
                if st.button(" Optimize Routes", disabled=not api_key):
                    if not api_key:
                        st.error(" Please configure Google Maps API key first")
                        return

                    with st.spinner(" Optimizing routes with real-time traffic data..."):
                        try:
                            # Initialize optimizer with API key
                            optimizer = RouteOptimizer(depot_address, MAX_VAN_CAPACITY, api_key)

                            # Optimize regular routes
                            if stops:
                                st.subheader("Regular Van Routes")
                                regular_result = optimizer.optimize_route(stops, start_time, number_of_vans)

                                if regular_result['geocoding_errors']:
                                    st.warning(" Some addresses could not be geocoded:")
                                    for error in regular_result['geocoding_errors']:
                                        st.write(f" {error}")

                                if not regular_result['is_feasible']:
                                    st.error(" Could not find feasible routes for regular passengers")
                                else:
                                    # Display optimized routes
                                    total_distance = 0
                                    for route in regular_result['vehicle_routes']:
                                        if route['stops']:  # Only show routes with stops
                                            st.markdown(f"**Van {route['vehicle_id'] + 1}:**")
                                            st.write(f" Distance: {format_distance(route['distance'])} |  Passengers: {route['load']}")

                                            # Show stops in route order
                                            for stop_idx in route['stops']:
                                                if 0 <= stop_idx - 1 < len(stops):  # Convert back to 0-based index
                                                    stop = stops[stop_idx - 1]  # -1 because depot is index 0
                                                    st.write(f"   {stop.address}: {len(stop.passengers)} passengers - {', '.join(stop.passengers)}")

                                            total_distance += route['distance']

                                    if total_distance > 0:
                                        st.info(f" Total regular van distance: {format_distance(total_distance)}")

                            # Handle wheelchair routes (separate optimization)
                            if wheelchair_stops:
                                st.subheader("Wheelchair Van Route")
                                # For wheelchair, we use a single vehicle for now
                                wheelchair_result = optimizer.optimize_route(wheelchair_stops, start_time, 1)

                                if wheelchair_result['geocoding_errors']:
                                    for error in wheelchair_result['geocoding_errors']:
                                        st.warning(f"Wheelchair geocoding error: {error}")

                                if wheelchair_result['is_feasible'] and wheelchair_result['vehicle_routes']:
                                    route = wheelchair_result['vehicle_routes'][0]
                                    st.write(f" Distance: {format_distance(route['distance'])} |  Passengers: {route['load']}")

                                    for stop_idx in route['stops']:
                                        if 0 <= stop_idx - 1 < len(wheelchair_stops):
                                            stop = wheelchair_stops[stop_idx - 1]
                                            st.write(f"   {stop.address}: {len(stop.passengers)} passengers - {', '.join(stop.passengers)}")
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
