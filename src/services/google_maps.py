"""
Google Maps API Service for NES Van Route Optimization
Handles geocoding and distance matrix calculations
"""

import os
import logging
from typing import List, Tuple, Optional, Dict, Any
from functools import lru_cache
import time

try:
    import googlemaps
    from googlemaps.exceptions import ApiError, TransportError, Timeout
except ImportError:
    raise ImportError("googlemaps package not found. Install with: pip install googlemaps")

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
        if not self.api_key:
            raise ValueError("Google Maps API key not provided. Set GOOGLE_MAPS_API_KEY environment variable")

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

        except (ApiError, TransportError, Timeout) as e:
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
            self._rate_limit()

            # Convert coordinates to Google Maps format
            origin_strs = [f"{lat},{lng}" for lat, lng in origins]
            dest_strs = [f"{lat},{lng}" for lat, lng in destinations]

            # Build request parameters
            params = {
                "origins": origin_strs,
                "destinations": dest_strs,
                "mode": "driving",
                "units": "metric"
            }

            if departure_time:
                params["departure_time"] = departure_time

            result = self.client.distance_matrix(**params)

            if result["status"] != "OK":
                raise ValueError(f"Distance matrix API returned status: {result['status']}")

            # Extract distance and duration matrices
            distance_matrix = []
            duration_matrix = []

            for row in result["rows"]:
                dist_row = []
                dur_row = []

                for element in row["elements"]:
                    if element["status"] == "OK":
                        dist_row.append(element["distance"]["value"])  # meters
                        dur_row.append(element["duration"]["value"])   # seconds
                    else:
                        dist_row.append(None)
                        dur_row.append(None)

                distance_matrix.append(dist_row)
                duration_matrix.append(dur_row)

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
