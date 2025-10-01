# NES Van Route Optimization Web App

A Streamlit-based tool to optimize daily van routes for NES, reducing planning time and mileage.

## Features
- Upload CSV master list (name, address, wheelchair)
- Real address geocoding via Google Maps (with 24h cache in-memory per session)
- Route optimization across multiple vans with capacity constraints (OR-Tools)
- Wheelchair van handling: all wheelchair riders + up to 1 regular rider
- Results per-van with distance and duration totals
- Sample CSV templates in `sample_data/`

## Setup

1. Clone this repo or copy the project files.
2. (Recommended) Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the app:
   ```bash
   streamlit run app.py
   ```

## Sample Data
- Master list: `sample_data/master_list_template.csv` (name, full address, wheelchair Y/N)
- Alternative stop-based: `sample_data/route_template.csv`

## Next Steps
- Add XLSX/PDF export of optimized routes
- Add Redis cache for 24h geocode/distance matrices
- Add optional map visualization