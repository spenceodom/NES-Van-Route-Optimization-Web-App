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
        # Number of vans
        number_of_vans = st.slider(
            "Number of Vans",
            min_value=1,
            max_value=8,
            value=2,
            help="How many vans are available for this route?"
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
        st.subheader("📄 Sample Template")
        sample_csv = (
            "stop_id,address,passenger_name,time_window_start,time_window_end,passengers,notes\n"
            "1,123 Main St, Anytown, CA 90210,John Smith,08:00,08:30,1,Regular pickup\n"
            "2,456 Oak Ave, Anytown, CA 90210,Jane Doe,08:15,08:45,2,Wheelchair accessible\n"
            "3,789 Pine St, Anytown, CA 90210,Bob Johnson,08:30,09:00,1,\n"
            "4,321 Elm St, Anytown, CA 90210,Alice Brown,08:45,09:15,1,\n"
            "5,654 Maple Dr, Anytown, CA 90210,Charlie Wilson,09:00,09:30,3,Family pickup\n"
        )
        st.download_button(
            label="Download Sample CSV",
            data=sample_csv,
            file_name="route_template.csv",
            mime="text/csv",
            help="Download a sample CSV file to see the required format"
        )

    st.header("Upload and Optimize Route")
    uploaded_file = st.file_uploader(
        "Choose a CSV file",
        type=['csv'],
        help="Upload a CSV file with your stops (max 50 stops, 200KB)"
    )
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            st.success(f"✅ Successfully loaded {len(df)} stops")
            st.dataframe(df, use_container_width=True)
            # Convert DataFrame rows to StopModel objects
            stops = [StopModel(**row) for row in df.to_dict(orient='records')]
            if st.button("🚀 Optimize Route"):
                with st.spinner("Optimizing route..."):
                    optimizer = RouteOptimizer(depot_address, number_of_vans)
                    result = optimizer.optimize_route(stops, start_time)
                    if result['is_feasible']:
                        st.success(f"✅ Route optimized! Total distance: {result['total_distance']:.2f}")
                        st.write("Optimized stop order (by index):", result['route_sequence'])
                    else:
                        st.error("❌ No feasible route found.")
        except Exception as e:
            st.error(f"❌ Failed to read or process CSV: {str(e)}")

if __name__ == "__main__":
    main() 