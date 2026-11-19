"""Cloudflare Python Worker entrypoint."""
from workers import asgi
from backend.app import app

Default = asgi.entrypoint(app)
