from flask_sqlalchemy import model
from . import db

BaseModel: model = db.Model

class UserData(db.Model):
    __tablename__ = 'user_data'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(255))
    followers = db.Column(db.Integer)
    image_url = db.Column(db.Text)
    followed_artists = db.Column(db.JSON)
    top_artists_long_term = db.Column(db.JSON)
    top_artists_medium_term = db.Column(db.JSON)
    top_artists_short_term = db.Column(db.JSON)
    top_tracks_long_term = db.Column(db.JSON)
    top_tracks_medium_term = db.Column(db.JSON)
    top_tracks_short_term = db.Column(db.JSON)
    playlists = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=db.func.now())
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    mailing_list = db.Column(db.Boolean, default=False)
    spotify_subscribe = db.Column(db.Boolean, default=False)
    email = db.Column(db.String(255), nullable=True)
    processed = db.Column(db.Boolean, default=False)
