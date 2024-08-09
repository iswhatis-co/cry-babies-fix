import requests
from flask import current_app

from ..services.spotify_service import SpotifyService


class PlaylistService:
    def __init__(self):
        self.spotify_api = SpotifyService()

    def create_playlist(self, user_id, name, description, access_token):
        current_app.logger.info(
            f"Creating playlist for user ID: {user_id} with name: {name} and description: {description}"
        )
        if not user_id or not isinstance(user_id, str):
            raise ValueError("Invalid user details")

        # Validate and sanitize name and description
        if not name or not isinstance(name, str):
            raise ValueError("Invalid playlist name")
        if not description or not isinstance(description, str):
            raise ValueError("Invalid playlist description")
        name = name.strip()
        description = description.strip()

        try:
            endpoint = f"https://api.spotify.com/v1/users/{user_id}/playlists"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            payload = {"name": name, "description": description, "public": True}
            response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            playlist_data = response.json()
            return playlist_data["id"]
        except requests.RequestException as e:
            current_app.logger.error(f"Failed to create playlist: {e}")
            raise ValueError("Failed to create playlist") from e

    def add_tracks(self, playlist_id, artist_playlist_id, access_token):
        tracks = self.spotify_api.build_and_shuffle_playlist(
            playlist_id, artist_playlist_id, access_token
        )
        if tracks:
            current_playlist_tracks = self.spotify_api.get_playlist_tracks(
                playlist_id, access_token
            )
            new_tracks = [
                track for track in tracks if track not in current_playlist_tracks
            ]
            if new_tracks:
                self.spotify_api.add_tracks_to_playlist(
                    playlist_id, new_tracks, access_token
                )
            return tracks
        current_app.logger.error("build_and_shuffle_playlist returned None")
        return None
