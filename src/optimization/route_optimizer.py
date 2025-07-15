"""
NES Van Route Optimization Engine
Basic OR-Tools TSP implementation with dummy Euclidean distances
"""

import numpy as np
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from typing import List
from src.models.route_models import StopModel

class RouteOptimizer:
    """Main optimization engine using OR-Tools (TSP for MVP)"""
    def __init__(self, depot_address, vehicle_capacity=15):
        self.depot_address = depot_address
        self.vehicle_capacity = vehicle_capacity

    def optimize_route(self, stops: List[StopModel], start_time):
        # For MVP, generate dummy coordinates for each stop
        n = len(stops)
        coords = self._generate_dummy_coords(n)
        distance_matrix = self._euclidean_distance_matrix(coords)

        # OR-Tools TSP setup
        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return int(distance_matrix[from_node][to_node])

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
        search_parameters.time_limit.seconds = 5

        solution = routing.SolveWithParameters(search_parameters)
        if not solution:
            return {
                'route_sequence': [],
                'total_distance': 0,
                'is_feasible': False
            }

        # Extract route
        index = routing.Start(0)
        route = []
        total_distance = 0
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            total_distance += routing.GetArcCostForVehicle(previous_index, index, 0)
        route.append(manager.IndexToNode(index))  # End

        return {
            'route_sequence': route,
            'total_distance': total_distance,
            'is_feasible': True
        }

    def _generate_dummy_coords(self, n):
        # For MVP, generate random 2D coordinates for each stop
        np.random.seed(42)
        return np.random.rand(n, 2) * 100

    def _euclidean_distance_matrix(self, coords):
        n = coords.shape[0]
        matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                if i != j:
                    matrix[i][j] = np.linalg.norm(coords[i] - coords[j])
        return matrix 