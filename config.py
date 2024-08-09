import os
import redis

from datetime import timedelta
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Secret key for session management
    SECRET_KEY: str = os.getenv("SECRET_KEY")

    # Spotify API credentials
    CLIENT_ID: str = os.getenv("CLIENT_ID")
    CLIENT_SECRET: str = os.getenv("CLIENT_SECRET")

    # Environment-specific redirect URI
    REDIRECT_URI: str = os.getenv("PRODUCTION_REDIRECT_URI") #if os.getenv(
        #"FLASK_ENV") == "production" else os.getenv("LOCAL_REDIRECT_URI")

    # Session configuration
    SESSION_TYPE: str = "redis"
    SESSION_REDIS = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    PERMANENT_SESSION_LIFETIME: timedelta = timedelta(minutes=30)

    # Spotify API endpoints
    AUTH_URL: str = "https://accounts.spotify.com/authorize"
    SPOTIFY_TOKEN_URL: str = "https://accounts.spotify.com/api/token"
    SPOTIFY_API_BASE_URL: str = "https://api.spotify.com/v1/"

    # Environment setting
    ENV: str = os.getenv("FLASK_ENV", "development")

    # Primary database URL (postgres://)
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    # Secondary database URL (postgresql://)
    DATABASE_2_URL = os.getenv('DATABASE_2_URL', '')

    SQLALCHEMY_DATABASE_URI = DATABASE_2_URL
    SQLALCHEMY_BINDS = {'primary': DATABASE_URL}
    SQLALCHEMY_TRACK_MODIFICATIONS = False


    # Application directories
    BASE_DIR: str = os.path.abspath(os.path.dirname(__file__))
    STATIC_DIR: str = os.path.join(BASE_DIR, "app", "static")
    TEMPLATE_DIR: str = os.path.join(BASE_DIR, "app", "templates")
    FONT_PATH_LACQUER = os.path.join(STATIC_DIR, "fonts", "Lacquer-Regular.ttf")
    FONT_PATH_NEW_SPIRIT = os.path.join(STATIC_DIR, "fonts", "NewSpiritSemiBoldCondensed.otf")

    # Specified track URIs
    SPECIFIED_TRACK_URIS: List[str] = [
        "spotify:track:0FtODjGalCt5caVtQwoIuP",
        "spotify:track:3UESTUetIZT67oVqNm76DH",
        "spotify:track:0uSfUZrGHvuqm1Yz4I51qC",
        "spotify:track:6V7srdT0Mu63F4XN97buVZ",
        "spotify:track:5tg10O76Ih5wI5I09QpqTU",
    ]
    
    # Excluded music genres
    EXCLUDED_GENRES = [
        "rap",
        "drum and bass",
        "musical advocacy",
        "asmr",
        "hip hop",
        "classical",
        "comedy",
        "musical",
        "trap",
        "house",
        "spoken word",
        "reading",
        "poetry",
        "audiobook",
        "field recording",
        "historical performance",
        "experimental poetry",
        "children's music",
        "kids",
        "nursery",
        "lullaby",
        "background",
        "ambient",
        "meditation",
        "healing",
        "hypnosis",
        "pilates",
        "reiki",
        "erotica",
        "erotic product",
        "prank",
        "binaural",
        "meme",
        "meme rap",
        "viral rap",
        "gamecore",
        "anime score",
        "anime rap",
        "animegrind",
        "anime game",
        "anime",
        "idol game",
        "idol",
        "soundtrack",
        "show tunes",
        "broadway",
        "karaoke",
        "video game music",
        "vgm",
        "nintendocore",
        "rhythm game",
        "game"
    ]

class DevelopmentConfig(Config):
    DEBUG: bool = True

class ProductionConfig(Config):
    DEBUG: bool = False

# Configuration dictionary
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig
}

def get_config():
    return config[os.getenv("FLASK_ENV", "production")]
