import inspect
from llama_index.core.tools import FunctionTool
import requests
from geopy.geocoders import Nominatim
import mss
import mss.tools
from datetime import datetime
from PIL import Image, UnidentifiedImageError
import numpy as np
from langchain.tools import tool, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_community.tools.pubmed.tool import PubmedQueryRun
from langchain_community.utilities import ArxivAPIWrapper
from secret_keys import (
    OPENWATHERMAP_API_TOKEN,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    HUE_USER,
    HUE_BRIDGE_IP,
)
from llm_chatbot.tools.web_search import web_search_api
from llm_chatbot.tools.python_interpreter import UVPythonShellManager
from llm_chatbot.tools.spotify_control import SpotifyTool
from llm_chatbot.tools.philips_hue_tool import PhilipsHueTool
from llm_chatbot.tools.notifier_tool import NotifierTool
import numpy as np
from PIL import Image
import os
import json
from typing import Union, Dict
import openai
from secret_keys import OPENROUTER_API_KEY

@tool
def open_image_file(filepath: str):
    """Converts image file to NumPy array. Handles JPEG, PNG, GIF, BMP via Pillow library.

    Args:
        filepath (str): Path to image file

    Returns:
        - np.ndarray: Image data as (height, width, channels) array, uint8 (0-255)
        - Dict: Error info if failed {'status': 'error', 'message': str}

    RGB/RGBA images return 3/4 channels. Large images may use significant memory.
    """
    try:
        # Check if file exists
        if not os.path.isfile(filepath):
            return {"status": "error", "message": f"File not found: {filepath}"}

        # Attempt to open the image
        with Image.open(filepath) as img:
            # Convert image to RGB if it's in a different mode (e.g., RGBA)
            if img.mode != "RGB":
                img = img.convert("RGB")
        return img

    except IOError as e:
        return {
            "status": "error",
            "message": f"IOError: Unable to open image file. {str(e)}",
        }
    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred: {str(e)}"}


# create an agent
@tool
def get_current_weather(location: str, unit: str) -> str:
    """Fetches current weather data using OpenWeatherMap API.

    Args:
        location (str): City name or "City,CountryCode" (e.g. "London,UK")
        unit (str): 'standard' (Kelvin), 'metric' (Celsius), or 'imperial' (Fahrenheit)

    Returns:
        str: Dict as string with:
            {location, country, temperature, feels_like, humidity,
            description, wind_speed, clouds}

    Requires OpenWeatherMap API key in environment. Uses geocoding for location accuracy.
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
    """Performs web search and returns formatted results.

    Args:
        query (str): Search query string

    Returns:
        List[Dict]: Search results with:
            - title: Page title
            - url: Full URL
            - description: Content excerpt
            - age: Result age

    Results ordered by relevance from search API algorithm.
    """
    results = web_search_api(query)

    formatted_results = []
    if "web" in results and "results" in results["web"]:
        for result in results["web"]["results"]:
            formatted_results.append(
                {
                    "title": result.get("title", "N/A"),
                    "url": result.get("url", "N/A"),
                    "description": result.get("description", "N/A"),
                    "age": result.get("age", "N/A"),
                }
            )
    return formatted_results


@tool
def take_screenshots(save=False):
    """Captures screenshots from all monitors as PIL Images.

    Args:
        save (bool): If True, saves PNGs with timestamp (default: False)

    Returns:
        List[Image.Image]: Screenshots from each monitor (excludes virtual monitor)

    Captures entire monitor areas including windows/desktop. Uses MSS for capture.
    """
    # Create an instance of mss
    with mss.mss() as sct:
        # List to store PIL images
        screenshots = []

        # Iterate through all monitors
        # Skip the first monitor (usually represents the "all in one" virtual monitor)
        for monitor in sct.monitors[1:]:
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
    """Creates image from textual description using AI model.

    Returns:
        None: Image delivered via side effect (file/UI)

    AI generation process may take time. Output quality depends on prompt clarity.
    """
    pass


@tool
def search_pubmed(query: str, max_result_chars: int = 2500):
    """Searches PubMed biomedical/life sciences literature database.

    Args:
        query (str): Search terms/keywords
        max_result_chars (int): Max chars in result (default: 2500)

    Returns metadata/abstracts for matching articles: title, authors, date, journal, PMID, URL.
    Recent results prioritized. Full texts not included.
    """
    pub = PubmedQueryRun()
    pub.api_wrapper.doc_content_chars_max = max_result_chars

    return pub.invoke(query)


@tool
def search_arxiv(query: str, max_result_chars: int = 2500):
    """Searches arXiv STEM research paper database.

    Args:
        query (str): Search terms/keywords/authors/IDs
        max_result_chars (int): Max chars in result (default: 2500)

    Returns:
        str: Formatted string with paper metadata: title, authors, date, ID, abstract, URL

    Includes both preprints and published papers, sorted by relevance/date.
    """
    arx = ArxivAPIWrapper()
    arx.api_wrapper.doc_content_chars_max = max_result_chars
    return arx.run(query)


@tool
def query_vlm(image_path: str, query: str) -> str:
    """Analyzes image using Vision Language Model.

    Args:
        image_path (str): Path to image file (supports PIL formats)
        query (str): Question/prompt about image content

    Returns:
        str: VLM response or error message

    Handles object detection, scene description, text recognition, and visual Q&A.
    """
    from llm_chatbot.tools.vlm_image_processor import query_image

    try:
        if not image_path.strip():
            raise ValueError("Image path cannot be empty.")
        if not query.strip():
            raise ValueError("Query cannot be empty.")

        image = Image.open(image_path)
        result = query_image(image, query)
        return result

    except FileNotFoundError:
        return "Error: The specified image file does not exist. Please check the file path and try again."
    except UnidentifiedImageError:
        return "Error: The file exists but is not a valid image format. Please ensure you're using a supported image file."
    except ValueError as e:
        return f"Error: {str(e)}"
    except RuntimeError:
        return "Error: There was a problem processing the image or query. Please try again or check your inputs."
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


def get_tool_list_prompt(tools):
    tool_desc_list = []
    for name, tool_fn in tools.items():
        fn_desc = tool_fn["schema"]["function"]["description"]
        fn_desc = fn_desc.replace("\n", "\n\t")
        tool_desc_list.append(f"- {name}: {fn_desc}")
    return "\n\n".join(tool_desc_list)


def get_tools_overview(available_method_sets):
    # all this does is filter out the key, value pair of the actual func passed in from the tool class(its not serializable for the prompt)
    tools = [
        [
            {
                "name": fn_dict["name"],
                "docstring": fn_dict["docstring"],
                "signature": fn_dict["signature"],
            }
            for fn_dict in bot_tool._get_available_methods()
        ]
        for bot_tool in available_method_sets
        if isinstance(bot_tool, StructuredTool) is False
    ]

    tools.extend(
        [
            {
                "name": bot_tool.name,
                "docstring": bot_tool.func.__doc__,
                "signature": str(inspect.signature(bot_tool.func)),
            }
            for bot_tool in available_method_sets
            if isinstance(bot_tool, StructuredTool)
        ]
    )

    tool_overview_prompt = "".join(
        [
            "<tool_method_set>" + json.dumps(tool) + "</tool_method_set>"
            for tool in tools
        ]
    )
    prompt = f'''<|begin_of_text|><|start_header_id|>system<|end_header_id|>
You are to analyze the set of methods, given below, that are a components/facets of the same tool/functionality. The main task at hand is to output a detailed overview of the overall tools and the functionality they offer with all the methods each has in the format specified below. The summary should be concise yet detailed. Refer to the tool method set to properly understand and relay their functionality and the capability of the tool as a whole better in your description. You are to only output one {{tool: description}} pair per <tool_method_set> capturing the whole set of methods and their capabilities.

## Output Format
Your output should always be valid JSON in this format:
[{{
    "tool_name": "<name of tool set>",
    "description": "<detailed yet concise description outlining/highlighting the tools functions>"
}},
{{
    "tool_name": "<name of tool set>",
    "description": "<detailed yet concise description outlining/highlighting the tools functions>"
}}]<|eot_id|><|start_header_id|>user<|end_header_id|>Below is a group of tool method sets:\n{tool_overview_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>[{{"tool_name":"'''

    openai_client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    prompt_completion = openai_client.completions.create(
        model="meta-llama/llama-3.1-70b-instruct",
        prompt=prompt,
        max_tokens=4096,
        temperature=0.1
    )
    tools_overview = '''[{"tool_name":"''' + prompt_completion.choices[0].text
    print(tools_overview)
    return tools_overview

def get_tools():
    # Initalize tools
    interpreter = UVPythonShellManager()
    session = interpreter.create_session()

    spotify = SpotifyTool(
        client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET
    )
    hue_tool = PhilipsHueTool(bridge_ip=HUE_BRIDGE_IP, api_key=HUE_USER)

    notifier_tool = NotifierTool()
    
    tools = [
        get_current_weather,
        web_search,
        take_screenshots,
        search_arxiv,
        open_image_file,
        notifier_tool,
        interpreter,
        spotify,
        hue_tool
    ]

    tool_dict = {}
    tool_dict["overview"] = get_tools_overview(tools)

    for bot_tool in tools:
        tool_methods = []
        if isinstance(bot_tool, StructuredTool):
            tool_schema = convert_to_openai_tool(bot_tool)
            tool_dict[tool_schema["function"]["name"]] = {
                "tool_desc": bot_tool.func.__doc__,
                "schema": tool_schema,
                "function": bot_tool,
            }
        else:        
            for fn in bot_tool._get_available_methods():
                tool_schema = convert_to_openai_tool(tool(fn['func']))
                tool_dict[tool_schema["function"]["name"]] = {
                    "tool_desc": bot_tool.__doc__,
                    "schema": tool_schema,
                    "function": tool(fn['func']),
                }
    return tool_dict




# functions = [
#         get_current_weather,
#         web_search,
#         take_screenshots,
#         search_arxiv,
#         open_image_file,
#         tool(interpreter.run_command),
#         tool(interpreter.run_python_code),
#         tool(spotify.get_current_playback),
#         tool(spotify.next_track),
#         tool(spotify.play_pause),
#         tool(spotify.previous_track),
#         tool(spotify.search_and_play),
#         tool(spotify.set_volume),
#         tool(spotify.get_devices),
#         tool(spotify.search_for_playlists),
#         tool(spotify.search_for_albums),
#         tool(spotify.get_user_playlists),
#         tool(spotify.search_playlist),
#         tool(spotify.play_playlist),
#         tool(spotify.play_album),
#         tool(spotify.get_playlist_tracks),
#         tool(spotify.get_album_tracks),
#         tool(spotify.transfer_playback),
#         tool(hue_tool.control_light),
#         tool(hue_tool.activate_scene),
#         tool(hue_tool.control_room_lights),
#         tool(hue_tool.get_all_lights),
#         tool(hue_tool.get_all_rooms),
#         tool(hue_tool.get_all_scenes),
#         tool(hue_tool.get_light_state),
#     ]
    