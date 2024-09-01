from llama_index.core.tools import FunctionTool
import requests
from geopy.geocoders import Nominatim
from secret_keys import OPENWATHERMAP_API_TOKEN
from llm_chatbot.tools.web_search import web_search_api

# create an agent
def get_current_weather(location: str, unit: str) -> str:
    """
    Fetch current weather data for a given location using the OpenWeatherMap API.

    Args:
        location (str): City name or city name and country code divided by comma (e.g., "London,UK").
        unit (str): Units of measurement. Must be one of 'standard', 'metric', or 'imperial'.

    Returns:
        dict: A dictionary containing weather information with the following keys:
            - location (str): Name of the location.
            - country (str): Country code.
            - temperature (float): Current temperature in the specified unit.
            - feels_like (float): "Feels like" temperature in the specified unit.
            - humidity (int): Humidity percentage.
            - description (str): Brief description of the weather condition.
            - wind_speed (float): Wind speed in the specified unit.
            - clouds (int): Cloudiness percentage.
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

def web_search(query: str):
    """
    Perform a web search and return formatted results.

    Args:
        query (str): The search query string.

    Returns:
        list: A list of dictionaries containing search results. Each dictionary has the following keys:
            - title (str): The title of the search result.
            - url (str): The URL of the search result.
            - description (str): A brief description or snippet of the search result.
    """
    results = web_search_api(query)
    
    formatted_results = []
    if "web" in results and "results" in results["web"]:
        for result in results["web"]["results"]:
            formatted_results.append({
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "description": result.get("description", "")
            })
    return formatted_results


def generate_image():
    """Generates an image given a image query"""
    pass

functions = {
    "get_current_weather": FunctionTool.from_defaults(fn=get_current_weather), 
    "web_search": FunctionTool.from_defaults(fn=web_search)
}