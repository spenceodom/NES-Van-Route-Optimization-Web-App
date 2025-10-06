"""
NES Van Route Optimization Engine
Real OR-Tools TSP/VRP implementation with Google Maps API integration
"""

import logging
from typing import List, Optional, Tuple, Dict, Any
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from src.models.route_models import StopModel

logger = logging.getLogger(__name__)

class RouteOptimizer:
    """Main optimization engine using OR-Tools with Google Maps API"""

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

        # Defensive check: ensure google_maps.py source has no null bytes on deployed envs
        try:
            import importlib.util
            import os
            spec = importlib.util.find_spec('src.services.google_maps')
            gm_path = spec.origin if spec and spec.origin else os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'services', 'google_maps.py'))
            try:
                with open(gm_path, 'rb') as f:
                    data = f.read()
                if b'\x00' in data:
                    raise ValueError("Detected invalid null bytes in src/services/google_maps.py on the server. Redeploy a clean copy from GitHub or restart the app to clear corrupted files.")
            except FileNotFoundError:
                # If the file isn't where expected, proceed to import and let Python raise a clear error
                pass
        except Exception:
            # Non-fatal: continue; import will still be attempted below
            pass

        # Lazy import to avoid startup failures if maps service has environment issues
        try:
            from src.services.google_maps import GoogleMapsService as _GoogleMapsService
        except SyntaxError as se:
            # Wrap syntax error to provide clearer guidance
            raise ValueError("Failed to load Google Maps service due to a corrupted source file on the server. Please redeploy/refresh the app so that src/services/google_maps.py is a clean UTF-8 text file.") from se

        self.gmaps_service = _GoogleMapsService(api_key)

    def optimize_route(
        self,
        stops: List[StopModel],
        start_time,
        num_vehicles: int = 1
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
            if num_vehicles == 1:
                # Single vehicle - use TSP
                result = self._optimize_single_vehicle(distance_matrix, duration_matrix, valid_stops)
            else:
                # Multiple vehicles - use VRP
                result = self._optimize_multi_vehicle(distance_matrix, duration_matrix, valid_stops, num_vehicles)

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
        stops: List[StopModel]
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
                    return 999999  # Large penalty for unreachable locations
                return int(duration)

            transit_callback_index = routing.RegisterTransitCallback(duration_cost_callback)
            routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
            search_parameters.time_limit.seconds = 10

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
        num_vehicles: int
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
                    return 999999
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
            routing.AddDimensionWithVehicleCapacity(
                demand_callback_index,
                0,  # null capacity slack
                [self.vehicle_capacity] * num_vehicles,  # vehicle maximum capacities
                True,  # start cumul to zero
                'Capacity'
            )

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
