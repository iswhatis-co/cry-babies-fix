import os
from flask import Flask, request, redirect, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
from redis import Redis

from dotenv import load_dotenv
load_dotenv()

from config import Config

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

def create_app(config_class=Config):
    app = Flask(__name__, static_folder='static', static_url_path='/static')
    app.config.from_object(config_class)
    app.secret_key = app.config["SECRET_KEY"]

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    app.config["SESSION_TYPE"] = "redis"
    app.config["SESSION_PERMANENT"] = True
    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "None"

    if app.config["ENV"] == "production":
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_DOMAIN"] = os.getenv("SESSION_COOKIE_DOMAIN")
    else:
        app.config["SESSION_COOKIE_SECURE"] = False
        app.config["SESSION_COOKIE_DOMAIN"] = None

    app.config.update(
        SESSION_COOKIE_SECURE=app.config["SESSION_COOKIE_SECURE"],
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    app.config["SESSION_REDIS"] = Redis.from_url(redis_url)
    Session(app)

    @app.before_request
    def before_request():
        if not request.is_secure and app.config["ENV"] == "production":
            url = request.url.replace("http://", "https://", 1)
            return redirect(url, code=301)

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                'chfavicon.ico', mimetype='image/vnd.microsoft.icon')

    @app.route('/static/<path:filename>')
    def serve_static(filename):
        root_dir = os.path.dirname(os.getcwd())
        return send_from_directory(os.path.join(root_dir, 'static'), filename)

    with app.app_context():
        from app import models
        from app.routes.main_flow_bp import main_flow_bp
        app.register_blueprint(main_flow_bp)

    app.logger.info("Flask application initialized")
    return app

from app import models
