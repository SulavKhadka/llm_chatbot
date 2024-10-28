from llama_index.core.tools import FunctionTool
import requests
from geopy.geocoders import Nominatim
import mss
import mss.tools
from datetime import datetime
from PIL import Image, UnidentifiedImageError
import numpy as np
from langchain.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_community.tools.pubmed.tool import PubmedQueryRun
from langchain_community.utilities import ArxivAPIWrapper
import random
import io

from secret_keys import OPENWATHERMAP_API_TOKEN
from llm_chatbot.tools.web_search import web_search_api
from llm_chatbot.tools.python_interpreter import UVPythonShellManager
import numpy as np
from PIL import Image
import os
from typing import Union, Dict

@tool
def open_image_file(filepath: str):
    """
    Converts an image file to a NumPy array.

    This tool takes a filepath to an image, attempts to open and process the image,
    and returns the image data as a NumPy array. It's designed to handle various
    image formats supported by the Pillow library.

    Args:
        filepath (str): The full path to the image file. This should be a string
            representing a valid file path on the system where the code is running.

    Returns:
        Union[np.ndarray, Dict[str, str]]: 
        - If successful, returns a NumPy array representing the image data.
          The shape of the array will be (height, width, channels) for color images,
          or (height, width) for grayscale images.
        - If unsuccessful, returns a dictionary with error information:
          {
              'status': 'error',
              'message': 'A description of what went wrong'
          }

    Raises:
        This function doesn't raise exceptions directly. All exceptions are caught
        and returned as error dictionaries.

    Note:
        - This tool uses the Pillow library to open images, which supports a wide
          range of formats including JPEG, PNG, GIF, BMP, and more.
        - The returned NumPy array will have dtype of uint8, with values ranging
          from 0 to 255.
        - For color images, the returned array will have 3 channels (RGB) or 4 channels
          (RGBA) if the image has an alpha channel.
        - Memory usage can be high for large images, as the entire image is loaded
          into memory as a NumPy array.
        - This tool does not modify the original image file.

    Example usage:
        result = image_to_numpy('/path/to/your/image.jpg')
        if isinstance(result, np.ndarray):
            print(f"Successfully loaded image. Shape: {result.shape}")
        else:
            print(f"Error: {result['message']}")

    """
    try:
        # Check if file exists
        if not os.path.isfile(filepath):
            return {
                'status': 'error',
                'message': f"File not found: {filepath}"
            }

        # Attempt to open the image
        with Image.open(filepath) as img:
            # Convert image to RGB if it's in a different mode (e.g., RGBA)
            if img.mode != 'RGB':
                img = img.convert('RGB')
        return img

    except IOError as e:
        return {
            'status': 'error',
            'message': f"IOError: Unable to open image file. {str(e)}"
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f"An unexpected error occurred: {str(e)}"
        }
# create an agent
@tool
def get_current_weather(location: str, unit: str) -> str:
    """
    Fetch current weather data for a given location using the OpenWeatherMap API.

    This tool provides detailed weather information for a specified location. It's useful when you need 
    up-to-date weather data for a particular city or region. The tool uses geocoding to convert location 
    names into coordinates, ensuring accurate results even for less common locations.

    Args:
        location (str): The name of the location for which to fetch weather data. This can be a city name 
            or a combination of city and country code (e.g., "London" or "London,UK"). The more specific 
            the location, the more accurate the results will be.
        unit (str): The unit system for temperature and wind speed measurements. Must be one of:
            - 'standard': Temperature in Kelvin, wind speed in meters/sec
            - 'metric': Temperature in Celsius, wind speed in meters/sec
            - 'imperial': Temperature in Fahrenheit, wind speed in miles/hour

    Returns:
        str: A string representation of a dictionary containing detailed weather information. The dictionary 
        includes the following keys:
            - location (str): Name of the location as recognized by the API.
            - country (str): Two-letter country code of the location.
            - temperature (float): Current temperature in the specified unit.
            - feels_like (float): "Feels like" temperature, accounting for humidity and wind, in the specified unit.
            - humidity (int): Relative humidity percentage.
            - description (str): Brief textual description of the current weather condition.
            - wind_speed (float): Wind speed in the specified unit.
            - clouds (int): Cloudiness percentage, from 0 (clear sky) to 100 (completely cloudy).

    Raises:
        ValueError: If the OpenWeatherMap API key is not found in the environment variables.
        requests.exceptions.RequestException: If there's an error in making the API request or processing the response.

    Note:
        This tool requires a valid OpenWeatherMap API key to be set in the environment variables. 
        For best results, use clear and unambiguous location names.
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

    This tool conducts a web search using the provided query and returns a list of relevant search results. 
    It's useful for gathering information on a wide range of topics, finding recent news, or discovering 
    websites related to a specific subject.

    Args:
        query (str): The search query string. A clear and concise description of the information you're
            looking for. More specific queries tend to yield more relevant results.

    Returns:
        List[Dict]: A list of dictionaries, where each dictionary represents a single search result. 
        Each dictionary contains the following keys:
            - title (str): The title of the web page or document.
            - url (str): The full URL of the web page or document.
            - description (str): A brief excerpt or summary of the web page content, highlighting 
              relevant parts of the text that match the search query.

    Note:
        - The tool does not provide the full content of web pages, only summaries and links.
        - The relevance and order of results are determined by the search API's algorithms and 
          may not always perfectly match the user's intentions.
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
                    "age": result.get("age", "N/A")
                }
            )
    return formatted_results

@tool
def take_screenshots(save=False):
    """
    Capture screenshots of all monitors and return them as PIL Image objects.

    This tool captures screenshots from all available monitors connected to the system. 
    It's useful for capturing the content of the local screen, for visual navigation and problem solving.

    Args:
        save (bool, optional): If True, each screenshot will be saved as a PNG file in the current 
            directory. If False, screenshots are only returned as Image objects. Defaults to False.

    Returns:
        List[Image.Image]: A list of PIL Image objects, each representing a screenshot from one monitor. 
        The list is ordered by monitor number, excluding the first "all in one" virtual monitor.

    Note:
        - This tool skips the first monitor in the list, which is typically a virtual "all in one" monitor 
          that represents the combined area of all physical monitors.
        - The tool captures the entire area of each monitor, including all visible windows and the desktop.
        - If 'save' is True, screenshots are saved with filenames that include the monitor number and a 
          timestamp, e.g., "screenshot_monitor2_20230615_120530.png".
        - This tool may not work as expected in all environments, particularly those without a graphical 
          interface or with unusual monitor configurations.
        - The returned Image objects can be further processed or analyzed using PIL (Python Imaging Library) 
          functions if needed.
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
    """
    Generates an image based on a given image query.

    This tool creates a new image based on a textual description or prompt. It's useful for generating 
    custom illustrations, visualizing concepts, or creating artistic interpretations of ideas. The tool 
    uses an AI-based image generation model to produce the image.

    Args:
        None: This function doesn't take any arguments directly. The image query or prompt should be 
        provided through the context or conversation leading up to the use of this tool.

    Returns:
        None: This function doesn't return a value directly. The generated image is typically made 
        available through a side effect, such as saving to a file or displaying in the user interface.

    Note:
        - The quality and accuracy of the generated image depend on the clarity and specificity of the 
          image query provided in the conversation context.
        - The image generation process may take some time, depending on the complexity of the query and 
          the underlying model's processing speed.
        - The tool may have limitations on the types of images it can generate, based on content policies 
          and the capabilities of the underlying model.
        - The generated image is a new creation and does not represent or reproduce any existing copyrighted image.
        - If the image query is ambiguous or too complex, the result may not match the user's expectations precisely.
    """
    pass

@tool
def search_pubmed(query: str, max_result_chars: int = 2500):
    """
    Search PubMed database and return formatted results.

    This tool performs a search query on the PubMed database, which is a free resource supporting the search 
    and retrieval of biomedical and life sciences literature. It's particularly useful for finding scientific 
    articles, research papers, and medical studies on a wide range of topics in the life sciences and healthcare.

    Args:
        query (str): The search query string. This should be a clear and concise description of the topic 
            or keywords you're searching for. More specific queries tend to yield more relevant results.
        max_result_chars (int, optional): The maximum number of characters to return in the result content. 
            This helps to limit the size of the returned data. Defaults to 2500 characters.

    Returns:
        The return type is not specified in the original function, but it likely returns a list or dictionary 
        containing the search results. Each result may include details such as:
        - Title of the article
        - Authors
        - Publication date
        - Journal name
        - Abstract (if available)
        - PubMed ID
        - URL to the full article (if available)

    Note:
        - The tool uses the PubmedQueryRun class to perform the search, which may have its own specific behavior and limitations.
        - The number of results returned may be limited by the PubMed API and the max_result_chars parameter.
        - Results are typically sorted by relevance, with the most recent and most relevant articles appearing first.
        - This tool provides access to scientific literature and may return technical or complex information. 
          Interpretation of the results may require domain expertise.
        - Due to the max_result_chars limitation, full article texts are not provided, only metadata and possibly abstracts.
        - The search covers a vast database, but it may not include the very latest publications due to indexing delays.
    """
    pub = PubmedQueryRun()
    pub.api_wrapper.doc_content_chars_max = max_result_chars
    
    return pub.invoke(query)

@tool
def search_arxiv(query: str, max_result_chars: int = 2500):
    """
    Search arXiv database and return formatted results.

    This tool performs a search query on the arXiv database, which is an open-access archive for scholarly 
    articles in STEM fields. It's particularly useful for finding pre-print and published research papers
    across these disciplines.

    Args:
        query (str): The search query string. This should be a clear and concise description of the topic 
            or keywords you're searching for. More specific queries tend to yield more relevant results. 
            The query can include author names, titles, abstracts, or specific arXiv IDs.
        max_result_chars (int, optional): The maximum number of characters to return in the result content. 
            This helps to limit the size of the returned data. Defaults to 2500 characters.

    Returns:
        str: A string containing the formatted search results. The exact format may depend on the 
        ArxivAPIWrapper implementation, but typically includes:
        - Title of the paper
        - Authors
        - Published date
        - arXiv ID
        - Abstract (if available and within the max_result_chars limit)
        - URL to the full paper

    Note:
        - Results are typically sorted by relevance and date, with the most recent and most relevant 
          papers appearing first.
        - This tool provides access to scholarly articles which may be highly technical. Interpretation 
          of the results may require domain expertise.
        - Due to the max_result_chars limitation, full paper texts are not provided, only metadata 
          and possibly abstracts.
        - arXiv covers specific fields of study. If your query is outside these fields, you may not 
          get relevant results.
        - The search covers both pre-prints and published papers. Pre-prints may not have undergone 
          peer review, so results should be interpreted with this in mind.
    """
    arx = ArxivAPIWrapper()
    arx.api_wrapper.doc_content_chars_max = max_result_chars
    return arx.run(query)

@tool
def query_vlm(image_path: str, query: str) -> str:
    """
    Perform a visual query on an image using a Vision Language Model.

    This tool opens an image from a local directory and applies a specified query to that image 
    using a Vision Language Model (VLM). It's useful for tasks such as object detection, scene 
    description, text recognition in images, or answering specific questions about the image content.

    Args:
        image_path (str): The file path to the image. This should be a valid path to an image file 
            in a format supported by PIL (e.g., JPG, PNG, BMP).
        query (str): The query or question to ask about the image. This can be a description request, 
            a specific question about the image content, or any other prompt that the VLM can process.

    Returns:
        str: Either the response from the Vision Language Model based on the image and query, or 
        an error message if something went wrong. The exact format and content of the successful 
        response will depend on the query and the capabilities of the underlying VLM. Error messages 
        will describe what went wrong during the process.

    Note:
        - The performance and accuracy of the results depend on the underlying Vision Language Model, 
          which is not specified in this function.
        - The function does not modify the original image file.
        - If an error occurs (e.g., file not found, invalid image format, empty inputs), the function 
          will return an error message as a string rather than raising an exception.
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


def get_tools():
    interpreter = UVPythonShellManager()
    session = interpreter.create_session()
    tool_dict = {}
    functions = [
        get_current_weather,
        web_search,
        take_screenshots,
        search_arxiv,
        open_image_file,
        tool(interpreter.run_command),
        tool(interpreter.run_python_code)
    ]
    for fn in functions:
        tool_schema = convert_to_openai_tool(fn)
        tool_dict[tool_schema["function"]["name"]] = {"schema": tool_schema, "function": fn}
    return tool_dict