import spotipy
from spotipy.oauth2 import SpotifyOAuth
from typing import Optional, Dict, Any, List
import json
import webbrowser
from secret_keys import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from functools import wraps
import os
import inspect

class SpotifyTool:
    """Tool for controlling Spotify playback and getting information."""
    
    def __init__(self, client_id, client_secret, cache_path: str = ".spotify_cache"):
        """
        Initialize Spotify Tool with authentication handling.
        
        Args:
            cache_path (str): Path to store the OAuth token cache file
        """
        self.cache_path = cache_path
        self.sp = None
        self._initialize_spotify(client_id, client_secret)
    
    def _initialize_spotify(self, client_id, client_secret):
        """Initialize Spotify client with proper auth flow."""
        scope = " ".join([
            "user-read-playback-state",
            "user-modify-playback-state",
            "user-read-currently-playing",
            "playlist-read-private",
            "playlist-modify-public",
            "playlist-modify-private"
        ])
        
        try:
            # Create OAuth manager
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri="http://example.com/callback",
                scope=scope,
                cache_path=self.cache_path,
                open_browser=False
            )
            
            # Check if we have a cached token
            token_info = auth_manager.cache_handler.get_cached_token()
            
            if not token_info or auth_manager.is_token_expired(token_info):
                print("\nSpotify Authorization Required!")
                print("\nFollow these steps:")
                print("1. We'll open your browser to authorize this application")
                print("2. Log in to Spotify if needed")
                print("3. Click 'Agree' to grant access")
                print("4. You'll be redirected to a page that won't load (this is expected)")
                print("5. Copy the ENTIRE URL from your browser's address bar")
                print("   (It should start with 'http://localhost:8888/callback?code=')")
                print("\nPress Enter to open the authorization page...")
                
                auth_url = auth_manager.get_authorize_url()
                print(f"Auth URL: {auth_url}")
                input()
                
                # Get the authorization URL and open it
                webbrowser.open(auth_url)
                
                print("\nAfter authorizing, paste the URL you were redirected to:")
                response_url = input().strip()
                
                # Get the token
                code = auth_manager.parse_response_code(response_url)
                token_info = auth_manager.get_access_token(code, as_dict=False)
                
                print("Authorization successful!")
            
            # Create the Spotify client
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            
            # Verify the connection
            self.sp.current_user()
            print("\nSuccessfully connected to Spotify!")
            
        except Exception as e:
            print(f"\nError during Spotify initialization: {str(e)}")
            print("\nTroubleshooting steps:")
            print("1. Make sure you copied the entire URL from your browser")
            print("2. Check that your Spotify credentials are correct")
            print("3. Ensure you have an active internet connection")
            print("4. Try clearing the cache and reconnecting:")
            print("   spotify.clear_auth_cache()")
            raise

    def clear_auth_cache(self):
        """Clear the stored authentication cache for spotify if any error happens related to it."""
        try:
            if os.path.exists(self.cache_path):
                os.remove(self.cache_path)
                print("Authentication cache cleared successfully")
                print("Next operation will require reauthorization")
            else:
                print("No authentication cache found")
        except Exception as e:
            print(f"Error clearing cache: {str(e)}")

    def _ensure_spotify_connected(func):
        """Decorator to ensure Spotify is connected before operations."""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.sp is None:
                try:
                    self._initialize_spotify()
                except Exception as e:
                    return json.dumps({
                        "status": "error",
                        "message": f"Spotify initialization failed: {str(e)}"
                    })
            try:
                # Verify connection
                self.sp.current_user()
            except Exception:
                try:
                    self._initialize_spotify()
                except Exception as e:
                    return json.dumps({
                        "status": "error",
                        "message": f"Spotify reconnection failed: {str(e)}"
                    })
            return func(self, *args, **kwargs)
        return wrapper

    def _require_active_device(func):
        """Decorator to check if there's an active Spotify device."""
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            devices = self.sp.devices()
            if not devices['devices']:
                return json.dumps({
                    "status": "error",
                    "message": "No active Spotify devices found. Please open Spotify on a device."
                })
            return func(self, *args, **kwargs)
        return wrapper
    
    def _get_current_track_info(self) -> Dict[str, Any]:
        """Get information about the currently playing track."""
        try:
            current = self.sp.current_playback()
            if not current or not current.get('item'):
                return None
            
            track = current['item']
            return {
                "name": track['name'],
                "artist": ", ".join(artist['name'] for artist in track['artists']),
                "album": track['album']['name'],
                "duration": track['duration_ms'],
                "progress": current['progress_ms'],
                "is_playing": current['is_playing']
            }
        except Exception as e:
            return None

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

    @_ensure_spotify_connected
    @_require_active_device
    def play_pause(self):
        """Toggle current spotify music playback between play and pause states.
        
        Args: None

        Returns:
            JSON string containing:
            - Action taken (paused/resumed)
            - Current track information
            - Error message if operation fails
        """
        try:
            current = self.sp.current_playback()
            if not current:
                return json.dumps({
                    "status": "error",
                    "message": "No active playback found"
                })
            
            if current['is_playing']:
                self.sp.pause_playback()
                action = "paused"
            else:
                self.sp.start_playback()
                action = "resumed"
            
            track_info = self._get_current_track_info()
            return json.dumps({
                "status": "success",
                "action": action,
                "track_info": track_info
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    @_require_active_device
    def next_track(self) -> str:
        """Skip to next track in queue on spotify.
        
        Args: None

        Returns:
            JSON string containing:
            - Success confirmation
            - New track information
            - Error message if operation fails
        """
        try:
            self.sp.next_track()
            # Wait a moment for track to change
            import time
            time.sleep(1)
            track_info = self._get_current_track_info()
            
            return json.dumps({
                "status": "success",
                "action": "skipped_to_next",
                "track_info": track_info
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    @_require_active_device
    def previous_track(self) -> str:
        """Return to previous track on spotify.
        
        Args: None
        
        Returns:
            JSON string containing:
            - Success confirmation
            - New track information
            - Error message if operation fails
        """
        try:
            self.sp.previous_track()
            # Wait a moment for track to change
            import time
            time.sleep(1)
            track_info = self._get_current_track_info()
            
            return json.dumps({
                "status": "success",
                "action": "skipped_to_previous",
                "track_info": track_info
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    @_require_active_device
    def set_volume(self, volume: int) -> str:
        """Set the music playback volume level on spotify.
        
        Args:
            volume: Integer between 0-100 representing volume level
            
        Returns:
            JSON string containing:
            - Confirmation of volume change
            - Error message if operation fails
        """
        try:
            volume = max(0, min(100, volume))  # Ensure volume is between 0 and 100
            self.sp.volume(volume)
            return json.dumps({
                "status": "success",
                "action": "volume_set",
                "volume": volume
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_require_active_device
    @_ensure_spotify_connected
    def search_and_play(self, query: str, type: str = "track") -> str:
        """Search for and play specified content on spotify.
        
        Args:
            query: Search string to find content
            type: Content type to search for ("track", "album", "playlist")
            
        Returns:
            JSON string containing:
            - Playback confirmation and track info
            - Error message if content not found or operation fails
        """
        try:
            # Search for the item
            results = self.sp.search(q=query, type=type, limit=1)
            
            if not results[f"{type}s"]['items']:
                return json.dumps({
                    "status": "error",
                    "message": f"No {type} found for query: {query}"
                })
            
            item = results[f"{type}s"]['items'][0]
            
            # Start playback
            if type == "track":
                self.sp.start_playback(uris=[item['uri']])
            else:
                self.sp.start_playback(context_uri=item['uri'])
            
            # Wait a moment for playback to start
            import time
            time.sleep(1)
            track_info = self._get_current_track_info()
            
            return json.dumps({
                "status": "success",
                "action": f"playing_{type}",
                "query": query,
                "track_info": track_info
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })
    
    @_ensure_spotify_connected
    def get_current_playback(self) -> str:
        """Get information about currently playing music content on spotify.
        
        Args: None

        Returns:
            JSON string containing:
            - Current track/playback information
            - Status message if no active playback
            - Error message if operation fails
        """
        try:
            track_info = self._get_current_track_info()
            if not track_info:
                return json.dumps({
                    "status": "info",
                    "message": "No active playback"
                })
            
            return json.dumps({
                "status": "success",
                "track_info": track_info
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    def get_devices(self) -> str:
        """Retrieve list of user's available Spotify devices.
        
        Args: None

        Returns:
            JSON string containing:
            - List of devices with ID, name, type, active status, volume
            - Error message if no devices found or operation fails
        """
        try:
            devices = self.sp.devices()
            if not devices['devices']:
                return json.dumps({
                    "status": "error",
                    "message": "No Spotify devices found. Please open Spotify on a device."
                })
            
            formatted_devices = []
            for device in devices['devices']:
                formatted_devices.append({
                    "id": device['id'],
                    "name": device['name'],
                    "type": device['type'],
                    "is_active": device['is_active'],
                    "volume": device.get('volume_percent', 0),
                    "is_restricted": device.get('is_restricted', False)
                })
            
            return json.dumps({
                "status": "success",
                "devices": formatted_devices
            })
                
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    @_require_active_device
    def transfer_playback(self, device_id: str, force_play: bool = False) -> str:
        """Transfer playback to specified device on spotify.
        
        Args:
            device_id: Spotify device ID to transfer playback to
            force_play: Whether to force playback to start on new device
            
        Returns:
            JSON string containing:
            - Transfer confirmation and device info
            - Current track information
            - Error message if device not found or operation fails
        """
        try:
            # First check if the device exists
            devices = self.sp.devices()
            device_exists = any(d['id'] == device_id for d in devices['devices'])
            
            if not device_exists:
                return json.dumps({
                    "status": "error",
                    "message": f"Device with ID {device_id} not found. Use get_devices() to see available devices."
                })
            
            # Transfer playback
            self.sp.transfer_playback(device_id=device_id, force_play=force_play)
            
            # Wait a moment for transfer to complete
            import time
            time.sleep(1)
            
            # Get updated playback info
            current = self.sp.current_playback()
            if not current:
                return json.dumps({
                    "status": "success",
                    "message": "Playback transferred, but no active playback",
                    "device_id": device_id
                })
            
            device_info = {
                "name": current['device']['name'],
                "type": current['device']['type'],
                "volume": current['device']['volume_percent']
            }
            
            track_info = self._get_current_track_info()
            
            return json.dumps({
                "status": "success",
                "message": f"Playback transferred to {device_info['name']}",
                "device": device_info,
                "track_info": track_info,
                "is_playing": current['is_playing']
            })
                
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    def search_for_playlists(self, query: str, limit: int = 10) -> str:
        """Search for playlists by name or description on spotify.
        
        Args:
            query: Search term to find playlists
            limit: Maximum number of playlists to return (default: 10)
            
        Returns:
            JSON string containing:
            - List of matching playlists with details
            - Error message if operation fails
        """
        try:
            results = self.sp.search(q=query, type='playlist', limit=limit)
            
            playlists = []
            for item in results['playlists']['items']:
                playlists.append({
                    "name": item['name'],
                    "id": item['id'],
                    "uri": item['uri'],
                    "owner": item['owner']['display_name'],
                    "total_tracks": item['tracks']['total'],
                    "description": item.get('description', ''),
                    "is_public": item['public']
                })
            
            return json.dumps({
                "status": "success",
                "query": query,
                "matches_found": len(playlists),
                "playlists": playlists
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    def search_for_albums(self, query: str, limit: int = 10) -> str:
        """Search for albums by name or artist on spotify.
        
        Args:
            query: Search term to find albums
            limit: Maximum number of albums to return (default: 10)
            
        Returns:
            JSON string containing:
            - List of matching albums with details
            - Error message if operation fails
        """
        try:
            results = self.sp.search(q=query, type='album', limit=limit)
            
            albums = []
            for item in results['albums']['items']:
                albums.append({
                    "name": item['name'],
                    "id": item['id'],
                    "uri": item['uri'],
                    "artists": [artist['name'] for artist in item['artists']],
                    "total_tracks": item['total_tracks'],
                    "release_date": item['release_date'],
                    "type": item['album_type']  # 'album', 'single', or 'compilation'
                })
            
            return json.dumps({
                "status": "success",
                "query": query,
                "matches_found": len(albums),
                "albums": albums
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    def get_user_playlists(self, limit: int = 50) -> str:
        """Get the current user's playlists from spotify.
        
        Args:
            limit: Maximum number of playlists to return (default: 50)
            
        Returns:
            JSON string containing:
            - List of user's playlists with details
            - Error message if operation fails
        """
        try:
            results = self.sp.current_user_playlists(limit=limit)
            
            playlists = []
            for item in results['items']:
                playlists.append({
                    "name": item['name'],
                    "id": item['id'],
                    "uri": item['uri'],
                    "owner": item['owner']['display_name'],
                    "total_tracks": item['tracks']['total'],
                    "description": item.get('description', ''),
                    "is_public": item['public']
                })
            
            return json.dumps({
                "status": "success",
                "total_playlists": len(playlists),
                "playlists": playlists
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    def search_playlist(self, playlist_id: str, query: str) -> str:
        """Search for tracks within a specific playlist on spotify.
        
        Args:
            playlist_id: Spotify playlist ID, URI, or URL
            query: Search query to filter tracks
            
        Returns:
            JSON string containing:
            - List of matching tracks with details
            - Error message if operation fails
        """
        try:
            # Get all tracks from the playlist
            results = []
            tracks = self.sp.playlist_tracks(playlist_id)
            
            while tracks:
                for item in tracks['items']:
                    track = item['track']
                    # Skip None tracks (can happen with deleted songs)
                    if track is None:
                        continue
                        
                    # Create searchable string from track details
                    search_string = f"{track['name']} {' '.join(artist['name'] for artist in track['artists'])}"
                    
                    # Check if query matches track details (case-insensitive)
                    if query.lower() in search_string.lower():
                        results.append({
                            "name": track['name'],
                            "artists": [artist['name'] for artist in track['artists']],
                            "uri": track['uri'],
                            "duration_ms": track['duration_ms'],
                            "position": len(results)
                        })
                
                # Get next page of tracks if available
                if tracks['next']:
                    tracks = self.sp.next(tracks)
                else:
                    tracks = None
            
            return json.dumps({
                "status": "success",
                "query": query,
                "matches_found": len(results),
                "tracks": results
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    @_require_active_device
    def play_playlist(self, playlist_id: str, shuffle: bool = False) -> str:
        """Play a specific playlist on spotify.
        
        Args:
            playlist_id: Spotify playlist ID, URI, or URL
            shuffle: Whether to shuffle the playlist (default: False)
            
        Returns:
            JSON string containing:
            - Playback confirmation and first track info
            - Error message if operation fails
        """
        try:
            # Set shuffle state before starting playback
            self.sp.shuffle(shuffle)
            
            # Start playlist playback
            self.sp.start_playback(context_uri=f"spotify:playlist:{playlist_id}")
            
            # Wait a moment for playback to start
            import time
            time.sleep(1)
            
            # Get current track info
            track_info = self._get_current_track_info()
            
            return json.dumps({
                "status": "success",
                "action": "playing_playlist",
                "shuffle": shuffle,
                "track_info": track_info
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    @_require_active_device
    def play_album(self, album_id: str) -> str:
        """Play a specific album by album ID on spotify.
        
        Args:
            album_id: Spotify album ID, URI, or URL
            
        Returns:
            JSON string containing:
            - Playback confirmation and first track info
            - Error message if operation fails
        """
        try:
            # Start album playback
            self.sp.start_playback(context_uri=f"spotify:album:{album_id}")
            
            # Wait a moment for playback to start
            import time
            time.sleep(1)
            
            # Get current track info
            track_info = self._get_current_track_info()
            
            return json.dumps({
                "status": "success",
                "action": "playing_album",
                "track_info": track_info
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    def get_playlist_tracks(self, playlist_id: str, limit: int = 100) -> str:
        """Get a list of tracks in a spotify playlist.
        
        Args:
            playlist_id: Spotify playlist ID, URI, or URL
            limit: Maximum number of tracks to return (default: 100)
            
        Returns:
            JSON string containing:
            - List of tracks with details
            - Error message if operation fails
        """
        try:
            results = []
            tracks = self.sp.playlist_tracks(playlist_id, limit=limit)
            
            while tracks and len(results) < limit:
                for item in tracks['items']:
                    if len(results) >= limit:
                        break
                        
                    track = item['track']
                    if track is None:  # Skip deleted tracks
                        continue
                        
                    results.append({
                        "name": track['name'],
                        "artists": [artist['name'] for artist in track['artists']],
                        "uri": track['uri'],
                        "duration_ms": track['duration_ms'],
                        "added_at": item['added_at']
                    })
                
                if tracks['next'] and len(results) < limit:
                    tracks = self.sp.next(tracks)
                else:
                    tracks = None
            
            return json.dumps({
                "status": "success",
                "total_tracks": len(results),
                "tracks": results
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })

    @_ensure_spotify_connected
    def get_album_tracks(self, album_id: str) -> str:
        """Get a list of tracks in an album available in spotify.
        
        Args:
            album_id: Spotify album ID, URI, or URL
            
        Returns:
            JSON string containing:
            - List of tracks with details
            - Error message if operation fails
        """
        try:
            tracks = self.sp.album_tracks(album_id)
            results = []
            
            for track in tracks['items']:
                results.append({
                    "name": track['name'],
                    "artists": [artist['name'] for artist in track['artists']],
                    "uri": track['uri'],
                    "duration_ms": track['duration_ms'],
                    "track_number": track['track_number']
                })
            
            return json.dumps({
                "status": "success",
                "total_tracks": len(results),
                "tracks": results
            })
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": str(e)
            })
