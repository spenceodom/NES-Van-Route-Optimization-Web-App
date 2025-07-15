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
        st.subheader("📄 Master List Template")
        master_list_csv = (
            "name,address,wheelchair\n"
            "John Smith,123 Main St, Anytown, CA 90210,N\n"
            "Jane Doe,456 Oak Ave, Anytown, CA 90210,N\n"
            "Bob Johnson,789 Pine St, Anytown, CA 90210,Y\n"
            "Alice Brown,321 Elm St, Anytown, CA 90210,N\n"
            "Charlie Wilson,654 Maple Dr, Anytown, CA 90210,N\n"
            "Sam Lee,1000 Apartment Complex, Anytown, CA 90210,Y\n"
            "Chris Kim,1000 Apartment Complex, Anytown, CA 90210,N\n"
            "Pat Taylor,1000 Apartment Complex, Anytown, CA 90210,N\n"
        )
        st.download_button(
            label="Download Master List Template",
            data=master_list_csv,
            file_name="master_list_template.csv",
            mime="text/csv",
            help="Download a sample master list CSV file."
        )

    st.header("Step 1: Upload Master List")
    master_file = st.file_uploader(
        "Upload Master List CSV (name, address, wheelchair)",
        type=['csv'],
        help="Upload a CSV with all individuals, their addresses, and wheelchair status."
    )
    if master_file is not None:
        try:
            master_df = pd.read_csv(master_file)
            st.success(f"✅ Loaded {len(master_df)} individuals from master list.")
            st.dataframe(master_df, use_container_width=True)
            # Step 2: Select individuals for today
            st.header("Step 2: Select Individuals for Transport Today")
            all_names = master_df['name'].tolist()
            selected_names = st.multiselect(
                "Select individuals needing transport:",
                options=all_names
            )
            if selected_names:
                selected_df = master_df[master_df['name'].isin(selected_names)].copy()
                st.write(f"You selected {len(selected_df)} individuals.")
                st.dataframe(selected_df, use_container_width=True)
                # Prepare for optimization: split into wheelchair and regular
                wheelchair_df = selected_df[selected_df['wheelchair'].astype(str).str.upper() == 'Y']
                regular_df = selected_df[selected_df['wheelchair'].astype(str).str.upper() != 'Y']
                st.write(f"Wheelchair van: {len(wheelchair_df)} passengers.")
                st.write(f"Regular vans: {len(regular_df)} passengers.")
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
                    st.info("Route optimization logic will be implemented next. (Stops and grouping are ready.)")
                    st.write("Regular van stops:")
                    for s in stops:
                        st.write(f"{s.address}: {len(s.passengers)} passengers - {', '.join(s.passengers)}")
                    st.write("Wheelchair van stops:")
                    for s in wheelchair_stops:
                        st.write(f"{s.address}: {len(s.passengers)} passengers - {', '.join(s.passengers)}")
                    # Placeholder for XLSX export
                    st.info("XLSX export for both routes will be implemented next.")
        except Exception as e:
            st.error(f"❌ Failed to read or process master list: {str(e)}")

if __name__ == "__main__":
    main() 