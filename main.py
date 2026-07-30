"""Vercel entrypoint — the Python backend builder serves this ASGI app on all routes."""

from croissant_mcp.server import app  # noqa: F401
