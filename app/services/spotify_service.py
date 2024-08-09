import base64
import concurrent.futures
import logging
import json
from collections import defaultdict
from random import shuffle
from urllib.parse import quote, urlencode

import requests
from flask import current_app, session

from config import Config


class SpotifyService: # pylint: disable=too-few-public-methods
    def get_or_refresh_access_token(self, code=None, refresh_token=None):
        token_url = Config.SPOTIFY_TOKEN_URL
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "client_id": current_app.config["CLIENT_ID"],
            "client_secret": current_app.config["CLIENT_SECRET"],
        }

        if code:
            payload.update(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": Config.REDIRECT_URI,
                }
            )
        elif refresh_token:
            payload.update(
                {"grant_type": "refresh_token", "refresh_token": refresh_token}
            )
        else:
            raise ValueError("Either code or refresh_token must be provided.")

        try:
            response = requests.post(token_url, data=payload, headers=headers)
            response.raise_for_status()
            response_data = response.json()
            current_app.logger.info("Access token retrieved successfully")
            return response_data
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Failed to get access token: {e}")
            if response is not None:
                current_app.logger.error(f"Response content: {response.text}")
            return None

    def get_current_user(self, access_token):
        endpoint = "https://api.spotify.com/v1/me"
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = requests.get(endpoint, headers=headers)

            if (
                response.status_code == 401
            ):  # Unauthorized, possibly due to expired token
                refresh_token = session.get("refresh_token")
                if refresh_token:
                    new_tokens = self.get_or_refresh_access_token(
                        refresh_token=refresh_token
                    )
                    if new_tokens:
                        session["access_token"] = new_tokens["access_token"]
                        session["refresh_token"] = new_tokens["refresh_token"]
                        headers["Authorization"] = (
                            f'Bearer {new_tokens["access_token"]}'
                        )
                        response = requests.get(endpoint, headers=headers)
                    else:
                        current_app.logger.error("Failed to refresh access token.")
                        return None
                else:
                    current_app.logger.error("Refresh token not available.")
                    return None

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Failed to fetch user data: {e}")
            return None

    def create_playlist(self, user_id, playlist_name, description, access_token):
        # Validate and sanitize playlist_name and description
        if not playlist_name or not isinstance(playlist_name, str):
            raise ValueError("Invalid playlist name")
        if not description or not isinstance(description, str):
            raise ValueError("Invalid playlist description")
        playlist_name = playlist_name.strip()
        description = description.strip()
        endpoint = f"{Config.SPOTIFY_API_BASE_URL}users/{user_id}/playlists"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "name": playlist_name,
            "description": description,
            "public": False,  # Assuming the playlist should be private
        }

        try:
            response = requests.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()["id"]
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Failed to create playlist: {e}")
            return None

    def get_artist_playlist_tracks(self, playlist_id, access_token, existing_tracks):
        track_uris = []
        endpoint = f"{Config.SPOTIFY_API_BASE_URL}playlists/{playlist_id}/tracks"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"fields": "items(track(uri,artists))", "limit": 100}

        while True:
            try:
                response = requests.get(endpoint, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                for item in data["items"]:
                    track_uri = item["track"]["uri"]
                    if track_uri not in existing_tracks and all(
                        artist["id"] != "2lZ09YCpdWMMmBTSdDqspr"
                        for artist in item["track"]["artists"]
                    ):
                        track_uris.append(track_uri)
                if "next" in data:
                    endpoint = data["next"]
                else:
                    break
            except requests.exceptions.RequestException as e:
                current_app.logger.error(
                    f"Failed to retrieve artist playlist tracks: {e}"
                )
                break

        # current_app.logger.debug(f"Track URIs before shuffling: {track_uris}")
        shuffle(track_uris)  # Shuffle the entire list of track URIs
        # current_app.logger.debug(f"Track URIs after shuffling: {track_uris}")
        return track_uris[:20]  # Return the first 20 tracks after shuffling

    def get_mood_defined_tracks(self, access_token):
        params = {"limit": 50, "offset": 0, "time_range": "long_term"}
        all_tracks = []
        for _ in range(4):  # Make four calls to gather 200 songs
            endpoint = f"{Config.SPOTIFY_API_BASE_URL}me/top/tracks"
            headers = {"Authorization": f"Bearer {access_token}"}
            try:
                response = requests.get(endpoint, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                all_tracks.extend(data["items"])
                params["offset"] += 50
                current_app.logger.debug(f"Retrieved {len(data['items'])} tracks in batch {_ + 1}")
            except requests.exceptions.RequestException as e:
                current_app.logger.error(f"Failed to retrieve mood-defined tracks: {e}")
                break

        current_app.logger.info(f"Retrieved total of {len(all_tracks)} tracks before filtering")

        # Filter tracks
        excluded_genres = set(Config.EXCLUDED_GENRES)
        excluded_artists = {"2lZ09YCpdWMMmBTSdDqspr"}  # Add artist URIs to exclude here
        filtered_tracks = self.filter_tracks(all_tracks, access_token, excluded_genres, excluded_artists)

        current_app.logger.info(f"Filtered down to {len(filtered_tracks)} tracks")

        # Sort the filtered tracks by popularity in descending order
        sorted_filtered_tracks = sorted(filtered_tracks, key=lambda track: track['popularity'], reverse=True)

        # Extract track URIs from sorted filtered tracks
        track_uris = [track['uri'] for track in sorted_filtered_tracks]

        return track_uris

    def get_audio_features(self, track_ids, access_token):
        headers = {'Authorization': f'Bearer {access_token}'}
        audio_features = []

        for i in range(0, len(track_ids), 50):
            batch = track_ids[i:i+50]
            response = requests.get('https://api.spotify.com/v1/audio-features', headers=headers, params={'ids': ','.join(batch)})
            if response.status_code == 200:
                batch_features = response.json().get('audio_features', [])
                audio_features.extend(batch_features)
                current_app.logger.debug(f"Successfully fetched audio features for batch {i//50 + 1}")
            else:
                current_app.logger.error(f"Error fetching audio features for batch {i//50 + 1}: {response.status_code}")
                current_app.logger.error(f"Response content: {response.text}")
                continue
        if not audio_features:
            current_app.logger.error(f"No audio features retrieved for any tracks. Total tracks: {len(track_ids)}")
        else:
            current_app.logger.info(f"Retrieved audio features for {len(audio_features)} out of {len(track_ids)} tracks")
            current_app.logger.debug(f"First few audio features: {audio_features[:5]}")

        return audio_features

    def get_genres_for_artists(self, artist_ids, access_token):
        headers = {'Authorization': f'Bearer {access_token}'}
        genres_dict = {}

        for i in range(0, len(artist_ids), 50):
            batch = artist_ids[i:i+50]
            response = requests.get(f'https://api.spotify.com/v1/artists?ids={",".join(batch)}', headers=headers)
            if response.status_code == 200:
                response_data = response.json().get('artists', [])
                for artist in response_data:
                    genres_dict[artist['id']] = artist.get('genres', [])
            else:
                current_app.logger.error(f"Error fetching genres for batch {i//50 + 1}: {response.status_code}")
                continue

        return genres_dict

    def filter_tracks(self, tracks, access_token, excluded_genres, excluded_artists):
        track_ids = [track['id'] for track in tracks]
        artist_ids = [artist['id'] for track in tracks for artist in track['artists']]
        audio_features = self.get_audio_features(track_ids, access_token)

        current_app.logger.debug(f"Tracks count: {len(tracks)}, Audio features count: {len(audio_features)}")

        if not audio_features:
            current_app.logger.error(f"No audio features returned for tracks: {track_ids}")
            return []  # Return an empty list if no audio features are available

        try:
            audio_features_dict = {feature['id']: feature for feature in audio_features if feature is not None}
            current_app.logger.debug(f"Audio features dict created with {len(audio_features_dict)} items")
        except TypeError as e:
            current_app.logger.error(f"Error creating audio features dictionary: {str(e)}")
            current_app.logger.error(f"Audio features data: {audio_features}")
            return []  # Return an empty list if we can't process the audio features

        genres_dict = self.get_genres_for_artists(artist_ids, access_token)
        audio_features_dict = {feature['id']: feature for feature in audio_features}

        filtered_tracks = []
        artist_count = defaultdict(int)
        max_tracks_per_artist = 4
        max_valence = 0.3
        max_energy = 0.5
        min_popularity = 20  # Minimum popularity threshold

        for track in tracks:
            artist_id = track['artists'][0]['id']
            genres = [genre for artist in track['artists'] for genre in genres_dict.get(artist['id'], [])]

            # Check for exclusions and allowed conditions
            if any(artist['id'] in excluded_artists for artist in track['artists']):
                continue
            elif any(genre in excluded_genres for genre in genres):
                continue
            elif artist_count[artist_id] >= max_tracks_per_artist:
                continue
            elif track['popularity'] < min_popularity:  # Filter out tracks with popularity less than 20
                continue
            else:
                valence = audio_features_dict.get(track['id'], {}).get('valence', 0)
                energy = audio_features_dict.get(track['id'], {}).get('energy', 0)
                if (
                    (energy < 0.5 and 0.3 <= valence <= 0.4) or
                    (valence < 0.3 and 0.5 <= energy <= 0.6)
                ):
                    filtered_tracks.append({
                        'uri': track['uri'],
                        'popularity': track['popularity']
                    })
                    artist_count[artist_id] += 1
                elif valence <= max_valence and energy <= max_energy:
                    filtered_tracks.append({
                        'uri': track['uri'],
                        'popularity': track['popularity']
                    })
                    artist_count[artist_id] += 1

        return filtered_tracks

    def build_and_shuffle_playlist(self, playlist_id, artist_playlist_id, access_token):
        mood_tracks = self.get_mood_defined_tracks(access_token)
        specified_uris = Config.SPECIFIED_TRACK_URIS
        artist_tracks = self.get_artist_playlist_tracks(
            artist_playlist_id, access_token, mood_tracks + specified_uris
        )

        final_tracks = [None] * 45
        specified_positions = [0, 4, 11, 20, 39]

        # Place specified tracks at specified positions
        for pos, track in zip(specified_positions, specified_uris):
            final_tracks[pos] = track

        # Shuffle mood and artist tracks
        shuffle(mood_tracks)
        shuffle(artist_tracks)

        # Fill other positions alternating between mood and artist tracks
        mood_index = 0
        artist_index = 0
        added_tracks = set(specified_uris)  # Track added URIs to avoid duplicates

        for i in range(45):
            if final_tracks[i] is None:
                if i % 2 == 0 and mood_index < len(mood_tracks):
                    track = mood_tracks[mood_index]
                    mood_index += 1
                elif artist_index < len(artist_tracks):
                    track = artist_tracks[artist_index]
                    artist_index += 1
                else:
                    track = None

                if track is not None and track not in added_tracks and (
                    i == 0
                    or (
                        final_tracks[i - 1] is not None
                        and track != final_tracks[i - 1]  # Compare track URIs directly
                    )
                ):
                    final_tracks[i] = track
                    added_tracks.add(track)

        return [track for track in final_tracks if track is not None]

    def add_tracks_to_playlist(self, playlist_id, tracks, access_token):
        # Validate and sanitize playlist_id and tracks
        if not playlist_id or not isinstance(playlist_id, str):
            raise ValueError("Invalid playlist ID")
        if not tracks or not isinstance(tracks, list):
            raise ValueError("Invalid tracks")
        endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"uris": tracks}

        try:
            response = requests.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            current_app.logger.info("Tracks added to the playlist successfully.")
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Failed to add tracks to the playlist: {e}")
            current_app.logger.error(f"Response text: {response.text}")

    def exchange_code_for_token(self, code):
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": Config.REDIRECT_URI,
            "client_id": Config.CLIENT_ID,
            "client_secret": Config.CLIENT_SECRET,
        }
        response = requests.post(Config.SPOTIFY_TOKEN_URL, data=payload)
        response.raise_for_status()
        return response.json()

    def follow_artist(self, access_token, artist_id):  # done
        endpoint = (
            f"{Config.SPOTIFY_API_BASE_URL}me/following?type=artist&ids={artist_id}"
        )
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = requests.put(endpoint, headers=headers)
            response.raise_for_status()
            current_app.logger.info("Artist followed successfully.")
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Failed to follow artist: {e}")
            current_app.logger.error(f"Response text: {response.text}")

    def get_auth_url(self, state):
        scope = "user-top-read user-library-read user-read-email playlist-modify-private playlist-modify-public ugc-image-upload user-follow-modify user-follow-read"
        params = {
            "client_id": Config.CLIENT_ID,
            "response_type": "code",
            "redirect_uri": Config.REDIRECT_URI,
            "scope": scope,
            "state": state,
            "show_dialog": "true"
        }
        
        web_auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"
        android_auth_url = f"intent://accounts.spotify.com/authorize?{urlencode(params)}#Intent;package=com.spotify.music;scheme=https;end"
        ios_auth_url = f"spotify-action://authorize?{urlencode(params)}"
        
        return {
            "web": web_auth_url,
            "android": android_auth_url,
            "ios": ios_auth_url
        }

    def upload_playlist_cover_image(self, playlist_id, image_data, access_token):
        # Validate and sanitize playlist_id and image_data
        if not playlist_id or not isinstance(playlist_id, str):
            raise ValueError("Invalid playlist ID")
        if not image_data:
            raise ValueError("Invalid image data")

        endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/images"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/jpeg",
        }
        base64_image_data = base64.b64encode(
            image_data.getvalue()
        )
        return self._make_upload_request(endpoint, headers, base64_image_data)

    def _make_upload_request(self, endpoint, headers, data, retries=5):
        for attempt in range(retries):
            try:
                response = requests.put(
                    endpoint, headers=headers, data=data, timeout=30
                )
                response.raise_for_status()
                current_app.logger.info("Playlist cover image uploaded successfully.")
                return True
            except requests.exceptions.RequestException as e:
                current_app.logger.error(
                    f"Attempt {attempt + 1} failed to upload playlist cover image: {str(e)}"
                )
                current_app.logger.error(
                    f"Response text: {response.text if 'text' in dir(response) else 'No response'}"
                )
                if attempt < retries - 1:
                    current_app.logger.debug("Retrying...")
                else:
                    current_app.logger.error(
                        "Failed to upload image after multiple attempts."
                    )
                    return False
        return False

    def get_user_top_data(self, access_token):
        headers = {"Authorization": f"Bearer {access_token}"}
        top_data = {}

        def fetch_top_items(item_type, time_range):
            return self._get_top_items(item_type, time_range, headers)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {
                "top_tracks_short": executor.submit(
                    fetch_top_items, "tracks", "short_term"
                ),
                "top_tracks_medium": executor.submit(
                    fetch_top_items, "tracks", "medium_term"
                ),
                "top_tracks_long": executor.submit(
                    fetch_top_items, "tracks", "long_term"
                ),
                "top_artists_short": executor.submit(
                    fetch_top_items, "artists", "short_term"
                ),
                "top_artists_medium": executor.submit(
                    fetch_top_items, "artists", "medium_term"
                ),
                "top_artists_long": executor.submit(
                    fetch_top_items, "artists", "long_term"
                ),
            }

            for key, future in futures.items():
                top_data[key] = future.result()

        return top_data

    def _get_top_items(self, item_type, time_range, headers):
        endpoint = f"{Config.SPOTIFY_API_BASE_URL}me/top/{item_type}"
        params = {"limit": 20, "time_range": time_range}
        try:
            response = requests.get(endpoint, headers=headers, params=params)
            response.raise_for_status()
            return response.json()["items"]
        except requests.exceptions.RequestException as e:
            current_app.logger.error(
                f"Failed to retrieve top {item_type} for {time_range}: {e}"
            )
            return []

    def get_user_profile_data(self, access_token):
        headers = {"Authorization": f"Bearer {access_token}"}
        endpoint = f"{Config.SPOTIFY_API_BASE_URL}me"
        try:
            response = requests.get(endpoint, headers=headers)
            response.raise_for_status()
            data = response.json()
            current_app.logger.info(f"Successfully retrieved user profile: {data}")
            return {
                "id": data.get("id"),  # Ensure 'id' is included
                "country": data.get("country"),
                "display_name": data.get("display_name"),
                "user_name": data.get("id"),  # This is the same as 'id'
                "followers": data.get("followers", {}).get("total", 0),
                "image_url": (
                    data.get("images", [{}])[0].get("url")
                    if data.get("images")
                    else None
                ),
                "email": data.get("email"),
            }
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Failed to retrieve user profile data: {e}")
            raise ValueError(f"Failed to retrieve user profile data: {e}")

    def revoke_token(self, access_token):
        endpoint = "https://accounts.spotify.com/api/token"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"token": access_token}

        try:
            response = requests.post(endpoint, headers=headers, data=payload, timeout=30)
            response.raise_for_status()
            current_app.logger.info("Access token revoked successfully.")
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Failed to revoke access token: {e}")
