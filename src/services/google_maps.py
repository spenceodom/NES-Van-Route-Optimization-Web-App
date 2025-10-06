"""
Google Maps API Service for NES Van Route Optimization
Handles geocoding and distance matrix calculations
"""

import os
import logging
from typing import List, Tuple, Optional, Dict, Any
from functools import lru_cache
import time

logger = logging.getLogger(__name__)

class GoogleMapsService:
    """Service for interacting with Google Maps API for geocoding and distance matrix"""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Google Maps client

        Args:
            api_key: Google Maps API key. If None, will try to get from environment
        """
        self.api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY")
        if self.api_key:
            self.api_key = self.api_key.strip()
        if not self.api_key:
            raise ValueError("Google Maps API key not provided. Set GOOGLE_MAPS_API_KEY in secrets or environment")
        # Guard against hidden invalid characters that can break libraries
        if any((c == "\x00" or ord(c) < 32) for c in self.api_key):
            raise ValueError("Google Maps API key contains invalid characters. Please paste a clean plain-text key.")

        # Lazy import to avoid app startup failures when dependency is missing
        try:
            import googlemaps  # type: ignore
            from googlemaps.exceptions import ApiError, TransportError, Timeout  # type: ignore
        except ImportError as e:
            raise ImportError("googlemaps package not found. Install with: pip install googlemaps") from e

        self._api_exceptions = (ApiError, TransportError, Timeout)
        self.client = googlemaps.Client(key=self.api_key)

        # Rate limiting: Google Maps allows 40 requests per second
        self.last_request_time = 0
        self.min_request_interval = 1.0 / 40.0  # 40 requests per second max

    def _rate_limit(self):
        """Enforce rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    @lru_cache(maxsize=1000)
    def geocode_address(self, address: str) -> Tuple[float, float]:
        """
        Geocode a single address to latitude, longitude

        Args:
            address: Full address string

        Returns:
            Tuple of (latitude, longitude)

        Raises:
            ValueError: If address cannot be geocoded
        """
        try:
            self._rate_limit()
            result = self.client.geocode(address)

            if not result:
                raise ValueError(f"Could not geocode address: {address}")

            location = result[0]["geometry"]["location"]
            return (location["lat"], location["lng"])

        except self._api_exceptions as e:  # type: ignore[attr-defined]
            logger.error(f"Google Maps API error geocoding '{address}': {e}")
            raise ValueError(f"Failed to geocode address '{address}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error geocoding '{address}': {e}")
            raise ValueError(f"Failed to geocode address '{address}': {e}")

    def geocode_addresses(self, addresses: List[str]) -> List[Tuple[float, float]]:
        """
        Geocode multiple addresses

        Args:
            addresses: List of address strings

        Returns:
            List of (latitude, longitude) tuples in same order as input
        """
        coordinates = []
        failed_addresses = []

        for address in addresses:
            try:
                coords = self.geocode_address(address)
                coordinates.append(coords)
            except ValueError as e:
                logger.warning(f"Failed to geocode: {address} - {e}")
                failed_addresses.append(address)
                # Add None placeholder to maintain order
                coordinates.append(None)

        if failed_addresses:
            logger.warning(f"Failed to geocode {len(failed_addresses)} addresses: {failed_addresses}")

        return coordinates

    def get_distance_matrix(
        self,
        origins: List[Tuple[float, float]],
        destinations: List[Tuple[float, float]],
        departure_time: Optional[str] = None
    ) -> Tuple[List[List[Optional[int]]], List[List[Optional[int]]]]:
        """
        Get distance matrix between multiple origin-destination pairs

        Args:
            origins: List of (lat, lng) tuples for origins
            destinations: List of (lat, lng) tuples for destinations
            departure_time: ISO 8601 formatted time for traffic-aware routing (optional)

        Returns:
            Tuple of (distance_matrix, duration_matrix) where each is a 2D list
            Values are in meters and seconds respectively, None if route not found
        """
        try:
            # Google Distance Matrix limits: origins * destinations <= 100 per request (standard)
            # We chunk the full matrix into sub-matrices that respect the limit and stitch results.

            num_origins = len(origins)
            num_destinations = len(destinations)

            # Initialize full matrices with None
            distance_matrix: List[List[Optional[int]]] = [
                [None for _ in range(num_destinations)] for _ in range(num_origins)
            ]
            duration_matrix: List[List[Optional[int]]] = [
                [None for _ in range(num_destinations)] for _ in range(num_origins)
            ]

            # Choose chunk sizes such that rows_chunk * cols_chunk <= 100
            # Aim for square-ish chunks for efficiency
            max_elements = 100
            # Start with up to 10x10, grow rows chunk up to 25 while keeping product <= 100
            rows_chunk = min(num_origins, 25)
            cols_chunk = max_elements // max(1, rows_chunk)
            cols_chunk = max(1, min(num_destinations, cols_chunk))

            # If cols_chunk ends up too small, rebalance
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

                    # Enforce per-request rate limit
                    self._rate_limit()

                    params: Dict[str, Any] = {
                        "origins": origin_strs,
                        "destinations": dest_strs,
                        "mode": "driving",
                        "units": "metric",
                    }
                    if departure_time:
                        params["departure_time"] = departure_time

                    result = self.client.distance_matrix(**params)

                    if result.get("status") != "OK":
                        raise ValueError(f"Distance matrix API returned status: {result.get('status')}")

                    # Extract and place into full matrices
                    for i_row, row in enumerate(result.get("rows", [])):
                        dist_row: List[Optional[int]] = []
                        dur_row: List[Optional[int]] = []
                        for element in row.get("elements", []):
                            if element.get("status") == "OK":
                                dist_row.append(element["distance"]["value"])  # meters
                                dur_row.append(element["duration"]["value"])   # seconds
                            else:
                                dist_row.append(None)
                                dur_row.append(None)

                        # Place into the correct slice
                        for j_col, (d_val, t_val) in enumerate(zip(dist_row, dur_row)):
                            distance_matrix[row_start + i_row][col_start + j_col] = d_val
                            duration_matrix[row_start + i_row][col_start + j_col] = t_val

            return distance_matrix, duration_matrix

        except (ApiError, TransportError, Timeout) as e:
            logger.error(f"Google Maps distance matrix API error: {e}")
            raise ValueError(f"Failed to get distance matrix: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting distance matrix: {e}")
            raise ValueError(f"Failed to get distance matrix: {e}")

    def get_route_optimization_matrix(
        self,
        depot_coords: Tuple[float, float],
        stop_coords: List[Tuple[float, float]]
    ) -> Tuple[List[List[Optional[int]]], List[List[Optional[int]]]]:
        """
        Get distance/duration matrix optimized for route planning
        Includes depot as both origin and destination for all stops

        Args:
            depot_coords: (lat, lng) of depot
            stop_coords: List of (lat, lng) for stops

        Returns:
            Matrix where row 0 and column 0 represent the depot
        """
        # Create full coordinate list: [depot, stop1, stop2, ...]
        all_coords = [depot_coords] + stop_coords

        # Get full distance matrix
        distance_matrix, duration_matrix = self.get_distance_matrix(all_coords, all_coords)

        return distance_matrix, duration_matrix
