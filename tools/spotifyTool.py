import os
from collections import defaultdict
from dotenv import load_dotenv
from spotipy import Spotify
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler


load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
scopes = os.getenv("SCOPES")
redirect_uri = os.getenv("REDIRECT_URI")
cache_handler = CacheFileHandler(cache_path='cache')


class SpotifyTool:
    def __init__(self, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, redirect_uri, scopes, cache_handler):
        self.spotify_oauth = SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=redirect_uri, scope=scopes, show_dialog=True, cache_handler=cache_handler)
        self.client = Spotify(auth_manager=self.spotify_oauth)
        self.metrics = defaultdict(int)

    def mark_call(self, method_name: str):
        self.metrics["calls_total"] += 1
        self.metrics[f"{method_name}_calls"] += 1

    def mark_success(self, method_name: str):
        self.metrics["success_total"] += 1
        self.metrics[f"{method_name}_success"] += 1

    def mark_error(self, method_name: str):
        self.metrics["errors_total"] += 1
        self.metrics[f"{method_name}_errors"] += 1

    def mark_validation_error(self, method_name: str):
        self.metrics["validation_errors_total"] += 1
        self.metrics[f"{method_name}_validation_errors"] += 1

    def mark_no_device(self, method_name: str):
        self.metrics["no_device_total"] += 1
        self.metrics[f"{method_name}_no_device"] += 1

    def get_metrics(self):
        return dict(self.metrics)
        
    def get_user_playlists(self):
        method = "get_user_playlists"
        self.mark_call(method)
        try:
            playlists = self.client.current_user_playlists()
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while fetching playlists: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while fetching playlists: {e}"

        if not playlists or not playlists.get('items'):
            self.metrics[f"{method}_empty"] += 1
            return "No playlists found for this user."

        self.mark_success(method)
        return playlists['items']
    

    def play_next_song(self):
        method = "play_next_song"
        self.mark_call(method)
        try:
            devices = self.client.devices().get('devices', [])
            if not devices:
                self.mark_no_device(method)
                return "No Spotify device found. Open Spotify first."
            self.client.next_track()
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while skipping to next song: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while skipping to next song: {e}"

        self.mark_success(method)
        return "Skipped to the next song."

    def play_previous_song(self):
        method = "play_previous_song"
        self.mark_call(method)
        try:
            devices = self.client.devices().get('devices', [])
            if not devices:
                self.mark_no_device(method)
                return "No Spotify device found. Open Spotify first."
            self.client.previous_track()
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while going to previous song: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while going to previous song: {e}"

        self.mark_success(method)
        return "Went back to the previous song."

    def play_this_song(self, song_name):
        method = "play_this_song"
        self.mark_call(method)
        if not song_name or not song_name.strip():
            self.mark_validation_error(method)
            return "Please provide a valid song name."

        try:
            results = self.client.search(q=song_name, type='track')
            items = results.get('tracks', {}).get('items', [])
            if not items:
                self.metrics[f"{method}_no_results"] += 1
                return f"No track found for '{song_name}'."

            uri = items[0]['uri']
            track_name = items[0].get('name', song_name)

            devices = self.client.devices().get('devices', [])
            if not devices:
                self.mark_no_device(method)
                return "No Spotify device found. Open Spotify first."

            device_id = devices[0]['id']
            self.client.start_playback(device_id=device_id, uris=[uri])
            self.mark_success(method)
            return f"Playing {track_name}."
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while playing song: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while playing song: {e}"

    def play_my_playlist(self, playlist_name):
        method = "play_my_playlist"
        self.mark_call(method)
        if not playlist_name or not playlist_name.strip():
            self.mark_validation_error(method)
            return "Please provide a valid playlist name."

        try:
            playlists = self.client.current_user_playlists()
            items = playlists.get('items', []) if playlists else []
            if not items:
                self.metrics[f"{method}_empty_library"] += 1
                return "You don't have any playlists."

            for playlist in items:
                if playlist['name'].lower() == playlist_name.lower():
                    uri = playlist['uri']

                    devices = self.client.devices().get('devices', [])
                    if not devices:
                        self.mark_no_device(method)
                        return "No Spotify device found. Open Spotify first."

                    device_id = devices[0]['id']

                    self.client.transfer_playback(device_id=device_id, force_play=True)
                    self.client.start_playback(device_id=device_id, context_uri=uri)
                    self.mark_success(method)
                    return f"Playing {playlist['name']}"

            self.metrics[f"{method}_not_found"] += 1
            return f"Playlist '{playlist_name}' not found in your library."
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while playing playlist: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while playing playlist: {e}"

    def play_playlist(self, playlist_name):
        method = "play_playlist"
        self.mark_call(method)
        if not playlist_name or not playlist_name.strip():
            self.mark_validation_error(method)
            return "Please provide a valid playlist name."

        try:
            results = self.client.search(q=playlist_name, type='playlist')
            items = results.get('playlists', {}).get('items', []) if results else []
            items = [p for p in items if p]
            if not items:
                self.metrics[f"{method}_no_results"] += 1
                return f"No playlist found for '{playlist_name}'."

            uri = items[0]['uri']
            name = items[0].get('name', playlist_name)

            devices = self.client.devices().get('devices', [])
            if not devices:
                self.mark_no_device(method)
                return "No Spotify device found. Open Spotify first."

            device_id = devices[0]['id']
            self.client.start_playback(device_id=device_id, context_uri=uri)
            self.mark_success(method)
            return f"Playing playlist '{name}'."
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while playing playlist: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while playing playlist: {e}"

    def add_in_queue(self, song_name):
        method = "add_in_queue"
        self.mark_call(method)
        if not song_name or not song_name.strip():
            self.mark_validation_error(method)
            return "Please provide a valid song name."

        try:
            results = self.client.search(q=song_name, type='track')
            items = results.get('tracks', {}).get('items', []) if results else []
            if not items:
                self.metrics[f"{method}_no_results"] += 1
                return f"No track found for '{song_name}'."

            uri = items[0]['uri']
            track_name = items[0].get('name', song_name)

            devices = self.client.devices().get('devices', [])
            if not devices:
                self.mark_no_device(method)
                return "No Spotify device found. Open Spotify first."

            device_id = devices[0]['id']
            self.client.add_to_queue(uri, device_id=device_id)
            self.mark_success(method)
            return f"Added '{track_name}' to the queue."
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while adding to queue: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while adding to queue: {e}"

    def remove_from_queue(self, song_name):
        method = "remove_from_queue"
        self.mark_call(method)
        if not song_name or not song_name.strip():
            self.mark_validation_error(method)
            return "Please provide a valid song name."

        try:
            queue_data = self.client.queue()
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while reading queue: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while reading queue: {e}"

        queue_items = queue_data.get('queue', []) if queue_data else []
        if not queue_items:
            self.metrics[f"{method}_empty_queue"] += 1
            return "Queue is empty."

        normalized = song_name.strip().lower()
        matching_item = next(
            (track for track in queue_items if track.get('name', '').strip().lower() == normalized),
            None,
        )

        if not matching_item:
            self.metrics[f"{method}_not_found"] += 1
            return f"'{song_name}' is not currently in the queue."

        self.mark_success(method)
        return "Spotify Web API does not support removing a specific song from queue."
    
    def pause_song(self):
        method = "pause_song"
        self.mark_call(method)
        try:
            self.client.pause_playback()
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while pausing song: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while pausing song: {e}"

        self.mark_success(method)
        return "Paused the song."

    def resume_song(self):
        method = "resume_song"
        self.mark_call(method)
        try:
            self.client.start_playback()
        except SpotifyException as e:
            self.mark_error(method)
            return f"Spotify error while resuming song: {e}"
        except Exception as e:
            self.mark_error(method)
            return f"Unexpected error while resuming song: {e}"

        self.mark_success(method)
        return "Resumed the song."


if __name__ == "__main__":
    spotify_tool = SpotifyTool(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, redirect_uri, scopes, cache_handler)
    print(spotify_tool.play_next_song())



    # todo: pick active device