import streamlit as st
import pandas as pd
from datetime import time
from src.models.route_models import StopModel
from src.optimization.route_optimizer import RouteOptimizer

st.set_page_config(
    page_title="NES Van Route Optimizer",
    page_icon="🚐",
    layout="wide",
    initial_sidebar_state="expanded"
)

MAX_VAN_CAPACITY = 10


def main():
    st.title("🚐 NES Van Route Optimizer")
    st.markdown("Optimize daily van routes to save time, fuel, and ensure on-time pickups")

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
            st.success(f"✅ Loaded {len(master_df)} individuals from master list.")
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
                wheelchair_df = selected_df[selected_df['wheelchair'].astype(str).str.upper() == 'Y']
                regular_df = selected_df[selected_df['wheelchair'].astype(str).str.upper() != 'Y']
                # Group regular passengers by address
                grouped = regular_df.groupby('address')['name'].apply(list).reset_index()
                stops = []
                for _, row in grouped.iterrows():
                    stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=False))
                # Check if any stop exceeds van capacity
                over_capacity = [s for s in stops if len(s.passengers) > MAX_VAN_CAPACITY]
                if over_capacity:
                    st.error(f"❌ One or more stops have more than {MAX_VAN_CAPACITY} passengers. Please adjust your selection.")
                    for s in over_capacity:
                        st.warning(f"Address: {s.address} has {len(s.passengers)} passengers.")
                    return
                # Check if total demand can be met with available vans
                total_passengers = sum(len(s.passengers) for s in stops)
                min_vans_needed = (total_passengers + MAX_VAN_CAPACITY - 1) // MAX_VAN_CAPACITY
                if min_vans_needed > number_of_vans:
                    st.error(f"❌ Not enough vans. {min_vans_needed} vans needed for {total_passengers} passengers (max {MAX_VAN_CAPACITY} per van), but only {number_of_vans} vans available.")
                    return
                # Prepare wheelchair stops
                wheelchair_stops = []
                if not wheelchair_df.empty:
                    wc_grouped = wheelchair_df.groupby('address')['name'].apply(list).reset_index()
                    for _, row in wc_grouped.iterrows():
                        wheelchair_stops.append(StopModel(address=row['address'], passengers=row['name'], wheelchair=True))
                # Optimize button
                if st.button("🚀 Optimize Routes"):
                    # Assign regular stops to vans (simple round-robin for now)
                    van_routes = [[] for _ in range(number_of_vans)]
                    stop_idx = 0
                    for stop in stops:
                        van_routes[stop_idx % number_of_vans].append(stop)
                        stop_idx += 1
                    st.subheader("Regular Van Routes")
                    for i, route in enumerate(van_routes):
                        st.markdown(f"**Van {i+1}:**")
                        if not route:
                            st.write("No stops assigned.")
                        for s in route:
                            st.write(f"{s.address}: {len(s.passengers)} passengers - {', '.join(s.passengers)}")
                    st.subheader("Wheelchair Van Route")
                    if wheelchair_stops:
                        for s in wheelchair_stops:
                            st.write(f"{s.address}: {len(s.passengers)} passengers - {', '.join(s.passengers)}")
                    else:
                        st.write("No wheelchair passengers selected.")
        except Exception as e:
            st.error(f"❌ Failed to read or process master list: {str(e)}")

if __name__ == "__main__":
    main() 