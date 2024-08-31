from llama_index.core.tools import FunctionTool
import requests
from geopy.geocoders import Nominatim
from secret_keys import OPENWATHERMAP_API_TOKEN

# create an agent
def get_current_weather(location: str, unit: str) -> str:
    """
    Fetch current weather data for a given location using the OpenWeatherMap API.
    
    :param location: City name or city name and country code divided by comma (e.g. "London,UK")
    :param unit: Units of measurement. 'standard', 'metric' and 'imperial' units are available.
    """
    # API endpoint
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    
    # Get API key from environment variable
    api_key = OPENWATHERMAP_API_TOKEN
    
    if not api_key:
        raise ValueError("OpenWeatherMap API key not found. Make sure it's set in your .env file.")
    
    geolocator = Nominatim(user_agent="weather_boi")
    location = geolocator.geocode(location)

    # Parameters for the API request
    params = {
        "lat": location.latitude,
        "lon": location.longitude,
        "units": unit,  # For temperature in Celsius
        "appid": api_key,
    }
    
    try:
        # Make the API request
        response = requests.get(base_url, params=params)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        # Parse the JSON response
        data = response.json()
        print(data)
        # Extract relevant information
        weather_info = {
            "location": data["name"],
            "country": data["sys"]["country"],
            "temperature": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"],
            "wind_speed": data["wind"]["speed"],
            "clouds": data["clouds"]["all"]
        }
        
        return weather_info
    
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching weather data: {e}")
        return None

def get_current_traffic(location: str) -> str:
    """Returns the secret fact."""
    if location.lower() == "seattle":
        return "just take the bus lil bro"
    else:
        return "I only help seattle ppl and traffic probably sucks where you are"

def google_search(query: str):
    """Gets search results from web"""
    pass

def generate_image():
    """Generates an image given a image query"""
    pass

functions = {
    "get_current_weather": FunctionTool.from_defaults(fn=get_current_weather), 
    "get_current_traffic": FunctionTool.from_defaults(fn=get_current_traffic)
}