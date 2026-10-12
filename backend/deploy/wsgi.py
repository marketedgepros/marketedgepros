"""Minimal production WSGI entry point."""

from src.app import create_app

app = create_app("production")
