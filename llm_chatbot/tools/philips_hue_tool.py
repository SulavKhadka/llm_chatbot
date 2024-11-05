import requests
from typing import Dict, List, Optional, Union
import inspect
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

class PhilipsHueTool:
    """A tool for interacting with Philips Hue lights and scenes."""
    
    def __init__(self, bridge_ip: str, api_key: str):
        """
        Initialize the Philips Hue Tool.
        
        Args:
            bridge_ip: IP address of the Hue Bridge
            api_key: Application key for authentication
        """
        self.bridge_ip = bridge_ip
        self.api_key = api_key
        self.base_url = f"https://{bridge_ip}/clip/v2"
        self.headers = {"hue-application-key": api_key}
    
    def get_available_methods(self) -> List[Dict[str, str]]:
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
                    "signature": f"{name}{signature}"
                })
        
        return sorted(methods, key=lambda x: x["name"])

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """Make HTTP request to Hue Bridge."""
        url = f"{self.base_url}/{endpoint}"
        response = requests.request(
            method,
            url,
            headers=self.headers,
            json=data,
            verify=False  # Required for HTTPS connections to bridge
        )
        response.raise_for_status()
        return response.json() if response.text else {}

    def get_all_lights(self) -> Dict:
        """Get information about all lights."""
        return self._make_request("GET", "resource/light")
    
    def get_all_rooms(self) -> Dict:
        """Get information about all rooms."""
        return self._make_request("GET", "resource/room")
    
    def get_all_scenes(self) -> Dict:
        """Get information about all scenes."""
        return self._make_request("GET", "resource/scene")

    def control_light(self, light_id: str, **kwargs) -> Dict:
        """
        Control a specific light with various parameters.
        
        Args:
            light_id: ID of the light to control
            **kwargs: Supported parameters:
                - on (bool): Turn light on/off
                - brightness (int, 1-100): Set brightness percentage
                - color_temp (int, 153-500): Set color temperature in mirek
                - xy_color (tuple): Set color using xy coordinates (x, y)
                - transition_time (int): Transition duration in milliseconds
        """
        data = {}
        
        if "on" in kwargs:
            data["on"] = {"on": kwargs["on"]}
        
        if "brightness" in kwargs:
            data["dimming"] = {"brightness": max(1, min(100, kwargs["brightness"]))}
            
        if "color_temp" in kwargs:
            data["color_temperature"] = {
                "mirek": max(153, min(500, kwargs["color_temp"]))
            }
            
        if "xy_color" in kwargs:
            x, y = kwargs["xy_color"]
            data["color"] = {
                "xy": {
                    "x": max(0, min(1, x)),
                    "y": max(0, min(1, y))
                }
            }
            
        if "transition_time" in kwargs:
            data["dynamics"] = {"duration": kwargs["transition_time"]}
            
        return self._make_request("PUT", f"resource/light/{light_id}", data)

    def create_scene(self, room_id: str, name: str, lights_settings: List[Dict]) -> Dict:
        """
        Create a new scene for a room.
        
        Args:
            room_id: ID of the room
            name: Name for the scene
            lights_settings: List of dictionaries containing light settings
                Each dict should have:
                - light_id: ID of the light
                - settings: Dict with supported parameters (on, brightness, color_temp, xy_color)
        """
        actions = []
        for light in lights_settings:
            action = {
                "target": {
                    "rid": light["light_id"],
                    "rtype": "light"
                },
                "action": {}
            }
            
            settings = light["settings"]
            if "on" in settings:
                action["action"]["on"] = {"on": settings["on"]}
            if "brightness" in settings:
                action["action"]["dimming"] = {"brightness": settings["brightness"]}
            if "color_temp" in settings:
                action["action"]["color_temperature"] = {"mirek": settings["color_temp"]}
            if "xy_color" in settings:
                action["action"]["color"] = {
                    "xy": {
                        "x": settings["xy_color"][0],
                        "y": settings["xy_color"][1]
                    }
                }
            
            actions.append(action)
        
        data = {
            "type": "scene",
            "metadata": {"name": name},
            "actions": actions
        }
        
        return self._make_request("POST", "resource/scene", data)

    def activate_scene(self, scene_id: str, duration: Optional[int] = None) -> Dict:
        """
        Activate a scene.
        
        Args:
            scene_id: ID of the scene to activate
            duration: Optional transition duration in milliseconds
        """
        data = {
            "recall": {
                "action": "active"
            }
        }
        if duration is not None:
            data["recall"]["duration"] = duration
            
        return self._make_request("PUT", f"resource/scene/{scene_id}", data)

    def control_room_lights(self, room_id: str, **kwargs) -> Dict:
        """
        Control all lights in a room simultaneously.
        
        Args:
            room_id: ID of the room
            **kwargs: Same parameters as control_light method
        """
        data = {}
        
        if "on" in kwargs:
            data["on"] = {"on": kwargs["on"]}
        
        if "brightness" in kwargs:
            data["dimming"] = {"brightness": max(1, min(100, kwargs["brightness"]))}
            
        if "color_temp" in kwargs:
            data["color_temperature"] = {
                "mirek": max(153, min(500, kwargs["color_temp"]))
            }
            
        if "xy_color" in kwargs:
            x, y = kwargs["xy_color"]
            data["color"] = {
                "xy": {
                    "x": max(0, min(1, x)),
                    "y": max(0, min(1, y))
                }
            }
            
        return self._make_request("PUT", f"resource/grouped_light/{room_id}", data)

    def get_light_state(self, light_id: str) -> Dict:
        """Get the current state of a specific light."""
        return self._make_request("GET", f"resource/light/{light_id}")

    def start_light_effect(self, light_id: str, effect: str) -> Dict:
        """
        Start a light effect.
        
        Args:
            light_id: ID of the light
            effect: One of: 'prism', 'opal', 'glisten', 'sparkle', 'fire', 'candle'
        """
        data = {
            "effects": {
                "effect": effect
            }
        }
        return self._make_request("PUT", f"resource/light/{light_id}", data)

    def stop_light_effect(self, light_id: str) -> Dict:
        """Stop any running effect on a light."""
        data = {
            "effects": {
                "effect": "no_effect"
            }
        }
        return self._make_request("PUT", f"resource/light/{light_id}", data)