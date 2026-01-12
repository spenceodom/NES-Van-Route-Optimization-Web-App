"""
NES Van Route Optimization Engine
Real OR-Tools TSP/VRP implementation with Google Maps API integration
"""

import logging
import os
import requests
from typing import List, Optional, Tuple, Dict, Any
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from src.models.route_models import StopModel

logger = logging.getLogger(__name__)

class RouteOptimizer:
    """Main optimization engine using OR-Tools with Google Maps API"""

    class GoogleMapsService:
        """
        Google Maps Service for geocoding and distance matrix calculation.
        This class is embedded directly into RouteOptimizer to avoid external dependency issues.
        """
        def __init__(self, api_key: Optional[str] = None):
            """
            Initialize the Google Maps service.

            Args:
                api_key: Google Maps API key (optional, will use env var if not provided)
            """
            self.api_key = (api_key or os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
            if not self.api_key:
                raise ValueError("Google Maps API key not provided. Please set GOOGLE_MAPS_API_KEY environment variable or secrets.")
            # Basic sanitation to avoid hidden control chars
            if any((ord(c) < 32) for c in self.api_key):
                raise ValueError("Google Maps API key contains invalid characters. Paste a clean plain-text key.")

            self.base_url = "https://maps.googleapis.com/maps/api/geocode/json"
            self.distance_matrix_url = "https://maps.googleapis.com/maps/api/distancematrix/json"

        def geocode_address(self, address: str) -> Tuple[float, float]:
            """
            Geocode a single address.

            Args:
                address: The address to geocode.

            Returns:
                Tuple of (latitude, longitude).

            Raises:
                ValueError: If geocoding fails or returns no results.
            """
            params = {
                "address": address,
                "key": self.api_key
            }
            # Retry transient server errors and network hiccups
            last_err: Optional[Exception] = None
            for attempt in range(3):
                try:
                    resp = requests.get(self.base_url, params=params, timeout=15)
                    # Retry on 5xx without parsing body
                    if 500 <= resp.status_code < 600:
                        last_err = ValueError(f"Geocode server error (status {resp.status_code})")
                        continue

                    data = resp.json()
                    status = data.get("status")
                    if status != "OK":
                        err_msg = data.get("error_message") or status or "Unknown error"
                        raise ValueError(f"Geocoding failed: {err_msg}")

                    results = data.get("results") or []
                    if not results:
                        raise ValueError(f"No results found for address: {address}")

                    location = results[0].get("geometry", {}).get("location")
                    if not location:
                        raise ValueError(f"Location not found in results for address: {address}")

                    lat = location["lat"]
                    lng = location["lng"]
                    return (lat, lng)
                except requests.exceptions.RequestException as e:
                    # Network/timeout errors -> retry
                    last_err = e
                    continue
            # If we exhausted retries
            raise ValueError(f"Failed to geocode address '{address}': {last_err}")

        def geocode_addresses(self, addresses: List[str]) -> List[Optional[Tuple[float, float]]]:
            """
            Geocode multiple addresses.

            Args:
                addresses: List of addresses to geocode.

            Returns:
                List of tuples (latitude, longitude) or None if geocoding fails.
            """
            geocoded_coords = []
            for address in addresses:
                try:
                    coords = self.geocode_address(address)
                    geocoded_coords.append(coords)
                except ValueError as e:
                    logger.warning(f"Could not geocode address '{address}': {e}")
                    geocoded_coords.append(None)
            return geocoded_coords

        def get_route_optimization_matrix(
            self,
            depot_coords: Tuple[float, float],
            stop_coords: List[Tuple[float, float]]
        ) -> Tuple[List[List[Optional[int]]], List[List[Optional[int]]]]:
            """
            Get distance and duration matrices from Google Maps Distance Matrix API.

            Args:
                depot_coords: Coordinates of the depot (latitude, longitude).
                stop_coords: List of coordinates for stops (latitude, longitude).

            Returns:
                Tuple of (distance_matrix, duration_matrix).
            """
            # Build full [depot + stops] x [depot + stops] matrices via chunked HTTP calls
            all_coords: List[Tuple[float, float]] = [depot_coords] + stop_coords
            return self.get_distance_matrix(all_coords, all_coords)

        def get_distance_matrix(
            self,
            origins: List[Tuple[float, float]],
            destinations: List[Tuple[float, float]],
            departure_time: Optional[str] = None
        ) -> Tuple[List[List[Optional[int]]], List[List[Optional[int]]]]:
            try:
                num_origins = len(origins)
                num_destinations = len(destinations)

                distance_matrix: List[List[Optional[int]]] = [
                    [None for _ in range(num_destinations)] for _ in range(num_origins)
                ]
                duration_matrix: List[List[Optional[int]]] = [
                    [None for _ in range(num_destinations)] for _ in range(num_origins)
                ]

                max_elements = 100
                rows_chunk = min(num_origins, 25)
                cols_chunk = max(1, min(num_destinations, max_elements // max(1, rows_chunk)))
                if rows_chunk * cols_chunk > max_elements:
                    cols_chunk = max_elements // rows_chunk
                    cols_chunk = max(1, cols_chunk)

                for row_start in range(0, num_origins, rows_chunk):
                    row_end = min(num_origins, row_start + rows_chunk)
                    origin_block = origins[row_start:row_end]
                    origin_strs = [f"{lat},{lng}" for lat, lng in origin_block]

                    for col_start in range(0, num_destinations, cols_chunk):
                        col_end = min(num_destinations, col_start + cols_chunk)
                        dest_block = destinations[col_start:col_end]
                        dest_strs = [f"{lat},{lng}" for lat, lng in dest_block]

                        params: Dict[str, Any] = {
                            "origins": "|".join(origin_strs),
                            "destinations": "|".join(dest_strs),
                            "mode": "driving",
                            "units": "imperial",
                            "key": self.api_key,
                        }
                        if departure_time:
                            params["departure_time"] = departure_time

                        resp = requests.get(self.distance_matrix_url, params=params, timeout=30)
                        resp.raise_for_status()
                        result = resp.json()
                        if result.get("status") != "OK":
                            raise ValueError(f"Distance Matrix API returned status: {result.get('status')} {result.get('error_message','')}")

                        for i_row, row in enumerate(result.get("rows", [])):
                            elements = row.get("elements", [])
                            for j_col, element in enumerate(elements):
                                if element.get("status") == "OK":
                                    distance_matrix[row_start + i_row][col_start + j_col] = element["distance"]["value"]
                                    duration_matrix[row_start + i_row][col_start + j_col] = element["duration"]["value"]
                                else:
                                    distance_matrix[row_start + i_row][col_start + j_col] = None
                                    duration_matrix[row_start + i_row][col_start + j_col] = None

                return distance_matrix, duration_matrix
            except Exception as e:
                logger.error(f"Failed to get distance matrix: {e}")
                raise ValueError(f"Failed to get distance matrix: {e}")

    def __init__(self, depot_address: str, vehicle_capacity: int = 15, api_key: Optional[str] = None):
        """
        Initialize the route optimizer

        Args:
            depot_address: Address of the depot/starting point
            vehicle_capacity: Maximum capacity per vehicle
            api_key: Google Maps API key (optional, will use env var if not provided)
        """
        self.depot_address = depot_address
        self.vehicle_capacity = vehicle_capacity
        self.gmaps_service = self.GoogleMapsService(api_key)

    def optimize_route(
        self,
        stops: List[StopModel],
        start_time,
        num_vehicles: int = 1,
        max_regular_non_wheelchair: Optional[int] = None,
        vehicle_capacities: Optional[List[int]] = None,
        regular_non_wheelchair_capacities: Optional[List[int]] = None,
        wheelchair_capacities: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Optimize routes for multiple vehicles using real addresses and Google Maps

        Args:
            stops: List of StopModel objects with address information
            start_time: Route start time (for future time window implementation)
            num_vehicles: Number of vehicles to use

        Returns:
            Dictionary with optimization results
        """
        try:
            if not stops:
                return {
                    'route_sequence': [],
                    'total_distance': 0,
                    'is_feasible': True,
                    'vehicle_routes': [],
                    'geocoding_errors': []
                }

            # Step 1: Geocode all addresses
            addresses = [stop.address for stop in stops]
            depot_coords, stop_coords, geocoding_errors = self._geocode_all_addresses(addresses)

            if not depot_coords:
                raise ValueError("Could not geocode depot address")

            # Filter out stops that couldn't be geocoded
            valid_stops = []
            valid_coords = []
            for i, (stop, coord) in enumerate(zip(stops, stop_coords)):
                if coord is not None:
                    valid_stops.append(stop)
                    valid_coords.append(coord)
                else:
                    geocoding_errors.append(f"Stop {i+1}: {stop.address}")

            if not valid_stops:
                raise ValueError("Could not geocode any stop addresses")

            logger.info(f"Successfully geocoded {len(valid_stops)} out of {len(stops)} stops")

            # Step 2: Get distance matrix from Google Maps
            distance_matrix, duration_matrix = self.gmaps_service.get_route_optimization_matrix(
                depot_coords, valid_coords
            )

            # Step 3: Run optimization
            has_per_vehicle_caps = any([
                vehicle_capacities is not None,
                regular_non_wheelchair_capacities is not None,
                wheelchair_capacities is not None,
            ])
            if num_vehicles == 1 and not has_per_vehicle_caps:
                # Single vehicle - use TSP
                result = self._optimize_single_vehicle(
                    distance_matrix,
                    duration_matrix,
                    valid_stops,
                    max_regular_non_wheelchair=max_regular_non_wheelchair
                )
            else:
                # Multiple vehicles - use VRP
                result = self._optimize_multi_vehicle(
                    distance_matrix,
                    duration_matrix,
                    valid_stops,
                    num_vehicles,
                    max_regular_non_wheelchair=max_regular_non_wheelchair,
                    vehicle_capacities=vehicle_capacities,
                    regular_non_wheelchair_capacities=regular_non_wheelchair_capacities,
                    wheelchair_capacities=wheelchair_capacities
                )

            # Add geocoding errors to result
            result['geocoding_errors'] = geocoding_errors
            return result

        except Exception as e:
            logger.error(f"Route optimization failed: {e}")
            return {
                'route_sequence': [],
                'total_distance': 0,
                'is_feasible': False,
                'vehicle_routes': [],
                'geocoding_errors': [str(e)]
            }

    def _geocode_all_addresses(self, stop_addresses: List[str]) -> Tuple[Optional[Tuple[float, float]], List[Optional[Tuple[float, float]]], List[str]]:
        """
        Geocode depot and all stop addresses

        Returns:
            Tuple of (depot_coords, stop_coords_list, error_messages)
        """
        geocoding_errors = []

        # Geocode depot
        try:
            depot_coords = self.gmaps_service.geocode_address(self.depot_address)
        except ValueError as e:
            logger.error(f"Failed to geocode depot: {e}")
            depot_coords = None
            geocoding_errors.append(f"Depot: {self.depot_address} - {e}")

        # Geocode stops
        stop_coords = self.gmaps_service.geocode_addresses(stop_addresses)

        return depot_coords, stop_coords, geocoding_errors

    def _optimize_single_vehicle(
        self,
        distance_matrix: List[List[Optional[int]]],
        duration_matrix: List[List[Optional[int]]],
        stops: List[StopModel],
        max_regular_non_wheelchair: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Optimize route for single vehicle (TSP)
        """
        try:
            n = len(stops) + 1  # +1 for depot
            manager = pywrapcp.RoutingIndexManager(n, 1, 0)
            routing = pywrapcp.RoutingModel(manager)

            # Use duration as the optimization cost while still tracking distance
            def duration_cost_callback(from_index, to_index):
                from_node = manager.IndexToNode(from_index)
                to_node = manager.IndexToNode(to_index)

                # Handle None values in duration matrix
                duration = duration_matrix[from_node][to_node]
                if duration is None:
                    return 10**9  # Large penalty for unreachable locations
                return int(duration)

            transit_callback_index = routing.RegisterTransitCallback(duration_cost_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

            # Optionally add a capacity dimension to limit non-wheelchair passengers (e.g., front seat only)
            if max_regular_non_wheelchair is not None:
                def regular_demand_callback(from_index):
                    from_node = manager.IndexToNode(from_index)
                    if from_node == 0:
                        return 0
                    stop = stops[from_node - 1]
                    return 0 if stop.wheelchair else len(stop.passengers)

                regular_demand_index = routing.RegisterUnaryTransitCallback(regular_demand_callback)
                routing.AddDimensionWithVehicleCapacity(
                    regular_demand_index,
                    0,
                    [max_regular_non_wheelchair],
                    True,
                    'RegularFrontSeat'
                )

            # Add a time dimension to balance per-van route duration (minimize max route time)
            try:
                routing.AddDimension(
                    transit_callback_index,
                    0,           # no waiting/slack
                    10**7,       # large upper bound on per-vehicle time
                    True,        # start cumul to zero
                    'Time'
                )
                time_dimension = routing.GetDimensionOrDie('Time')
                time_dimension.SetGlobalSpanCostCoefficient(100)
            except Exception as e:
                logger.warning(f"Failed to add time dimension for balancing: {e}")

            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
            search_parameters.time_limit.seconds = 15

            solution = routing.SolveWithParameters(search_parameters)

            if not solution:
                return {
                    'route_sequence': [],
                    'total_distance': 0,
                    'is_feasible': False,
                    'vehicle_routes': []
                }

            # Extract route
            index = routing.Start(0)
            route = []
            total_distance_m = 0
            total_duration_s = 0

            while not routing.IsEnd(index):
                from_node_index = manager.IndexToNode(index)
                route.append(from_node_index)
                previous_index = index
                index = solution.Value(routing.NextVar(index))
                to_node_index = manager.IndexToNode(index)
                # Sum both distance and duration from matrices
                edge_distance = distance_matrix[from_node_index][to_node_index]
                edge_duration = duration_matrix[from_node_index][to_node_index]
                if edge_distance is not None:
                    total_distance_m += int(edge_distance)
                if edge_duration is not None:
                    total_duration_s += int(edge_duration)

            route.append(manager.IndexToNode(index))  # End at depot

            return {
                'route_sequence': route,
                'total_distance': total_distance_m,
                'total_duration': total_duration_s,
                'is_feasible': True,
                'vehicle_routes': [{
                    'vehicle_id': 0,
                    'stops': route[1:-1],  # Exclude depot from stops
                    'distance': total_distance_m,
                    'duration': total_duration_s,
                    'load': sum(len(stop.passengers) for stop in stops)
                }]
            }

        except Exception as e:
            logger.error(f"Single vehicle optimization failed: {e}")
            return {
                'route_sequence': [],
                'total_distance': 0,
                'is_feasible': False,
                'vehicle_routes': []
            }

    def _optimize_multi_vehicle(
        self,
        distance_matrix: List[List[Optional[int]]],
        duration_matrix: List[List[Optional[int]]],
        stops: List[StopModel],
        num_vehicles: int,
        max_regular_non_wheelchair: Optional[int] = None,
        vehicle_capacities: Optional[List[int]] = None,
        regular_non_wheelchair_capacities: Optional[List[int]] = None,
        wheelchair_capacities: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Optimize routes for multiple vehicles (VRP)
        """
        try:
            n = len(stops) + 1  # +1 for depot
            manager = pywrapcp.RoutingIndexManager(n, num_vehicles, 0)
            routing = pywrapcp.RoutingModel(manager)

            # Use duration as the optimization cost while still tracking distance
            def duration_cost_callback(from_index, to_index):
                from_node = manager.IndexToNode(from_index)
                to_node = manager.IndexToNode(to_index)

                duration = duration_matrix[from_node][to_node]
                if duration is None:
                    return 10**9  # Large penalty for unreachable locations
                return int(duration)

            transit_callback_index = routing.RegisterTransitCallback(duration_cost_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

            # Add capacity constraints
            def demand_callback(from_index):
                from_node = manager.IndexToNode(from_index)
                if from_node == 0:  # Depot
                    return 0
                return len(stops[from_node - 1].passengers)

            demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
            capacities = vehicle_capacities if vehicle_capacities is not None and len(vehicle_capacities) == num_vehicles else [self.vehicle_capacity] * num_vehicles
            routing.AddDimensionWithVehicleCapacity(
                demand_callback_index,
                0,  # null capacity slack
                capacities,  # vehicle maximum capacities
                True,  # start cumul to zero
                'Capacity'
            )

            # If there are at least as many stops as vehicles, require each vehicle
            # to serve at least one stop by enforcing a minimum load of 1.
            if len(stops) >= num_vehicles:
                capacity_dim = routing.GetDimensionOrDie('Capacity')
                for v in range(num_vehicles):
                    end_var = capacity_dim.CumulVar(routing.End(v))
                    # Lower bound 1, upper bound remains capacity of vehicle
                    end_var.SetRange(1, capacities[v])

            # Optionally add a second capacity dimension to limit non-wheelchair passengers per vehicle
            if (regular_non_wheelchair_capacities is not None and len(regular_non_wheelchair_capacities) == num_vehicles) or (max_regular_non_wheelchair is not None):
                def regular_demand_callback(from_index):
                    from_node = manager.IndexToNode(from_index)
                    if from_node == 0:
                        return 0
                    stop = stops[from_node - 1]
                    return 0 if stop.wheelchair else len(stop.passengers)

                regular_demand_index = routing.RegisterUnaryTransitCallback(regular_demand_callback)
                routing.AddDimensionWithVehicleCapacity(
                    regular_demand_index,
                    0,
                    (regular_non_wheelchair_capacities if regular_non_wheelchair_capacities is not None and len(regular_non_wheelchair_capacities) == num_vehicles else [max_regular_non_wheelchair] * num_vehicles),
                    True,
                    'RegularFrontSeat'
                )

            # Optionally add a wheelchair seats dimension to limit wheelchair riders per vehicle
            if wheelchair_capacities is not None and len(wheelchair_capacities) == num_vehicles:
                def wheelchair_demand_callback(from_index):
                    from_node = manager.IndexToNode(from_index)
                    if from_node == 0:
                        return 0
                    stop = stops[from_node - 1]
                    return len(stop.passengers) if stop.wheelchair else 0

                wheelchair_demand_index = routing.RegisterUnaryTransitCallback(wheelchair_demand_callback)
                routing.AddDimensionWithVehicleCapacity(
                    wheelchair_demand_index,
                    0,
                    wheelchair_capacities,
                    True,
                    'WheelchairSeats'
                )

            # Add time dimension for load balancing across vehicles
            try:
                routing.AddDimension(
                    transit_callback_index,
                    0,           # no waiting/slack
                    10**7,       # large upper bound on per-vehicle time
                    True,        # start cumul to zero
                    'Time'
                )
                time_dimension = routing.GetDimensionOrDie('Time')
                time_dimension.SetGlobalSpanCostCoefficient(100)
            except Exception as e:
                logger.warning(f"Failed to add time dimension for balancing: {e}")

            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION)
            search_parameters.local_search_metaheuristic = (
                routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
            search_parameters.time_limit.seconds = 30

            solution = routing.SolveWithParameters(search_parameters)

            if not solution:
                return {
                    'route_sequence': [],
                    'total_distance': 0,
                    'is_feasible': False,
                    'vehicle_routes': []
                }

            # Extract routes for each vehicle
            vehicle_routes = []
            total_distance_m = 0
            total_duration_s = 0

            for vehicle_id in range(num_vehicles):
                index = routing.Start(vehicle_id)
                route = []
                route_distance_m = 0
                route_duration_s = 0

                while not routing.IsEnd(index):
                    from_node_index = manager.IndexToNode(index)
                    route.append(from_node_index)
                    previous_index = index
                    index = solution.Value(routing.NextVar(index))
                    to_node_index = manager.IndexToNode(index)
                    edge_distance = distance_matrix[from_node_index][to_node_index]
                    edge_duration = duration_matrix[from_node_index][to_node_index]
                    if edge_distance is not None:
                        route_distance_m += int(edge_distance)
                    if edge_duration is not None:
                        route_duration_s += int(edge_duration)

                route.append(manager.IndexToNode(index))  # End at depot

                if len(route) > 2:  # More than just depot -> depot
                    vehicle_routes.append({
                        'vehicle_id': vehicle_id,
                        'stops': route[1:-1],  # Exclude depot
                        'distance': route_distance_m,
                        'duration': route_duration_s,
                        'load': sum(len(stops[node-1].passengers) for node in route[1:-1])
                    })
                    total_distance_m += route_distance_m
                    total_duration_s += route_duration_s

            return {
                'route_sequence': [],  # Not used in multi-vehicle case
                'total_distance': total_distance_m,
                'total_duration': total_duration_s,
                'is_feasible': True,
                'vehicle_routes': vehicle_routes
            }

        except Exception as e:
            logger.error(f"Multi-vehicle optimization failed: {e}")
            return {
                'route_sequence': [],
                'total_distance': 0,
                'is_feasible': False,
                'vehicle_routes': []
            }
