from typing import List, Dict, Optional, Union, Literal, Any
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import pytz
import requests
from dataclasses import dataclass
import inspect
from functools import lru_cache
from chatbot_data_models import ToolState, ToolMethodStatus, ToolStatus

class TransitVehicleType(str, Enum):
    """Supported transit vehicle types"""
    BUS = "BUS"
    TRAIN = "TRAIN"
    LIGHT_RAIL = "LIGHT_RAIL"
    RAIL = "RAIL"
    SUBWAY = "SUBWAY"
    FERRY = "FERRY"

class TravelMode(str, Enum):
    """Available travel modes for routing"""
    DRIVE = "DRIVE"
    BICYCLE = "BICYCLE"
    WALK = "WALK"
    TRANSIT = "TRANSIT"
    TWO_WHEELER = "TWO_WHEELER"

class RoutingPreference(str, Enum):
    """Route calculation preferences"""
    TRAFFIC_UNAWARE = "TRAFFIC_UNAWARE"
    TRAFFIC_AWARE = "TRAFFIC_AWARE"
    TRAFFIC_AWARE_OPTIMAL = "TRAFFIC_AWARE_OPTIMAL"

class Units(str, Enum):
    """Distance unit preferences"""
    METRIC = "METRIC"
    IMPERIAL = "IMPERIAL"

class TrafficModel(str, Enum):
    """Traffic modeling preferences"""
    BEST_GUESS = "BEST_GUESS"
    OPTIMISTIC = "OPTIMISTIC"
    PESSIMISTIC = "PESSIMISTIC"

class Location(BaseModel):
    """Location specification using various methods"""
    lat_lng: Optional[Dict[str, float]] = None
    place_id: Optional[str] = None
    address: Optional[str] = None
    plus_code: Optional[str] = None

class TransitPreference(str, Enum):
    """Transit routing preferences"""
    TRANSIT_ROUTING_PREFERENCE_UNSPECIFIED = "TRANSIT_ROUTING_PREFERENCE_UNSPECIFIED"
    LESS_WALKING = "LESS_WALKING"
    FEWER_TRANSFERS = "FEWER_TRANSFERS"

class RouteModifiers(BaseModel):
    """Route calculation modifiers"""
    avoidTolls: bool = False
    avoidHighways: bool = False
    avoidFerries: bool = False
    avoidIndoor: bool = False

class TransitDetails(BaseModel):
    """Details about a transit segment"""
    arrivalStop: Dict[str, Union[str, Location]]
    departureStop: Dict[str, Union[str, Location]]
    arrivalTime: datetime
    departureTime: datetime
    headsign: str
    headway: Optional[int]
    numStops: int
    line: Dict[str, Any]  # Transit line details

class RouteStep(BaseModel):
    """Individual step in a route"""
    distance: float
    duration: str
    startLocation: Location
    endLocation: Location
    detailedInstructions: Optional[str] = ""
    htmlInstructions: str
    travelMode: TravelMode
    transitDetails: Optional[TransitDetails] = None
    polyline: str

class RouteLeg(BaseModel):
    """Leg of a route between two points"""
    startAddress: str
    endAddress: str
    startLocation: Location
    endLocation: Location
    steps: List[RouteStep]
    distance: float
    duration: str
    durationInTraffic: Optional[str]

class Route(BaseModel):
    """Complete route information"""
    summary: str
    legs: List[RouteLeg]
    warnings: List[str]
    waypoint_order: List[int]
    fare: Optional[Dict[str, Union[str, float]]]
    overview_polyline: str
    travelAdvisory: Optional[Dict[str, Union[str, Dict, List]]] = {}
    routeLabels: Optional[List[str]] = []

class GoogleMapsRouter:
    """
    A comprehensive Google Maps routing tool with first-class support for all transit modes.
    Provides detailed routing information including transit specifics and real-time traffic data.
    """
    
    def __init__(self, api_key: str, default_region: str = "us", default_units: Units = Units.METRIC):
        """
        Initialize the Google Maps router.
        
        Args:
            api_key: Google Maps API key with Routes API access
            default_region: Default region code for geocoding (e.g., 'us', 'uk')
            default_units: Default unit system for distances (METRIC or IMPERIAL)
        """
        self.api_key = api_key
        self.default_region = default_region
        self.default_units = default_units
        self.base_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        pass

    def _get_available_methods(self) -> List[Dict[str, str]]:
        """
        Returns a list of all public methods in the class along with their docstrings.
        
        Returns:
            List of dictionaries containing method names and their documentation.
            Each dictionary has:
                - name: Method name
                - docstring: Method documentation
                - signature: Method signature
        """
        methods = []
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # Skip private methods (those starting with _)
            if not name.startswith('_'):
                # Get the method's signature
                signature = str(inspect.signature(method))
                # Get the method's docstring, clean it up and handle None case
                docstring = inspect.getdoc(method) or "No documentation available"
                
                methods.append({
                    "name": name,
                    "docstring": docstring,
                    "signature": f"{name}{signature}",
                    "func": method
                })
        
        return sorted(methods, key=lambda x: x["name"])

    def get_transit_route(
        self,
        origin: Union[str, Dict[str, float], Location],
        destination: Union[str, Dict[str, float], Location],
        departure_time: Optional[str] = None,
        arrival_time: Optional[str] = None,
        preferences: Optional[TransitPreference] = None,
        alternatives: bool = False,
        language: str = "en"
    ) -> List[Route]:
        """
        Get detailed transit routing information given a origin and destination addresses.
        
        Args:
            origin: Starting location (address, lat/lng dict, or Location object) (Required)
            destination: Ending location (address, lat/lng dict, or Location object) (Required)
            departure_time: Desired departure time (default: current time)
            arrival_time: Desired arrival time (mutually exclusive with departure_time)
            preferences: Transit routing preferences including:
                - max_walking_duration: Maximum walking time between stops
                - max_transfers: Maximum number of transfers allowed
                - cost_preference: Optimize for less walking or fewer transfers
            alternatives: Whether to return alternative routes
            language: Language for instructions and names
                
        Returns:
            List of Route objects containing complete routing information with transit details
            
        Raises:
            ValueError: If location format is invalid or timing parameters conflict
            requests.RequestException: If API request fails
        """
        # Format locations
        origin_dict = self._format_location(origin)
        destination_dict = self._format_location(destination)

        arrival_time = datetime.fromisoformat(arrival_time) if arrival_time else None
        departure_time = datetime.fromisoformat(departure_time) if departure_time else None
        
        # Set default departure time if neither departure nor arrival specified
        if not departure_time and not arrival_time:
            departure_time = datetime.now(pytz.utc)
        
        # Build request body
        request_body = self._build_request_body(
            origin=origin_dict,
            destination=destination_dict,
            mode=TravelMode.TRANSIT,
            departure_time=departure_time,
            arrival_time=arrival_time,
            transit_preferences=preferences,
            alternatives=alternatives,
            language=language
        )
        
        # Add transit-specific fields to field mask
        request_fields = request_body.pop('fields')
        request_fields += (
            ",routes.legs.steps.transitDetails.arrivalStop,"
            "routes.legs.steps.transitDetails.departureStop,"
            "routes.legs.steps.transitDetails.headsign,"
            "routes.legs.steps.transitDetails.headway,"
            "routes.legs.steps.transitDetails.stopCount,"
            "routes.legs.steps.transitDetails.transitLine"
        )
        
        try:
            response = requests.post(
                self.base_url,
                json=request_body,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "*"
                }
            )
            response.raise_for_status()
            
            # routes = self._parse_response(response.json())
            
            # # Cache successful responses for identical future requests
            # self.get_transit_route.cache_info()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            error_body = e.response.json() if e.response is not None else {}
            error_message = error_body.get('error', {}).get('message', str(e))
            raise requests.RequestException(
                f"Transit route request failed: {error_message}"
            ) from e

    def get_driving_route(
        self,
        origin: Union[str, Dict[str, float], Location],
        destination: Union[str, Dict[str, float], Location],
        departure_time: Optional[datetime] = None,
        traffic_model: str = TrafficModel.BEST_GUESS.value,
        alternatives: bool = False,
        avoid: Optional[RouteModifiers] = None,
        language: str = "en-US",
        region_code: Optional[str] = None,
        optimize_for_truck: bool = False
    ) -> List[Route]:
        """
        Get motor vehicle driving routes with real-time traffic information and route optimization.
        
        Args:
            origin: Starting location (address, lat/lng dict, or Location object) (Required)
            destination: Ending location (address, lat/lng dict, or Location object) (Required)
            departure_time: Desired departure time for traffic estimation (default: current time + 2 mins)
            traffic_model: Traffic prediction model:
                - BEST_GUESS: Best prediction based on historical data
                - OPTIMISTIC: Optimistic traffic estimate
                - PESSIMISTIC: Conservative traffic estimate
            alternatives: Whether to return alternative routes
            avoid: Route restrictions (tolls, highways, ferries)
            language: Language for instructions (default: en-US)
            region_code: Region bias for geocoding
            optimize_for_truck: Consider truck restrictions and routes if True
                
        Returns:
            List of Route objects containing driving directions with traffic info
            
        Raises:
            ValueError: If location format is invalid or parameters are incompatible
            requests.RequestException: If API request fails
        """
        # Format locations
        origin_dict = self._format_location(origin)
        destination_dict = self._format_location(destination)
        routing_preference = RoutingPreference.TRAFFIC_AWARE_OPTIMAL.value
        
        # Set default departure time for traffic calculation
        if not departure_time and routing_preference != RoutingPreference.TRAFFIC_UNAWARE.value:
            departure_time = datetime.now(pytz.utc) + timedelta(minutes=2)
        if isinstance(departure_time, str):
            departure_time = datetime.fromisoformat(departure_time).replace(tzinfo=pytz.utc)

        # Set up route modifiers
        route_modifiers = avoid if avoid else RouteModifiers()
        
        # Add truck optimization if requested
        if optimize_for_truck:
            # Add truck-specific route modifiers
            route_modifiers.vehicle_info = {
                "type": "TRUCK",
                "height_meters": 4.11,  # Standard truck height
                "width_meters": 2.59,   # Standard truck width
                "length_meters": 21.03,  # Standard truck length
                "axles": 5
            }
        
        # Build request body
        request_body = self._build_request_body(
            origin=origin_dict,
            destination=destination_dict,
            mode=TravelMode.DRIVE,
            departure_time=departure_time,
            routing_preference=routing_preference,
            route_modifiers=route_modifiers,
            alternatives=alternatives,
            language=language,
            region_code=region_code,
            traffic_model=traffic_model
        )
        
        # Request extra computations for driving routes
        request_body["extraComputations"] = [
            "TRAFFIC_ON_POLYLINE",
            "FUEL_CONSUMPTION"
        ]
        
        request_fields = request_body.pop("fields")
        # Add driving-specific fields to field mask
        request_fields += (
            "routes.legs.steps.navigationInstruction,"
            "routes.legs.duration,"
            "routes.legs.staticDuration,"  # Duration without traffic
            "routes.legs.travelAdvisory,"  # Contains toll info
            "routes.routeLabels,"  # For fuel-efficient routes
            "routes.travelAdvisory"  # Road closures, restrictions
        )

        request_body["departureTime"] = datetime.fromisoformat(departure_time.isoformat().split("+")[0]).isoformat() + "Z"

        try:
            response = requests.post(
                self.base_url,
                json=request_body,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "*"
                }
            )
            response.raise_for_status()
            print(response.json())
            # # Parse response with driving-specific information
            # routes = self._parse_driving_response(response.json())
            
            # # Add traffic condition descriptions
            # for route in routes:
            #     self._enhance_traffic_info(route)
            
            return response.json()
        except requests.exceptions.RequestException as e:
            error_body = e.response.json() if e.response is not None else {}
            error_message = error_body.get('error', {}).get('message', str(e))
            raise requests.RequestException(
                f"Driving route request failed: {error_message}"
            ) from e

    def get_multi_modal_route(
        self,
        origin: Union[str, Dict[str, float], Location],
        destination: Union[str, Dict[str, float], Location],
        mode_preference: List[TravelMode],
        departure_time: Optional[datetime] = None,
        transit_pref: Optional[TransitPreference] = None,
        routing_pref: Optional[RoutingPreference] = None,
        alternatives: bool = False,
        language: str = "en"
    ) -> List[Route]:
        """
        Get routes combining multiple modes of transportation.
        
        Args:
            origin: Starting location
            destination: Ending location
            mode_preference: Ordered list of preferred travel modes
            departure_time: Desired departure time
            transit_pref: Transit routing preferences
            routing_pref: Traffic routing preferences
            alternatives: Whether to return alternative routes
            language: Language for instructions
            
        Returns:
            List of Route objects with multi-modal routing information
        """
        raise NotImplementedError

    def _parse_driving_response(self, response: Dict) -> List[Route]:
        """
        Parse API response with driving-specific information.
        
        Args:
            response: Raw API response
            
        Returns:
            List of Route objects with enhanced driving information
        """
        routes = self._parse_response(response)  # Use base parser first
        
        # Enhance routes with driving-specific information
        for route in routes:
            # Add traffic advisories
            if 'travelAdvisory' in response['routes'][0]:
                route.travelAdvisory = {
                    'tollInfo': response['routes'][0]['travelAdvisory'].get('tollInfo', {}),
                    'speedReadingIntervals': response['routes'][0]['travelAdvisory'].get('speedReadingIntervals', []),
                    'fuelConsumptionMicroliters': response['routes'][0]['travelAdvisory'].get('fuelConsumptionMicroliters')
                }
            
            # Add route labels (e.g., FUEL_EFFICIENT)
            route.routeLabels = response['routes'][0].get('routeLabels', [])
            
            # Process each leg for traffic information
            for i, leg in enumerate(route.legs):
                resp_leg = response['routes'][0]['legs'][i]
                
                # Add traffic duration if available
                if 'duration' in resp_leg:
                    leg.durationInTraffic = resp_leg['duration']
                
                # Add detailed step information
                for j, step in enumerate(leg.steps):
                    resp_step = resp_leg['steps'][j]
                    if 'maneuver' in resp_step:
                        step.maneuver = resp_step['maneuver']
                    if 'navigationInstruction' in resp_step:
                        step.detailedInstructions = resp_step['navigationInstruction']
        
        return routes

    def _enhance_traffic_info(self, route: Route):
        """
        Add human-readable traffic condition descriptions to route.
        
        Args:
            route: Route object to enhance
            
        Adds traffic condition descriptions based on speed readings and durations.
        """
        if not hasattr(route, 'traffic_advisory') or not route.traffic_advisory:
            return
            
        intervals = route.traffic_advisory.get('speed_reading_intervals', [])
        if not intervals:
            return
            
        conditions = []
        for interval in intervals:
            if 'speed' in interval:
                speed = interval['speed']
                if speed < 10:
                    conditions.append("Heavy traffic")
                elif speed < 30:
                    conditions.append("Moderate traffic")
                elif speed < 50:
                    conditions.append("Light traffic")
                else:
                    conditions.append("Free flow")
        
        # Add unique conditions to route
        route.traffic_conditions = list(set(conditions))
        
        # Calculate traffic delay
        if route.legs[0].duration_in_traffic and route.legs[0].static_duration:
            delay = (
                self._parse_duration(route.legs[0].duration_in_traffic) - self._parse_duration(route.legs[0].static_duration)
            )
            route.traffic_delay = str(delay) if delay.total_seconds() > 0 else None

    def _parse_duration(self, duration_str: str) -> timedelta:
        """Convert API duration string to timedelta."""
        seconds = float(duration_str.rstrip('s'))
        return timedelta(seconds=seconds)

    def _format_location(self, location: Union[str, Dict[str, float], Location]) -> Dict:
        """
        Convert various location input formats to API-compatible format.
        
        Args:
            location: Location in supported format
                - String: Address or place ID (prefixed with 'place_id:')
                - Dict: {lat: float, lng: float} or {latitude: float, longitude: float}
                - Location: Pydantic Location object
                
        Returns:
            Dictionary in Google Maps API location format with one of:
            - location.latLng
            - placeId
            - address
        
        Raises:
            ValueError: If location format is invalid or missing required data
        """
        if isinstance(location, str):
            # Check if it's a place ID (prefixed with 'place_id:')
            if location.startswith('place_id:'):
                return {"placeId": location[9:]}  # Strip 'place_id:' prefix
            # Treat as address
            return {"address": location}
        
        elif isinstance(location, dict):
            # Handle both {lat, lng} and {latitude, longitude} formats
            if 'lat' in location and 'lng' in location:
                return {
                    "location": {
                        "latLng": {
                            "latitude": float(location['lat']),
                            "longitude": float(location['lng'])
                        }
                    }
                }
            elif 'latitude' in location and 'longitude' in location:
                return {
                    "location": {
                        "latLng": {
                            "latitude": float(location['latitude']),
                            "longitude": float(location['longitude'])
                        }
                    }
                }
            raise ValueError("Invalid coordinates format. Must contain lat/lng or latitude/longitude")
        
        elif isinstance(location, Location):
            # Handle Pydantic Location object
            if location.lat_lng:
                return {
                    "location": {
                        "latLng": {
                            "latitude": location.lat_lng['latitude'],
                            "longitude": location.lat_lng['longitude']
                        }
                    }
                }
            elif location.place_id:
                return {"placeId": location.place_id}
            elif location.address:
                return {"address": location.address}
            elif location.plus_code:
                return {"address": location.plus_code}
                
        raise ValueError("Invalid location format. Must be string, dict with coordinates, or Location object")

    def _validate_transit_time(
        self,
        departure_time: Optional[datetime] = None, 
        arrival_time: Optional[datetime] = None
    ) -> None:
        """
        Validate transit time restrictions.
        
        Args:
            departure_time: Optional departure time
            arrival_time: Optional arrival time
        
        Raises:
            ValueError: If time restrictions are violated
        """
        if departure_time and arrival_time:
            raise ValueError("Cannot specify both departure_time and arrival_time")
        
        if not (departure_time or arrival_time):
            return
            
        now = datetime.now(pytz.utc)
        min_time = now - timedelta(days=7)
        max_time = now + timedelta(days=100)
        
        check_time = departure_time or arrival_time
        if check_time < min_time:
            raise ValueError(
                "Transit trips must be within last 7 days. "
                f"Requested time {check_time.isoformat()} is too far in the past."
            )
        
        if check_time > max_time:
            raise ValueError(
                "Transit trips must be within next 100 days. "
                f"Requested time {check_time.isoformat()} is too far in the future."
            )

    def _validate_traffic_mode(
        self, 
        mode: TravelMode,
        routing_preference: Optional[RoutingPreference],
        traffic_model: Optional[str]
    ) -> None:
        """
        Validate traffic-related settings.
        
        Args:
            mode: Travel mode
            routing_preference: Traffic routing preference
            traffic_model: Traffic prediction model
        
        Raises:
            ValueError: If traffic settings are invalid
        """
        # Check routing preference restrictions
        if routing_preference and mode not in [TravelMode.DRIVE.value, TravelMode.TWO_WHEELER.value]:
            raise ValueError(
                f"routing_preference can only be set for DRIVE or TWO_WHEELER modes, got {mode}"
            )
        
        # Check traffic model restrictions
        if traffic_model:
            if mode != TravelMode.DRIVE.value:
                raise ValueError("traffic_model can only be used with DRIVE mode")
            if not routing_preference or routing_preference != RoutingPreference.TRAFFIC_AWARE_OPTIMAL.value:
                raise ValueError(
                    "traffic_model requires routing_preference=TRAFFIC_AWARE_OPTIMAL"
                )

    def _validate_departure_time(
        self,
        mode: TravelMode,
        routing_preference: Optional[RoutingPreference],
        departure_time: Optional[datetime]
    ) -> None:
        """
        Validate departure time settings.
        
        Args:
            mode: Travel mode
            routing_preference: Traffic routing preference
            departure_time: Requested departure time
        
        Raises:
            ValueError: If departure time settings are invalid
        """
        if not departure_time:
            return
            
        # Check TRAFFIC_UNAWARE restriction
        if (
            routing_preference == RoutingPreference.TRAFFIC_UNAWARE.value and 
            mode != TravelMode.TRANSIT.value
        ):
            raise ValueError(
                "Cannot set departure_time with TRAFFIC_UNAWARE routing preference"
            )
        
        # Check past departure time restriction
        tst_now = datetime.now()
        if departure_time < datetime.now(pytz.utc) and mode != TravelMode.TRANSIT.value:
            raise ValueError(
                "Past departure_time only allowed for TRANSIT mode"
            )

    def _validate_route_modifiers(
        self,
        mode: TravelMode,
        modifiers: Optional[RouteModifiers]
    ) -> None:
        """
        Validate route modifiers for the given mode.
        
        Args:
            mode: Travel mode
            modifiers: Route modification requests
        
        Raises:
            ValueError: If modifiers are invalid for the mode
        """
        if not modifiers:
            return
            
        # Validate vehicle info
        if hasattr(modifiers, 'vehicle_info') and mode != TravelMode.DRIVE:
            raise ValueError("vehicle_info can only be set for DRIVE mode")
        
        # Validate highway/toll avoidance
        if (modifiers.avoidHighways or modifiers.avoidTolls) and mode not in [
            TravelMode.DRIVE, 
            TravelMode.TWO_WHEELER
        ]:
            raise ValueError(
                "Highway and toll avoidance only available for DRIVE and TWO_WHEELER modes"
            )

    def _build_request_body(
        self,
        origin: Dict,
        destination: Dict,
        mode: TravelMode,
        departure_time: Optional[datetime] = None,
        arrival_time: Optional[datetime] = None,
        routing_preference: Optional[RoutingPreference] = None,
        transit_preferences: Optional[TransitPreference] = None,
        route_modifiers: Optional[RouteModifiers] = None,
        alternatives: bool = False,
        language: str = "en",
        units: Optional[Units] = None,
        traffic_model: Optional[TrafficModel] = None,
        region_code: Optional[str] = None
    ) -> Dict:
        """
        Construct the API request body with validation of all parameters.
        
        Args:
            origin: Formatted origin location
            destination: Formatted destination location
            mode: Travel mode (DRIVE, TRANSIT, etc.)
            departure_time: Optional departure time
            arrival_time: Optional arrival time (mutually exclusive with departure_time)
            routing_preference: Traffic routing preference
            transit_preferences: Transit routing options
            route_modifiers: Route restrictions (tolls, highways, etc.)
            alternatives: Whether to request alternative routes
            language: Language code for results
            units: Unit system for distances
            traffic_model: Traffic prediction model
            region_code: Region bias for geocoding
                
        Returns:
            Complete request body for the Routes API
                
        Raises:
            ValueError: If any parameter combinations are invalid
        """
        # Validate all restrictions
        if mode == TravelMode.TRANSIT:
            self._validate_transit_time(departure_time, arrival_time)
        else:
            if arrival_time:
                raise ValueError("arrival_time can only be set for TRANSIT mode")
            if transit_preferences:
                raise ValueError("transit_preferences only valid for TRANSIT mode")
        
        self._validate_traffic_mode(mode, routing_preference, traffic_model)
        self._validate_departure_time(mode, routing_preference, departure_time)
        self._validate_route_modifiers(mode, route_modifiers)

        # Build the base request (previous implementation remains the same)
        body = {
            "origin": origin,
            "destination": destination,
            "travelMode": mode.value,
            "computeAlternativeRoutes": alternatives,
            "languageCode": language,
            "units": (units or self.default_units).value
        }

        # Add optional parameters with mode-specific fields
        if region_code:
            body["regionCode"] = region_code
        elif self.default_region:
            body["regionCode"] = self.default_region

        if routing_preference and mode in [TravelMode.DRIVE.value, TravelMode.TWO_WHEELER.value]:
            body["routingPreference"] = routing_preference
            if traffic_model and routing_preference == RoutingPreference.TRAFFIC_AWARE_OPTIMAL.value:
                body["trafficModel"] = traffic_model

        if mode == TravelMode.TRANSIT.value and transit_preferences:
            body["transitPreferences"] = transit_preferences

        if route_modifiers:
            body["routeModifiers"] = route_modifiers.model_dump()

        # Handle timing parameters
        if departure_time:
            body["departureTime"] = departure_time.isoformat()
        elif arrival_time:
            body["arrivalTime"] = arrival_time.isoformat()
                
        # Add mode-specific fields to field mask
        base_fields = (
            "routes.duration,"
            "routes.distanceMeters,"
            "routes.legs.steps,"
            "routes.legs.duration,"
            "routes.legs.distanceMeters,"
            "routes.polyline.encodedPolyline"
        )
        
        mode_specific_fields = {
            TravelMode.TRANSIT: (
                "routes.legs.steps.transitDetails.arrivalStop,"
                "routes.legs.steps.transitDetails.departureStop,"
                "routes.legs.steps.transitDetails.headsign,"
                "routes.legs.steps.transitDetails.headway,"
                "routes.legs.steps.transitDetails.stopCount,"
                "routes.legs.steps.transitDetails.transitLine"
            ),
            TravelMode.DRIVE: (
                "routes.legs.steps.maneuver,"
                "routes.legs.staticDuration,"
                "routes.legs.travelAdvisory,"
                "routes.routeLabels,"
                "routes.travelAdvisory"
            )
        }
        
        body["fields"] = base_fields + mode_specific_fields.get(mode, "")

        return body

    def _extract_transit_details(self, step: Dict) -> TransitDetails:
        """
        Extract detailed transit information from a route step.
        
        Args:
            step: Route step containing transit information
            
        Returns:
            TransitDetails object with parsed transit information
            
        Note:
            Processes detailed transit data including:
            - Stop information (names, locations, platforms)
            - Line details (route numbers, names, agencies)
            - Timing (arrival, departure, frequency)
            - Vehicle types and identifiers
        """
        line = step.get('transitDetails', {}).get('transitLine', {})
        
        return TransitDetails(
            arrivalStop={
                'name': step['transitDetails']['arrivalStop']['name'],
                'location': Location(
                    lat_lng={
                        'latitude': step['transitDetails']['arrivalStop']['location']['latLng']['latitude'],
                        'longitude': step['transitDetails']['arrivalStop']['location']['latLng']['longitude']
                    }
                )
            },
            departureStop={
                'name': step['transitDetails']['departureStop']['name'],
                'location': Location(
                    lat_lng={
                        'latitude': step['transitDetails']['departureStop']['location']['latLng']['latitude'],
                        'longitude': step['transitDetails']['departureStop']['location']['latLng']['longitude']
                    }
                )
            },
            arrivalTime=datetime.fromisoformat(step['transitDetails']['arrivalTime'].rstrip('Z')),
            departureTime=datetime.fromisoformat(step['transitDetails']['departureTime'].rstrip('Z')),
            headsign=step['transitDetails'].get('headsign', ''),
            headway=int(step['transitDetails'].get('headway', {}).get('seconds', 0)) if 'headway' in step['transitDetails'] else None,
            numStops=step['transitDetails'].get('stopCount', 0),
            line={
                'name': line.get('name', ''),
                'short_name': line.get('nameShort', ''),
                'vehicle': {
                    'type': line.get('vehicle', {}).get('type', ''),
                    'name': line.get('vehicle', {}).get('name', {}).get('text', ''),
                    'icon': line.get('vehicle', {}).get('iconUri', '')
                },
                'agency': [{
                    'name': agency.get('name', ''),
                    'phone': agency.get('phoneNumber', ''),
                    'url': agency.get('uri', '')
                } for agency in line.get('agencies', [])]
            }
        )

    def _parse_transit_step(self, step: Dict) -> RouteStep:
        """
        Parse a single transit step from the route response.
        
        Args:
            step: API response step object
            
        Returns:
            RouteStep object with transit-specific details if applicable
        """
        base_step = RouteStep(
            distance=float(step.get('distanceMeters', 0)),
            duration=step.get('duration', ''),
            startLocation=Location(
                latLng={
                    'latitude': step['startLocation']['latLng']['latitude'],
                    'longitude': step['startLocation']['latLng']['longitude']
                }
            ),
            endLocation=Location(
                latLng={
                    'latitude': step['endLocation']['latLng']['latitude'],
                    'longitude': step['endLocation']['latLng']['longitude']
                }
            ),
            htmlInstructions=step['navigationInstruction'].get('instructions', ''),
            travelMode=TravelMode(step['travelMode']),
            polyline=step.get('polyline', {}).get('encodedPolyline', '')
        )
        
        # Add transit details if this is a transit step
        if step['travelMode'] == 'TRANSIT' and 'transitDetails' in step:
            base_step.transitDetails = self._extract_transit_details(step)
        
        return base_step

    def _parse_response(self, response: Dict) -> List[Route]:
        """
        Parse the API response into Route objects.
        
        Args:
            response: Raw API response
            
        Returns:
            List of parsed Route objects with complete routing information
            
        Raises:
            ValueError: If response format is invalid
        """
        if 'routes' not in response:
            raise ValueError("Invalid response format - missing 'routes' key")
        
        routes = []
        for route in response['routes']:
            legs = []
            for leg in route.get('legs', []):
                steps = [self._parse_transit_step(step) for step in leg.get('steps', [])]
                
                legs.append(RouteLeg(
                    startAddress=leg.get('startAddress', ''),
                    endAddress=leg.get('endAddress', ''),
                    startLocation=Location(
                        latLng={
                            'latitude': leg['startLocation']['latLng']['latitude'],
                            'longitude': leg['startLocation']['latLng']['longitude']
                        }
                    ),
                    endLocation=Location(
                        latLng={
                            'latitude': leg['endLocation']['latLng']['latitude'],
                            'longitude': leg['endLocation']['latLng']['longitude']
                        }
                    ),
                    steps=steps,
                    distance=float(leg.get('distanceMeters', 0)),
                    duration=leg.get('duration', ''),
                    durationInTraffic=leg.get('staticDuration')
                ))
            
            routes.append(Route(
                summary=route.get('description', ''),
                legs=legs,
                warnings=route.get('warnings', []),
                waypoint_order=route.get('optimizedIntermediateWaypointIndex', []),
                fare=route.get('fare'),
                overview_polyline=route.get('polyline', {}).get('encodedPolyline', '')
            ))
        
        return routes

    @lru_cache(maxsize=1000)
    def _geocode_address(self, address: str) -> Location:
        """
        Convert address string to location coordinates.
        
        Args:
            address: Address string to geocode
            
        Returns:
            Location object with coordinates
        """
        pass

    def _get_tool_status(self) -> Dict[str, bool]:
        """Check operational status of all public tool methods."""
        
        tool_status = ToolStatus(
            status=ToolState.UNOPERATIONAL,
            methods={}
        )
        
        # Test location for health checks
        test_origin = {"lat": 37.7749, "lng": -122.4194}  # San Francisco
        test_dest = {"lat": 37.3382, "lng": -121.8863}    # San Jose
        test_time = (datetime.now(pytz.utc) + timedelta(minutes=30)).isoformat()
        
        for tool_method in self._get_available_methods():
            method_health = ToolMethodStatus(
                status=ToolState.UNOPERATIONAL,
                error=""
            )
            
            try:
                if tool_method['name'] == "get_transit_route":
                    response = self.get_transit_route(
                        origin=test_origin,
                        destination=test_dest,
                        departure_time=test_time
                    )
                    
                elif tool_method['name'] == "get_driving_route":
                    response = self.get_driving_route(
                        origin=test_origin,
                        destination=test_dest,
                        departure_time=test_time.isoformat()
                    )
                    
                elif tool_method['name'] == "get_multi_modal_route":
                    # Skip testing NotImplemented methods
                    if "NotImplementedError" in str(inspect.getsource(tool_method['func'])):
                        method_health.status = False
                        method_health.error = "Method not implemented"
                        tool_status.methods[tool_method['name']] = method_health
                        continue
                        
                    response = self.get_multi_modal_route(
                        origin=test_origin,
                        destination=test_dest,
                        mode_preference=[TravelMode.TRANSIT, TravelMode.WALK],
                        departure_time=test_time
                    )
                
                # Check if response contains expected data
                if isinstance(response, dict):
                    if 'routes' in response:
                        method_health.status = True
                    else:
                        method_health.status = False
                        method_health.error = "Invalid response format - missing routes"
                else:
                    method_health.status = False
                    method_health.error = "Invalid response type"
                    
            except NotImplementedError as e:
                method_health.status = False
                method_health.error = "Method not implemented"
            except requests.exceptions.RequestException as e:
                method_health.status = False
                method_health.error = f"API request failed: {str(e)}"
            except Exception as e:
                method_health.status = False
                method_health.error = str(e)
                
            tool_status.methods[tool_method['name']] = method_health
        
        # Determine overall tool status based on method health
        num_healthy_methods = sum([m.status for m in tool_status.methods.values()])
        if num_healthy_methods <= 0:
            tool_status.status = ToolState.UNOPERATIONAL
        elif num_healthy_methods < len(tool_status.methods):
            tool_status.status = ToolState.PARTIALLY_OPERATIONAL
        elif num_healthy_methods == len(tool_status.methods):
            tool_status.status = ToolState.FULLY_OPERATIONAL
        
        return tool_status