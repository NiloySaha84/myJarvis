import os
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
        
    def get_user_playlists(self):
        try:
            playlists = self.client.current_user_playlists()
        except SpotifyException as e:
            return f"Spotify error while fetching playlists: {e}"
        except Exception as e:
            return f"Unexpected error while fetching playlists: {e}"

        if not playlists or not playlists.get('items'):
            return "No playlists found for this user."

        return playlists['items']
    

    def play_next_song(self):
        try:
            devices = self.client.devices().get('devices', [])
            if not devices:
                return "No Spotify device found. Open Spotify first."
            self.client.next_track()
        except SpotifyException as e:
            return f"Spotify error while skipping to next song: {e}"
        except Exception as e:
            return f"Unexpected error while skipping to next song: {e}"

        return "Skipped to the next song."

    def play_previous_song(self):
        try:
            devices = self.client.devices().get('devices', [])
            if not devices:
                return "No Spotify device found. Open Spotify first."
            self.client.previous_track()
        except SpotifyException as e:
            return f"Spotify error while going to previous song: {e}"
        except Exception as e:
            return f"Unexpected error while going to previous song: {e}"

        return "Went back to the previous song."

    def play_this_song(self, song_name):
        if not song_name or not song_name.strip():
            return "Please provide a valid song name."

        try:
            results = self.client.search(q=song_name, type='track')
            items = results.get('tracks', {}).get('items', [])
            if not items:
                return f"No track found for '{song_name}'."

            uri = items[0]['uri']
            track_name = items[0].get('name', song_name)

            devices = self.client.devices().get('devices', [])
            if not devices:
                return "No Spotify device found. Open Spotify first."

            device_id = devices[0]['id']
            self.client.start_playback(device_id=device_id, uris=[uri])
            return f"Playing {track_name}."
        except SpotifyException as e:
            return f"Spotify error while playing song: {e}"
        except Exception as e:
            return f"Unexpected error while playing song: {e}"

    def play_my_playlist(self, playlist_name):
        if not playlist_name or not playlist_name.strip():
            return "Please provide a valid playlist name."

        try:
            playlists = self.client.current_user_playlists()
            items = playlists.get('items', []) if playlists else []
            if not items:
                return "You don't have any playlists."

            for playlist in items:
                if playlist['name'].lower() == playlist_name.lower():
                    uri = playlist['uri']

                    devices = self.client.devices().get('devices', [])
                    if not devices:
                        return "No Spotify device found. Open Spotify first."

                    device_id = devices[0]['id']

                    self.client.transfer_playback(device_id=device_id, force_play=True)
                    self.client.start_playback(device_id=device_id, context_uri=uri)
                    return f"Playing {playlist['name']}"

            return f"Playlist '{playlist_name}' not found in your library."
        except SpotifyException as e:
            return f"Spotify error while playing playlist: {e}"
        except Exception as e:
            return f"Unexpected error while playing playlist: {e}"

    def play_playlist(self, playlist_name):
        if not playlist_name or not playlist_name.strip():
            return "Please provide a valid playlist name."

        try:
            results = self.client.search(q=playlist_name, type='playlist')
            items = results.get('playlists', {}).get('items', []) if results else []
            items = [p for p in items if p]
            if not items:
                return f"No playlist found for '{playlist_name}'."

            uri = items[0]['uri']
            name = items[0].get('name', playlist_name)

            devices = self.client.devices().get('devices', [])
            if not devices:
                return "No Spotify device found. Open Spotify first."

            device_id = devices[0]['id']
            self.client.start_playback(device_id=device_id, context_uri=uri)
            return f"Playing playlist '{name}'."
        except SpotifyException as e:
            return f"Spotify error while playing playlist: {e}"
        except Exception as e:
            return f"Unexpected error while playing playlist: {e}"

    def add_in_queue(self, song_name):
        if not song_name or not song_name.strip():
            return "Please provide a valid song name."

        try:
            results = self.client.search(q=song_name, type='track')
            items = results.get('tracks', {}).get('items', []) if results else []
            if not items:
                return f"No track found for '{song_name}'."

            uri = items[0]['uri']
            track_name = items[0].get('name', song_name)

            devices = self.client.devices().get('devices', [])
            if not devices:
                return "No Spotify device found. Open Spotify first."

            device_id = devices[0]['id']
            self.client.add_to_queue(uri, device_id=device_id)
            return f"Added '{track_name}' to the queue."
        except SpotifyException as e:
            return f"Spotify error while adding to queue: {e}"
        except Exception as e:
            return f"Unexpected error while adding to queue: {e}"

    def remove_from_queue(self, song_name):
        if not song_name or not song_name.strip():
            return "Please provide a valid song name."

        try:
            queue_data = self.client.queue()
        except SpotifyException as e:
            return f"Spotify error while reading queue: {e}"
        except Exception as e:
            return f"Unexpected error while reading queue: {e}"

        queue_items = queue_data.get('queue', []) if queue_data else []
        if not queue_items:
            return "Queue is empty."

        normalized = song_name.strip().lower()
        matching_item = next(
            (track for track in queue_items if track.get('name', '').strip().lower() == normalized),
            None,
        )

        if not matching_item:
            return f"'{song_name}' is not currently in the queue."

        return "Spotify Web API does not support removing a specific song from queue."
    
    def pause_song(self):
        try:
            self.client.pause_playback()
        except SpotifyException as e:
            return f"Spotify error while pausing song: {e}"
        except Exception as e:
            return f"Unexpected error while pausing song: {e}"

        return "Paused the song."

    def resume_song(self):
        try:
            self.client.start_playback()
        except SpotifyException as e:
            return f"Spotify error while resuming song: {e}"
        except Exception as e:
            return f"Unexpected error while resuming song: {e}"

        return "Resumed the song."


if __name__ == "__main__":
    spotify_tool = SpotifyTool(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, redirect_uri, scopes, cache_handler)
    print(spotify_tool.play_next_song())



    # todo: pick active device