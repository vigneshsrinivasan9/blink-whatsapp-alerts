"""Blink camera client built on the community `blinkpy` library.

Blink has no official public API, so this uses blinkpy (reverse-engineered).
First login requires a 2FA code emailed/texted by Blink; after that the session
credentials are cached to a JSON file so the monitor can run headless.
"""
import logging
import os

from aiohttp import ClientSession
from blinkpy.auth import Auth, BlinkTwoFARequiredError
from blinkpy.blinkpy import Blink
from blinkpy.helpers.util import json_load

log = logging.getLogger(__name__)


async def create_blink_from_cache(creds_file: str, session: ClientSession) -> Blink:
    """Create and start a Blink instance from cached credentials.

    Raises FileNotFoundError if the credentials file does not exist yet
    (run setup_2fa.py first).
    """
    if not os.path.exists(creds_file):
        raise FileNotFoundError(
            f"Blink credentials file '{creds_file}' not found. "
            f"Run `python -m src.setup_2fa` once to perform the 2FA login."
        )

    blink = Blink(session=session)
    blink.auth = Auth(await json_load(creds_file), no_prompt=True, session=session)
    await blink.start()
    log.info("Blink started. Cameras: %s", list(blink.cameras.keys()))
    return blink


async def login_interactive(
    username: str, password: str, creds_file: str, session: ClientSession
) -> Blink:
    """Perform a fresh, interactive login (prompts for a 2FA code) and cache
    the resulting credentials to `creds_file`."""
    blink = Blink(session=session)
    blink.auth = Auth(
        {"username": username, "password": password},
        no_prompt=True,
        session=session,
    )

    try:
        await blink.start()
    except BlinkTwoFARequiredError:
        code = input("Enter the 2FA code Blink just sent you: ").strip()
        if not await blink.send_2fa_code(code):
            raise RuntimeError("2FA verification failed. Check the code and retry.")

    await blink.save(creds_file)
    log.info("Login successful. Credentials cached to %s", creds_file)
    return blink


def detect_motion(blink: Blink) -> list[str]:
    """Return the names of cameras that have reported motion since the last
    refresh."""
    triggered = []
    for name, camera in blink.cameras.items():
        if getattr(camera, "motion_detected", False):
            triggered.append(name)
    return triggered
