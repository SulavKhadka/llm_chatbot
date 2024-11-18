import os
from typing import Dict, List, Optional, Union
from datetime import datetime
import requests
from geopy.geocoders import Nominatim
import inspect

class WeatherTool:
    """
    A streamlined interface for OpenWeatherMap API providing actionable weather data methods.
    Each public method represents a distinct tool capability that can be used by an agent.
    """
    
    def __init__(self, api_key: str):
        """
        Initialize the Weather tool with API key.
        
        Args:
            api_key: OpenWeatherMap API key
        """
        self._api_key = api_key
        self._base_url = 'https://api.openweathermap.org/data/2.5'
        self._geolocator = Nominatim(user_agent="weather_tool")

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

    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make an API request to OpenWeatherMap."""
        if params is None:
            params = {}
        
        params['appid'] = self._api_key
        url = f"{self._base_url}/{endpoint}"
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as error:
            raise Exception(f"API request failed: {error}")

    def _get_coordinates(self, location: str) -> tuple:
        """Convert location string to coordinates using geocoding."""
        try:
            location_data = self._geolocator.geocode(location)
            if location_data is None:
                raise ValueError(f"Could not find coordinates for location: {location}")
            return location_data.latitude, location_data.longitude
        except Exception as error:
            raise Exception(f"Geocoding failed: {error}")

    def _format_weather_data(self, weather_data: Dict) -> Dict:
        """Format raw weather data into a more user-friendly structure."""
        return {
            'location': weather_data.get('name'),
            'country': weather_data.get('sys', {}).get('country'),
            'temperature': weather_data.get('main', {}).get('temp'),
            'feels_like': weather_data.get('main', {}).get('feels_like'),
            'humidity': weather_data.get('main', {}).get('humidity'),
            'pressure': weather_data.get('main', {}).get('pressure'),
            'description': weather_data.get('weather', [{}])[0].get('description'),
            'wind_speed': weather_data.get('wind', {}).get('speed'),
            'wind_direction': weather_data.get('wind', {}).get('deg'),
            'clouds': weather_data.get('clouds', {}).get('all'),
            'rain_1h': weather_data.get('rain', {}).get('1h'),
            'snow_1h': weather_data.get('snow', {}).get('1h'),
            'timestamp': datetime.fromtimestamp(weather_data.get('dt', 0))
        }

    def get_current_weather(self, location: str, units: str = 'metric', language: str = 'en') -> Dict:
        """
        Get current weather conditions for a location.
        
        Args:
            location: City name or "City,CountryCode" (e.g. "London,UK")
            units: Units of measurement ('standard' for Kelvin, 'metric' for Celsius, 'imperial' for Fahrenheit)
            language: Language code for weather descriptions (e.g. 'en', 'es', 'fr')
            
        Returns:
            Dictionary containing current weather data including:
            - temperature and feels like temperature in requested units
            - humidity percentage
            - pressure in hPa
            - weather description in requested language
            - wind speed (m/s for metric, mph for imperial)
            - cloudiness percentage
            - precipitation data if present
        """
        lat, lon = self._get_coordinates(location)
        
        params = {
            'lat': lat,
            'lon': lon,
            'units': units,
            'lang': language
        }
        
        data = self._make_request('weather', params)
        return self._format_weather_data(data)

    def get_forecast(self, location: str, forecast_days: int = 5, units: str = 'metric', language: str = 'en') -> Dict:
        """
        Get weather forecast for a location.
        
        Args:
            location: City name or "City,CountryCode" (e.g. "London,UK")
            forecast_days: Number of days (1-16) for forecast
            units: Units of measurement ('standard' for Kelvin, 'metric' for Celsius, 'imperial' for Fahrenheit)
            language: Language code for weather descriptions (e.g. 'en', 'es', 'fr')
            
        Returns:
            Dictionary containing daily forecast data including:
            - daily temperature ranges
            - precipitation probability
            - weather conditions
            - wind speed and direction
            - humidity and pressure
        """
        if not 1 <= forecast_days <= 16:
            raise ValueError("Forecast days must be between 1 and 16")
            
        lat, lon = self._get_coordinates(location)
        
        params = {
            'lat': lat,
            'lon': lon,
            'units': units,
            'lang': language,
            'cnt': forecast_days
        }
        
        return self._make_request('forecast/daily', params)

    def get_air_quality(self, location: str) -> Dict:
        """
        Get current air quality data for a location.
        
        Args:
            location: City name or "City,CountryCode" (e.g. "London,UK")
            
        Returns:
            Dictionary containing air quality data including:
            - Air Quality Index (AQI)
            - Individual pollutant levels (CO, NO2, O3, SO2, PM2.5, PM10)
            - Qualitative air quality assessment
            - Timestamp of measurement
        """
        lat, lon = self._get_coordinates(location)
        
        params = {
            'lat': lat,
            'lon': lon
        }
        
        return self._make_request('air_pollution', params)