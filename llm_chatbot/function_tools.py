from llama_index.core.tools import FunctionTool
import requests
from geopy.geocoders import Nominatim
import mss
import mss.tools
from datetime import datetime
from PIL import Image
import numpy as np
from langchain.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
import random

from secret_keys import OPENWATHERMAP_API_TOKEN
from llm_chatbot.tools.web_search import web_search_api

# create an agent


@tool
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
        raise ValueError(
            "OpenWeatherMap API key not found. Make sure it's set in your .env file."
        )

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
            "clouds": data["clouds"]["all"],
        }

        return str(weather_info)

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while fetching weather data: {e}")
        return None


@tool
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
            formatted_results.append(
                {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("description", ""),
                }
            )
    return formatted_results


@tool
def take_screenshots(save=False):
    """
    Capture screenshots of all monitors and return them as PIL Image objects.

    This function uses the MSS (Multiple Screen Shot) library to capture screenshots
    from all available monitors. It skips the first monitor in the list, which is
    typically a virtual "all in one" monitor. Each screenshot is converted to a
    PIL Image object for easy manipulation and processing.

    Args:
        save (bool, optional): If True, save each screenshot as a PNG file.
            Defaults to False.

    Returns:
        List[Image.Image]: A list of PIL Image objects, each representing a
        screenshot from one monitor. The list is ordered by monitor number.
    """
    # Create an instance of mss
    with mss.mss() as sct:
        # List to store PIL images
        screenshots = []

        # Iterate through all monitors
        for monitor in sct.monitors[
            1:
        ]:  # Skip the first monitor (usually represents the "all in one" virtual monitor)
            # Capture the screen
            screenshot = sct.grab(monitor)

            # Convert to PIL Image
            img = Image.fromarray(np.array(screenshot))

            screenshots.append(img)

            if save:
                # Generate a unique filename with timestamp and monitor number
                filename = f"screenshot_monitor{monitor['monitor']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

                # Save the screenshot
                img.save(filename)
                print(f"Screenshot saved as {filename}")

    return screenshots


@tool
def generate_image():
    """Generates an image given a image query"""
    pass


@tool
def add_2_nums(x: int, y: int) -> int:
    """
    Add 2 numbers and return the sum.

    Args:
        x (int): first integer to add
        y (int): next ingeter to add
    
    Returns:
        int: the sum of x and y
    """

    return x+y

@tool
def get_random_number(st: int= 1, end: int= 100) -> int:
    """
    Get a random integer, within a range if provided but not required, default range is 1-100.

	Args:
	    st (int, optional): start of the range. Defaults to 1
	    end (int, optional): end of the range. Defaults to 100
    
    Returns:
        int: a random number between st and end
    """

    return random.randrange(st, end)


def get_tool_list_prompt(tools):
    tool_desc_list = []
    for name, tool_fn in tools.items():
        fn_desc = tool_fn["schema"]["function"]["description"]
        fn_desc = fn_desc.replace("\n", "\n\t")
        tool_desc_list.append(f"- {name}: {fn_desc}")
    return "\n\n".join(tool_desc_list)


def get_tools():
    tool_dict = {}
    functions = [
        get_current_weather,
        web_search,
        take_screenshots,
        add_2_nums,
        get_random_number
    ]
    for fn in functions:
        tool_schema = convert_to_openai_tool(fn)
        tool_dict[tool_schema["function"]["name"]] = {"schema": tool_schema, "function": fn}
    return tool_dict