"""All-in-one launcher: start a cloudflared quick tunnel, auto-capture its
public URL, then run the Blink -> WhatsApp monitor with image attachments.

This removes the manual step of copying the ephemeral tunnel URL into .env,
because cloudflared quick-tunnel URLs change on every restart.

Usage:
    python run_all.py

Requirements:
    - bin/cloudflared.exe present (downloaded already)
    - .env filled in (Blink, Twilio, GITHUB_TOKEN)

If you'd rather supply your own stable URL (e.g. a named tunnel or ngrok),
set PUBLIC_BASE_URL in .env and just run `python main.py` instead.
"""
import asyncio
import logging
import os
import re
import subprocess
import sys
import threading
import time

from src.config import Config
from src.monitor import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("run_all")

CLOUDFLARED = os.path.join(os.path.dirname(__file__), "bin", "cloudflared.exe")
URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def start_tunnel(port: int, timeout: float = 30.0) -> tuple[subprocess.Popen, str]:
    """Launch cloudflared and return (process, public_url)."""
    if not os.path.exists(CLOUDFLARED):
        raise FileNotFoundError(
            f"cloudflared not found at {CLOUDFLARED}. Download it first."
        )

    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url_holder: dict[str, str] = {}

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if "url" not in url_holder:
                m = URL_RE.search(line)
                if m:
                    url_holder["url"] = m.group(0)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    deadline = time.time() + timeout
    while time.time() < deadline:
        if "url" in url_holder:
            return proc, url_holder["url"]
        if proc.poll() is not None:
            raise RuntimeError("cloudflared exited before printing a URL.")
        time.sleep(0.25)

    proc.terminate()
    raise TimeoutError("Timed out waiting for cloudflared tunnel URL.")


def main() -> None:
    cfg = Config.load()

    log.info("Starting cloudflared quick tunnel on port %d...", cfg.media_port)
    proc, public_url = start_tunnel(cfg.media_port)
    log.info("Tunnel ready: %s", public_url)

    # Inject the freshly-captured URL so the monitor attaches images.
    cfg.public_base_url = public_url.rstrip("/")

    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        log.info("Shutting down tunnel...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
