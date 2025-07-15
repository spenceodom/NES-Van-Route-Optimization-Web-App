import pandas as pd
from src.models.route_models import StopModel

class CSVProcessor:
    REQUIRED_COLUMNS = [
        'stop_id', 'address', 'passenger_name',
        'time_window_start', 'time_window_end', 'passengers'
    ]
    MAX_ROWS = 50
    MAX_FILE_SIZE = 200 * 1024  # 200 KB

    def validate_and_process_csv(self, uploaded_file):
        if uploaded_file.size > self.MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds {self.MAX_FILE_SIZE // 1024} KB limit.")
        df = pd.read_csv(uploaded_file)
        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")
        if len(df) > self.MAX_ROWS:
            raise ValueError(f"File contains {len(df)} rows, max allowed is {self.MAX_ROWS}.")
        stops = [StopModel(**row) for row in df.to_dict(orient='records')]
        return stops 