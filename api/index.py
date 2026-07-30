"""Vercel entrypoint — exposes the ASGI app from croissant_mcp."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from croissant_mcp.server import app  # noqa: E402, F401
