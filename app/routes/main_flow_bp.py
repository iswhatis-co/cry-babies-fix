import os
import random
import string
import uuid
import subprocess
import threading
import json
import redis
from concurrent.futures import ThreadPoolExecutor
from flask import (
    Blueprint, current_app, jsonify, redirect, render_template,
    request, send_file, send_from_directory, session, url_for, after_this_request, g
)
from flask_wtf.csrf import generate_csrf
from flask_session import Session
from app import db
from app.forms import CreatePlaylistForm
from app.models import UserData
from app.services.image_service import ImageService
from app.services.playlist_service import PlaylistService
from app.services.spotify_service import SpotifyService
from app.services.user_service import UserService

main_flow_bp = Blueprint('main_flow_bp', __name__)

Session(current_app)

executor = ThreadPoolExecutor(max_workers=5)

def generate_state_string(length=16):
    letters_and_digits = string.ascii_letters + string.digits
    return ''.join(random.choice(letters_and_digits) for i in range(length))

redis_url = os.getenv("REDIS_TLS_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379"
current_app.redis_client = redis.Redis.from_url(redis_url, ssl_cert_reqs=None 
                                    if redis_url.startswith("rediss://") else "required")
playlist_statuses = {}

def get_image_service():
    global image_service
    if image_service is None:
        image_service = ImageService(current_app.static_folder)
    return image_service

# Initialize services in a factory function
def init_services(redis_client):
    return {
        'spotify_service': SpotifyService(current_app.redis_client),
        'image_service': ImageService(current_app.static_folder, current_app.redis_client),
        'playlist_service': PlaylistService(),
        'user_service': UserService()
    }

@main_flow_bp.before_app_request
def before_request():
    g.services = init_services(current_app.redis_client)

@main_flow_bp.before_request
def before_request():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        current_app.logger.info(f"New session started with session_id: {session['session_id']}")

@main_flow_bp.route('/logout')
def logout():
    user_id = session.get("user_id")
    if user_id:
        current_app.redis_client.delete(f"user_session:{user_id}")
    session.clear()
    current_app.logger.info("User logged out and session invalidated.")
    return redirect(url_for('main_flow_bp.index'))

@main_flow_bp.route('/', methods=['GET', 'POST'])
def index():
    form = CreatePlaylistForm()
    if form.validate_on_submit():
        user_id = session["user_id"]
        user_name = form.user_name.data.lower()
        mailing_list = form.mailing_list.data
        spotify_subscribe = form.spotify_subscribe.data
    
        current_app.redis_client.hmset(f"user_data:{user_id}", {
            "user_name": user_name,
            "mailing_list": mailing_list,
            "spotify_subscribe": spotify_subscribe
        })

        state = f"{generate_state_string()}:{user_name}"
        current_app.redis_client.set(f"state:{state}", state, ex=300)
        current_app.logger.debug(f"Generated state: {state} and stored in Redis")

        auth_urls = SpotifyService.get_auth_url(state)
        current_app.logger.debug(f"Received auth URLs: {auth_urls}")

        user_agent = request.headers.get('User-Agent')
        current_app.logger.debug(f"User agent: {user_agent}")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            response_data = {"redirect_url": auth_urls}
            current_app.logger.info(f"Sending JSON response: {json.dumps(response_data)}")
            return jsonify(response_data)
        else:
            current_app.logger.info(f"Redirecting to: {auth_urls['web']}")
            return redirect(auth_urls['web'])

    return render_template('index.html', form=form)

@main_flow_bp.route('/callback')
def callback():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    current_app.logger.debug(f"Received callback with code: {code}, state: {state}, error: {error}")

    if error:
        current_app.logger.error(f"Error in Spotify callback: {error}")
        return redirect(url_for('main_flow_bp.index'))

    stored_state = current_app.redis_client.get(f"state:{state}")
    current_app.logger.debug(f"Stored state from Redis: {stored_state}")

    if stored_state is None or state.split(':')[0] != stored_state.decode('utf-8').split(':')[0]:
        current_app.logger.error("Invalid state")
        return redirect(url_for('main_flow_bp.index'))

    user_id = state.split(':')[1]

    try:
        token_data = g.services['spotify_service'].get_or_refresh_access_token(code=code, user_id=user_id)
        access_token = token_data['access_token']
        refresh_token = token_data['refresh_token']

        user_profile = g.services['spotify_service'].get_user_profile_data(access_token)
        
        current_app.redis_client.hmset(f"user_data:{user_id}", {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_profile": json.dumps(user_profile)
        })

        if not isinstance(user_profile, dict):
            raise ValueError(f"Expected dictionary for user_profile, got {type(user_profile)}")

        spotify_user_id = user_profile.get('id')
        
        session['user_id'] = user_id
        session['spotify_user_id'] = spotify_user_id

        user_name = state.split(':')[1] if ':' in state else 'User'
        current_app.logger.debug(f"Retrieved user_name from state: {user_name}")
        playlist_name = f"{user_name} and cassie's trauma list"
        session['playlist_name'] = playlist_name
        current_app.logger.debug(f"Set playlist_name in session: {playlist_name}")

        # Store user data
        user_data = g.services['user_service'].get_user_data(spotify_user_id)
        if user_data:
            # Update existing user data
            user_data.access_token = access_token
            user_data.refresh_token = refresh_token
            user_data.spotify_subscribe = session.get('spotify_subscribe', False)
            user_data.display_name = user_profile.get('display_name')
            user_data.followers = user_profile.get('followers')
            user_data.image_url = user_profile.get('images', [{}])[0].get('url')
            user_data.email = user_profile.get('email')
            user_data.mailing_list = session.get('mailing_list', False)
            user_data.processed = True
        else:
            # Create new user data
            user_data = UserData(
                user_id=spotify_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                spotify_subscribe=session.get('spotify_subscribe', False),
                display_name=user_profile.get('display_name'),
                followers=user_profile.get('followers'),
                image_url=user_profile.get('images', [{}])[0].get('url'),
                email=user_profile.get('email'),
                mailing_list=session.get('mailing_list', False),
                processed=True
            )
            db.session.add(user_data)

        db.session.commit()
        current_app.logger.debug(f"User data stored in database for user_id: {user_id}")

        # Initiate playlist creation process
        return create_playlist(user_name)

    except Exception as e:
        current_app.logger.error(f"Error creating playlist: {e}")
        db.session.rollback()
        return redirect(url_for('main_flow_bp.index'))
    
@main_flow_bp.route("/generated-image/<playlist_name>")
def generated_image(playlist_name):
    try:
        img_byte_arr = image_service.create_image(playlist_name)
        img_byte_arr.seek(0)  # Reset the buffer to the start
        return send_file(
            img_byte_arr,
            mimetype="image/jpeg",
            as_attachment=False,  # Ensure this is set correctly
        )
    except Exception as e:
        current_app.logger.error(
            f"Error generating image for playlist {playlist_name}: {e}"
        )
        return jsonify({"error": "Failed to generate image"}), 500

@main_flow_bp.route("/loading")
def loading():
    print("Loading page accessed")
    print(f"Session data: {session.items()}")
    playlist_id = session.get("playlist_id")
    user_id = session.get("user_profile", {}).get("id")  # Change this line
    access_token = session.get("access_token")
    print(f"Playlist ID: {playlist_id}, User ID: {user_id}, Access Token exists: {bool(access_token)}")
    
    if not playlist_id or not user_id or not access_token:
        print("Missing required session data")
        return redirect(url_for("main_flow_bp.index"))
    
    print(f"Rendering loading_ghost.html with playlist_id: {playlist_id}")
    return render_template("loading_ghost.html", playlist_id=playlist_id)

@main_flow_bp.route("/create_playlist", methods=["GET", "POST"])
def create_playlist(user_name=None):
    if request.method == "POST":
        user_name = request.form.get("user_name")
        mailing_list = request.form.get("mailing_list", False)
        current_app.logger.debug(f"Received POST request with user_name: {user_name}, mailing_list: {mailing_list}")

        if not user_name or not isinstance(user_name, str):
            current_app.logger.error(f"Invalid username: {user_name}")
            return jsonify({"error": "Invalid username"}), 400

        user_name = user_name.strip()  # Sanitize the username
        current_app.logger.debug(f"Sanitized username: {user_name}")

        session["user_name"] = user_name
        session["mailing_list"] = mailing_list
        current_app.logger.info(f"Username {user_name} stored in session")

        access_token = session.get("access_token")
        current_app.logger.debug(f"Access token: {access_token}")
        if not access_token:
            # If no access token, we need to start the Spotify authorization flow
            state = generate_state_string()
            current_app.redis_client.set(f"state:{state}", state, ex=300)
            current_app.logger.debug(f"Generated state: {state} and stored in Redis")

            auth_url = SpotifyService.get_auth_url(state)
            current_app.logger.debug(f"Generated auth URL: {auth_url}")
            return jsonify({"redirect": auth_url})

        # If we have an access token, proceed with playlist creation
        return create_playlist_internal(access_token, user_name, mailing_list)

    # Handle GET requests (including callback redirects)
    access_token = session.get("access_token")
    user_profile = session.get("user_profile")

    if not access_token or not user_profile:
        current_app.logger.error("Missing access token or user profile")
        return redirect(url_for('main_flow_bp.index'))

    user_name = user_name or session.get('user_name', user_profile.get('display_name', 'User'))
    mailing_list = session.get('mailing_list', False)

    return create_playlist_internal(access_token, user_name, mailing_list)

def create_playlist_internal(access_token, user_name, mailing_list):
    try:
        user_details = g.services['user_service'].get_user_details(access_token)
        current_app.logger.debug(f"User details: {user_details}")
        if not user_details or "id" not in user_details:
            current_app.logger.error("Invalid user details.")
            return jsonify({"error": "Invalid user details"}), 400

        user_id = user_details["id"]

        playlist_name = session.get('playlist_name', f"{user_name} and cassie's trauma list")
        description = "cool girls cry 💜💛💙💚"

        current_app.logger.debug(f"Creating playlist with name: {playlist_name}, description: {description}")
        playlist_id = g.services['playlist_service'].create_playlist(
            user_id, playlist_name, description, access_token
        )
        session["playlist_id"] = playlist_id
        current_app.logger.info(f"Playlist created with ID: {playlist_id}")
        current_app.logger.debug(f"Session data: {session.items()}")

        user_data = UserData(
            user_id=user_id, access_token=access_token, mailing_list=mailing_list
        )
        if mailing_list:
            user_data.email = user_details.get("email")
        db.session.add(user_data)
        db.session.commit()
        current_app.logger.debug(f"User data stored in database for user_id: {user_id}")

        return redirect(url_for("main_flow_bp.loading"))
    except Exception as e:
        current_app.logger.error(f"Error creating playlist: {e}")
        db.session.rollback()
        return redirect(url_for('main_flow_bp.index'))

@main_flow_bp.route("/process_main_flow", methods=["POST"])
def process_main_flow():
    current_app.logger.info("Processing the main flow")
    access_token = session.get("access_token")
    current_app.logger.debug(f"Access token: {access_token}")
    if not access_token:
        current_app.logger.error("Access token is missing.")
        return redirect(url_for("main_flow_bp.index"))  # Redirect to re-authenticate

    user_details = UserService.get_user_details(access_token)
    current_app.logger.debug(f"User details: {user_details}")
    if not user_details or "id" not in user_details:
        current_app.logger.error("Invalid user details.")
        return "Invalid user details", 400

    user_id = user_details["id"]
    playlist_name = session.get('playlist_name')
    
    if not playlist_name:
        user_name = session.get('user_name', 'User')
        playlist_name = f"{user_name} and cassie's trauma list"
        session['playlist_name'] = playlist_name

    try:
        # If playlist creation hasn't happened yet, create it
        if 'playlist_id' not in session:
            description = "cool girls cry 💜💛💙💚"
            playlist_id = PlaylistService.create_playlist(
                user_id, playlist_name, description, access_token
            )
            session["playlist_id"] = playlist_id
            current_app.logger.info(f"Playlist created with ID: {playlist_id}")

        # Store user data in the database
        user_data = UserData(
            user_id=user_id,
            access_token=access_token,
            refresh_token=session.get('refresh_token'),
            mailing_list=session.get('mailing_list', False),
            spotify_subscribe=session.get('spotify_subscribe', False)
        )
        if user_data.mailing_list:
            user_data.email = user_details.get("email")
        db.session.add(user_data)
        db.session.commit()

        current_app.logger.debug(f"Session data: {session.items()}")
        session.clear()
        return redirect(url_for("main_flow_bp.loading"))
    except Exception as e:
        current_app.logger.error(f"Error in process_main_flow: {e}")
        session.clear()
        return "Error processing main flow", 500

@main_flow_bp.route("/create_playlist_background/<playlist_id>")
def create_playlist_background(playlist_id):
    access_token = g.services['spotify_service'].get_access_token(session.get("user_id"))
    playlist_name = session.get("playlist_name")
    artist_playlist_id = "6Z8G9W9F4pCGon5iEJI2ly"

    try:
        current_app.logger.info(f"Starting playlist creation for {playlist_id}")
        current_app.logger.debug(f"Access token: {access_token[:10]}... (truncated)")
        current_app.logger.debug(f"Playlist name: {playlist_name}")

        final_tracks = g.services['spotify_service'].build_and_shuffle_playlist(
            playlist_id, artist_playlist_id, access_token
        )
        current_app.logger.info(f"Built and shuffled playlist. Tracks: {len(final_tracks)}")

        g.services['spotify_service'].add_tracks_to_playlist(playlist_id, final_tracks, access_token)
        current_app.logger.info("Added tracks to playlist")

        image_data = g.services['image_service'].create_image(playlist_name, session.get("user_id"))
        if image_data:
            g.services['spotify_service'].upload_playlist_cover_image(playlist_id, image_data, access_token)
            current_app.logger.info("Uploaded playlist cover image")
        else:
            current_app.logger.warning("No image data generated")

        g.services['spotify_service'].follow_artist(access_token, "2lZ09YCpdWMMmBTSdDqspr")
        current_app.logger.info("Followed artist")

        playlist_statuses[playlist_id] = "ready"
        current_app.logger.info("Playlist creation completed successfully")
    except Exception as e:
        current_app.logger.error(f"Error in creating playlist: {str(e)}", exc_info=True)
        playlist_statuses[playlist_id] = "error"

    status = playlist_statuses.get(playlist_id, "in_progress")
    playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
    return jsonify({"status": status, "playlist_url": playlist_url})

@main_flow_bp.route("/playlist_created")
def playlist_created():
    playlist_url = request.args.get("playlist_url")
    if not playlist_url or not isinstance(playlist_url, str):
        current_app.logger.error(f"Invalid playlist URL: {playlist_url}")
        return redirect(url_for("main_flow_bp.index"))
    user_id = session.get("user_profile", {}).get("id")
    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")
    mailing_list = session.get("mailing_list", False)
    spotify_subscribe = session.get("spotify_subscribe", False)

    if user_id and access_token:
        from store_user_data import store_user_data
        store_user_data(user_id, access_token, refresh_token, mailing_list, spotify_subscribe)

    return render_template("playlist_created.html", playlist_url=playlist_url)

@main_flow_bp.route("/static/<path:filename>")
def static_files(filename):
    if not filename or not isinstance(filename, str):
        current_app.logger.error(f"Invalid filename: {filename}")
        return redirect(url_for("main_flow_bp.index"))
    response = send_from_directory("app/static", filename)
    response.cache_control.public = True
    response.cache_control.max_age = 31536000  # Cache for one year
    return response

@main_flow_bp.route("/delete_user_data", methods=["GET", "POST"])
def delete_user_data():
    user_id = session.get("user_profile", {}).get("id")
    current_app.logger.info(f"Deleting data for user_id: {user_id}")

    if not user_id:
        current_app.logger.warning("No user_id found in the session")

        # Generate a new state and store it in Redis
        state = generate_state_string()
        current_app.redis_client.set(f"state:{state}", state, ex=300)
        current_app.logger.debug(f"Generated state: {state}")

        # Get the authorization URL for re-authentication
        auth_url = SpotifyService.get_auth_url(state)
        current_app.logger.debug(f"Generated auth_url: {auth_url}")

        # Store flag in session to indicate user is redirected for data deletion
        session["delete_user_data"] = True

        # Redirect the user to the authorization URL for re-authentication
        return redirect(auth_url)

    # Check if the user is being redirected after re-authentication
    if session.pop("delete_user_data", False):
        # Delete the user's data
        user_data = UserData.query.filter_by(user_id=user_id).first()
        current_app.logger.info(f"Retrieved user data: {user_data}")

        if user_data:
            try:
                db.session.delete(user_data)
                db.session.commit()
                current_app.logger.info(f"Deleted data for user_id: {user_id}")
            except Exception as e:
                current_app.logger.error(f"Error deleting user data: {e}")
                db.session.rollback()
                return "Error deleting user data", 500
        else:
            current_app.logger.warning(f"No data found for user_id: {user_id}")

        # Revoke the app's access token
        access_token = session.get("access_token")
        current_app.logger.info(f"Access token: {access_token}")

        if access_token:
            try:
                SpotifyService.revoke_token(access_token)
                current_app.logger.info("Access token revoked")
            except Exception as e:
                current_app.logger.error(f"Error revoking access token: {e}")
        else:
            current_app.logger.warning("No access token found in the session")

        session.clear()
        current_app.logger.info("Session cleared")

        return redirect("https://www.spotify.com/account/apps/")

    # If the user is not being redirected after re-authentication, proceed with the normal flow
    return redirect("https://www.spotify.com/account/apps/")

@main_flow_bp.route('/log', methods=['POST'])
def log():
    data = request.get_json()
    log_level = data.get('level', 'info')
    message = data.get('message', '')

    if log_level == 'debug':
        current_app.logger.debug(message)
    elif log_level == 'info':
        current_app.logger.info(message)
    elif log_level == 'warning':
        current_app.logger.warning(message)
    elif log_level == 'error':
        current_app.logger.error(message)
    else:
        current_app.logger.info(message)

    return jsonify({"status": "success"}), 200
