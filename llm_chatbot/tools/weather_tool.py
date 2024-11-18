import requests
from typing import Dict, Optional, List
from datetime import datetime
import inspect

class WeatherTool:
    """
    A streamlined weather data interface using the Tomorrow.io API.
    Provides current conditions and forecasts with automated weather code translation.
    """
    
    def __init__(self, api_key: str):
        """
        Initialize WeatherTool with Tomorrow.io API key.
        
        Args:
            api_key: Tomorrow.io API key
        """
        self._api_key = api_key
        self._base_url = "https://api.tomorrow.io/v4/weather"
        self._weather_codes = {
            0: "Unknown",
            1000: "Clear, Sunny",
            1100: "Mostly Clear",
            1101: "Partly Cloudy",
            1102: "Mostly Cloudy",
            1001: "Cloudy",
            2000: "Fog",
            2100: "Light Fog",
            4000: "Drizzle",
            4001: "Rain",
            4200: "Light Rain",
            4201: "Heavy Rain",
            5000: "Snow",
            5001: "Flurries",
            5100: "Light Snow",
            5101: "Heavy Snow",
            6000: "Freezing Drizzle",
            6001: "Freezing Rain",
            6200: "Light Freezing Rain",
            6201: "Heavy Freezing Rain",
            7000: "Ice Pellets",
            7101: "Heavy Ice Pellets",
            7102: "Light Ice Pellets",
            8000: "Thunderstorm"
        }

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

    def _make_request(self, endpoint: str, params: Dict) -> Dict:
        """Make API request to Tomorrow.io."""
        url = f"{self._base_url}/{endpoint}"
        params['apikey'] = self._api_key
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as error:
            raise Exception(f"Weather API request failed: {error}")

    def _translate_weather_code(self, code: int) -> str:
        """Translate numeric weather code to human-readable description."""
        return self._weather_codes.get(code, "Unknown")

    def _process_weather_data(self, data: Dict) -> Dict:
        """Process weather values to include human-readable descriptions."""
        if 'weatherCode' in data:
            data['weatherCondition'] = self._translate_weather_code(data['weatherCode'])
        return data

    def _process_timeline(self, timeline: list) -> list:
        """Process a timeline of weather data to include descriptions."""
        for period in timeline:
            if 'values' in period:
                period['values'] = self._process_weather_data(period['values'])
        return timeline

    def get_current_weather(self, location: str, units: str = 'metric') -> Dict:
        """
        Get current weather conditions.
        
        Args:
            location: Location identifier - can be:
                     - Coordinates (e.g., "42.3478,-71.0466")
                     - City name (e.g., "new york")
                     - US zip (e.g., "10001")
                     - UK postcode (e.g., "SW1")
            units: Unit system ('metric' or 'imperial')
            
        Returns:
            Dictionary containing:
            - temperature and feels_like temperature
            - humidity
            - wind speed and direction
            - precipitation probability and intensity
            - cloud cover, UV index, visibility
            - weather condition (human-readable)
            Plus location details and timestamp
        """
        params = {
            'location': location,
            'units': units
        }
        
        data = self._make_request('realtime', params)
        
        if not data.get('data'):
            raise Exception("No weather data received")
            
        processed_data = {
            'weather': self._process_weather_data(data['data']['values']),
            'location': data['location'],
            'timestamp': data['data']['time']
        }
        
        return processed_data

    def get_forecast(self, location: str, timesteps: str = '1h', days: int = 5, units: str = 'metric') -> Dict:
        """
        Get weather forecast with specified time steps.
        
        Args:
            location: Location identifier (same formats as get_current_weather)
            timesteps: Time resolution - '1h' for hourly or '1d' for daily
            days: Number of days to forecast:
                  - For hourly: 1-5 days (max 120 hours)
                  - For daily: 1-5 days
            units: Unit system ('metric' or 'imperial')
            
        Returns:
            Dictionary containing timeline of forecasts with:
            - temperature range and feels_like
            - precipitation probability and intensity
            - wind conditions
            - cloud cover, humidity
            - weather condition (human-readable)
            Plus location information
        """
        if timesteps not in ['1h', '1d']:
            raise ValueError("Timesteps must be '1h' for hourly or '1d' for daily")
            
        if not 1 <= days <= 5:
            raise ValueError("Days must be between 1 and 5")
            
        params = {
            'location': location,
            'units': units,
            'timesteps': [timesteps]
        }
        
        data = self._make_request('forecast', params)
        
        if not data.get('timelines'):
            raise Exception("No forecast data received")
        
        # Calculate number of periods based on timestep
        periods = days * (24 if timesteps == '1h' else 1)
        
        timeline_key = 'hourly' if timesteps == '1h' else 'daily'
        timeline = data['timelines'][timeline_key][:periods]
        
        return {
            'forecast': self._process_timeline(timeline),
            'location': data['location']
        }

    def _get_field_units(self, field: str, unit_system: str = 'metric') -> str:
        """Get the units for a specific weather field."""
        metric_units = {
            'temperature': 'Celsius',
            'windSpeed': 'm/s',
            'windGust': 'm/s',
            'precipitationIntensity': 'mm/hr',
            'snowAccumulation': 'mm',
            'visibility': 'km',
            'pressure': 'hPa',
            'cloudBase': 'km',
            'cloudCeiling': 'km'
        }
        
        imperial_units = {
            'temperature': 'Fahrenheit',
            'windSpeed': 'mph',
            'windGust': 'mph',
            'precipitationIntensity': 'in/hr',
            'snowAccumulation': 'in',
            'visibility': 'mi',
            'pressure': 'inHg',
            'cloudBase': 'mi',
            'cloudCeiling': 'mi'
        }
        
        units = metric_units if unit_system == 'metric' else imperial_units
        return units.get(field, 'N/A')