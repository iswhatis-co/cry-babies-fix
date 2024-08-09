import requests
from flask import current_app

from ..services.spotify_service import SpotifyService


class UserService: # pylint: disable=too-few-public-methods
    def __init__(self):
        self.spotify_api = SpotifyService()

    def get_user_details(self, access_token):
        endpoint = "https://api.spotify.com/v1/me"
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = requests.get(endpoint, headers=headers, timeout=5)
            response.raise_for_status()
            user_data = response.json()
            if "id" not in user_data:
                raise ValueError("Invalid user details")
            return user_data
        except requests.RequestException as e:
            current_app.logger.error(f"Failed to get user details: {e}")
            return None
