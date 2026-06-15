"""One-time interactive Blink login to handle 2FA and cache credentials.

Run once before starting the monitor:

    python -m src.setup_2fa
"""
import asyncio
import logging

from aiohttp import ClientSession

from .blink_client import login_interactive
from .config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def _main() -> None:
    cfg = Config.load()
    async with ClientSession() as session:
        await login_interactive(
            cfg.blink_username, cfg.blink_password, cfg.blink_creds_file, session
        )
    print(f"Done. Credentials saved to {cfg.blink_creds_file}.")


if __name__ == "__main__":
    asyncio.run(_main())
