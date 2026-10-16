"""Application factory for the container workflow demo survey."""

import os
import secrets

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db, routes

# The value shipped in .env.example. Production refuses to start with it.
PLACEHOLDER_SECRET_KEY = "change-me"


def create_app(test_config=None):
    """Create and configure the Flask app.

    All settings come from environment variables. Tests pass test_config to
    override them.
    """
    app = Flask(__name__)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        # Flask itself no longer reads FLASK_ENV. This app uses it to decide
        # whether the strict production checks apply.
        FLASK_ENV=os.environ.get("FLASK_ENV", "production"),
        # Containers set /data/survey.db. Bare local runs default to ./instance/survey.db.
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH", os.path.join(app.instance_path, "survey.db")
        ),
        TRUST_PROXY=os.environ.get("TRUST_PROXY", "0") == "1",
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    check_secret_key(app)

    # Behind nginx, trust one hop of X-Forwarded-* headers so Flask sees the
    # real client address and scheme. Off when Flask is reached directly.
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    app.register_blueprint(routes.bp)
    return app


def check_secret_key(app):
    """Refuse to start in production without a real SECRET_KEY."""
    key = app.config["SECRET_KEY"]
    if app.config["FLASK_ENV"] != "development":
        if not key or key == PLACEHOLDER_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY is missing or still set to the example placeholder. "
                "Set a real random value in .env before starting in production."
            )
    elif not key:
        # Development only: a throwaway key so sessions and CSRF still work.
        app.config["SECRET_KEY"] = secrets.token_hex(32)
