import os
import requests
import json
from typing import Dict, List, Any, Optional
from utils import BRAVE_SEARCH_API_KEY

# Configuration
API_KEY = BRAVE_SEARCH_API_KEY

BASE_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_PARAMS = {
    "country": "us",
    "safesearch": "moderate",
    "search_lang": "en",
    "ui_lang": "en-US",
    "count": 10
}

def web_search_api(query: str, **kwargs) -> Dict[str, Any]:
    """
    Perform a web search using the Brave Search API.

    Args:
        query (str): The search query.
        **kwargs: Additional parameters to customize the search.

    Returns:
        Dict[str, Any]: The parsed JSON response from the API.
    """
    params = DEFAULT_PARAMS.copy()
    params.update(kwargs)
    params["q"] = query

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": API_KEY
    }

    try:
        response = requests.get(BASE_URL, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error occurred while making the request: {e}")
        return {}

def format_results(results: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Format the search results for better readability.

    Args:
        results (Dict[str, Any]): The raw API response.

    Returns:
        List[Dict[str, str]]: A list of formatted search results.
    """
    formatted_results = []
    if "web" in results and "results" in results["web"]:
        for result in results["web"]["results"]:
            formatted_results.append({
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "description": result.get("description", "")
            })
    return formatted_results

def display_results(results: List[Dict[str, str]]):
    """
    Display the formatted search results.

    Args:
        results (List[Dict[str, str]]): The formatted search results.
    """
    for i, result in enumerate(results, 1):
        print(f"\n--- Result {i} ---")
        print(f"Title: {result['title']}")
        print(f"URL: {result['url']}")
        print(f"Description: {result['description']}")

def main():
    """
    Main function to run the web search script.
    """
    while True:
        query = input("\nEnter your search query (or 'quit' to exit): ").strip()
        if query.lower() == 'quit':
            break

        results = web_search(query)
        formatted_results = format_results(results)
        display_results(formatted_results)

        if "mixed" in results:
            print("\nOther result types available:")
            for result_type in results["mixed"].get("main", []):
                print(f"- {result_type['type']}")

if __name__ == "__main__":
    main()