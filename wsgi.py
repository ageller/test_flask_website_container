"""Entry point for gunicorn ("wsgi:app") and the Flask CLI ("flask --app wsgi run")."""

from app import create_app

app = create_app()
