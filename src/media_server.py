"""Tiny static file server for camera frames.

Twilio fetches WhatsApp media from a public URL, so frames must be reachable
over HTTP. This serves the frames directory on a background thread. To actually
attach images, expose this port publicly (e.g. an ngrok/cloudflared tunnel) and
set PUBLIC_BASE_URL to the tunnel URL.
"""
import functools
import logging
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)


def start_media_server(directory: str, port: int) -> ThreadingHTTPServer:
    """Start a background HTTP server rooted at `directory`. Returns the server
    instance (call .shutdown() to stop)."""
    handler = functools.partial(_QuietHandler, directory=directory)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("Media server serving '%s' on port %d", directory, port)
    return server


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request stderr logging
        pass
