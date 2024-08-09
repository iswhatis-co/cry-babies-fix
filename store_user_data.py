import requests

from flask import current_app
from app import create_app
from app.models import UserData, db


def get_followed_artists(access_token, limit=20, after=None):
    endpoint = "https://api.spotify.com/v1/me/following"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"type": "artist", "limit": limit}
    if after:
        params["after"] = after
    response = requests.get(endpoint, headers=headers, params=params)
    data = response.json()
    if "artists" in data and "items" in data["artists"]:
        # Extract only the name and Spotify URL for each artist
        return [
            {"name": artist["name"], "spotify_url": artist["external_urls"]["spotify"]}
            for artist in data["artists"]["items"]
        ]
    else:
        return []


def get_user_playlists(access_token, user_id, limit=10):
    endpoint = f"https://api.spotify.com/v1/users/{user_id}/playlists"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"limit": limit}
    response = requests.get(endpoint, headers=headers, params=params)
    playlists = response.json().get("items", [])

    return [
        {"name": playlist["name"], "spotify_url": playlist["external_urls"]["spotify"]}
        for playlist in playlists
    ]


def get_user_top_items(access_token, item_type, time_range="medium_term", limit=20):
    endpoint = f"https://api.spotify.com/v1/me/top/{item_type}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"limit": limit, "time_range": time_range}
    response = requests.get(endpoint, headers=headers, params=params)
    items = response.json().get("items", [])

    if item_type == "artists":
        # Extract only the name and Spotify URL for artists
        return [
            {"name": item["name"], "spotify_url": item["external_urls"]["spotify"]}
            for item in items
        ]
    elif item_type == "tracks":
        # Extract track name, main artist's name, and track's Spotify URL for tracks
        return [
            {
                "track_name": item["name"],
                "artist_name": item["artists"][0]["name"],
                "spotify_url": item["external_urls"]["spotify"],
            }
            for item in items
        ]

    return []


def get_user_profile(access_token):
    endpoint = f"https://api.spotify.com/v1/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(endpoint, headers=headers)
    data = response.json()
    return {
        "display_name": data.get("display_name"),
        "email": data.get("email"),
        "followers": data.get("followers", {}).get("total", 0),
        "image_url": (
            data.get("images", [{}])[0].get("url") if data.get("images") else None
        ),
    }

def store_user_data(user_id, access_token, refresh_token=None, mailing_list=False, spotify_subscribe=False):
    app = create_app()
    with app.app_context():
        # Get user profile data
        profile_data = get_user_profile(access_token)
        display_name = profile_data["display_name"]
        followers = profile_data["followers"]
        image_url = profile_data["image_url"]
        email = profile_data.get("email")

        # Get followed artists
        followed_artists = get_followed_artists(access_token, limit=20)
        app.logger.debug(f"Followed artists: {followed_artists}")

        # Get user's top items with modified structure
        top_data = {
            "top_artists_long": get_user_top_items(access_token, "artists", "long_term"),
            "top_artists_medium": get_user_top_items(access_token, "artists", "medium_term"),
            "top_artists_short": get_user_top_items(access_token, "artists", "short_term"),
            "top_tracks_long": get_user_top_items(access_token, "tracks", "long_term"),
            "top_tracks_medium": get_user_top_items(access_token, "tracks", "medium_term"),
            "top_tracks_short": get_user_top_items(access_token, "tracks", "short_term"),
        }

        # Get user's playlists
        playlists = get_user_playlists(access_token, user_id, limit=10)

        # Store data in the database
        user_data = UserData.query.filter_by(user_id=user_id).first()
        if user_data:
            # Update existing user data
            user_data.display_name = display_name
            user_data.followers = followers
            user_data.image_url = image_url
            user_data.email = email
            user_data.followed_artists = followed_artists
            user_data.top_artists_long_term = top_data["top_artists_long"]
            user_data.top_artists_medium_term = top_data["top_artists_medium"]
            user_data.top_artists_short_term = top_data["top_artists_short"]
            user_data.top_tracks_long_term = top_data["top_tracks_long"]
            user_data.top_tracks_medium_term = top_data["top_tracks_medium"]
            user_data.top_tracks_short_term = top_data["top_tracks_short"]
            user_data.playlists = playlists
            user_data.access_token = access_token
            user_data.refresh_token = refresh_token
            user_data.mailing_list = mailing_list
            user_data.spotify_subscribe = spotify_subscribe
            user_data.processed = True
        else:
            # Create new user data
            user_data = UserData(
                user_id=user_id,
                display_name=display_name,
                followers=followers,
                image_url=image_url,
                email=email,
                followed_artists=followed_artists,
                top_artists_long_term=top_data["top_artists_long"],
                top_artists_medium_term=top_data["top_artists_medium"],
                top_artists_short_term=top_data["top_artists_short"],
                top_tracks_long_term=top_data["top_tracks_long"],
                top_tracks_medium_term=top_data["top_tracks_medium"],
                top_tracks_short_term=top_data["top_tracks_short"],
                playlists=playlists,
                access_token=access_token,
                refresh_token=refresh_token,
                mailing_list=mailing_list,
                spotify_subscribe=spotify_subscribe,
                processed=True,
            )
            db.session.add(user_data)

        db.session.commit()

        app.logger.debug(f"Stored user data - user_id: {user_id}, mailing_list: {mailing_list}, spotify_subscribe: {spotify_subscribe}, refresh_token: {'Present' if refresh_token else 'Not present'}")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        unprocessed_users = UserData.query.filter_by(processed=False).all()
        for user_data in unprocessed_users:
            try:
                store_user_data(
                    user_data.user_id,
                    user_data.access_token,
                    user_data.refresh_token,  
                    user_data.mailing_list,
                    user_data.spotify_subscribe, 
                )
                user_data.processed = True
                db.session.commit()
            except Exception as e:
                app.logger.error(
                    f"Error processing user data for user_id {user_data.user_id}: {e}"
                )
                db.session.rollback()
                db.session.rollback()
