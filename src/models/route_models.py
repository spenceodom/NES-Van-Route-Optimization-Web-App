from typing import List, Optional
from datetime import time, datetime
from pydantic import BaseModel, Field

class StopModel(BaseModel):
    stop_id: str
    address: str
    passenger_name: str
    time_window_start: time
    time_window_end: time
    passengers: int
    notes: Optional[str] = ""

class RouteRequest(BaseModel):
    stops: List[StopModel]
    depot_address: str
    vehicle_capacity: int = 15
    start_time: time = time(8, 0)

class RouteResponse(BaseModel):
    stops: List[StopModel]
    total_distance: float
    total_time: int
    route_sequence: List[int]
    etas: List[datetime]
    is_feasible: bool
    optimization_time: float 