from typing import Dict, List, Optional
import requests
import inspect

class BraveSearchTool:
    """Agent tool for web search via Brave Search API. Supports general web search,
    news filtering, and result customization. Results include titles, URLs, and 
    descriptions. Use search() for general queries, search_news() for recent content."""

    def __init__(self, api_key: str):
        """Initialize with Brave Search API key."""
        self._api_key = api_key
        self._base_url = "https://api.search.brave.com/res/v1/web/search"
        self._default_params = {
            "country": "us",
            "safesearch": "moderate",
            "search_lang": "en",
            "ui_lang": "en-US"
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

    def _make_request(self, params: Dict) -> Dict:
        """Make API request with error handling."""
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self._api_key
        }
        
        try:
            response = requests.get(self._base_url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Search request failed: {e}")

    def _format_results(self, results: Dict, count: int) -> List[Dict[str, str]]:
        """Extract and format web results."""
        formatted = []
        if "web" in results and "results" in results["web"]:
            for result in results["web"]["results"][:count]:
                formatted.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("description", "")
                })
        return formatted

    def search(self, query: str, count: int = 5) -> List[Dict[str, str]]:
        """Search web pages. Usage: query='specific search terms', count=1-10 for results.
        Returns: [{"title": str, "url": str, "description": str}, ...] ordered by relevance."""
        params = {
            **self._default_params,
            "q": query,
            "count": min(max(1, count), 10)
        }
        results = self._make_request(params)
        return self._format_results(results, count)