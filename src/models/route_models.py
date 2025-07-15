from typing import List, Optional
from datetime import time, datetime
from pydantic import BaseModel, Field

class IndividualModel(BaseModel):
    name: str
    address: str
    wheelchair: bool

class StopModel(BaseModel):
    address: str
    passengers: List[str]  # List of names
    wheelchair: bool = False

class RouteRequest(BaseModel):
    stops: List[StopModel]
    depot_address: str
    number_of_vans: int = 2
    start_time: time = time(8, 0)

class RouteResponse(BaseModel):
    stops: List[StopModel]
    total_distance: float
    total_time: int
    route_sequence: List[int]
    etas: List[datetime]
    is_feasible: bool
    optimization_time: float 