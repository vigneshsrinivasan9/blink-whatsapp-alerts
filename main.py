"""Entry point: start the Blink motion -> WhatsApp alert monitor.

Usage:
    python main.py
"""
import asyncio
import logging

from src.config import Config
from src.monitor import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def main() -> None:
    cfg = Config.load()
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
