"""Send a single test WhatsApp message to confirm Twilio is configured.

    python -m src.test_whatsapp
"""
import logging

from .config import Config
from .whatsapp_client import WhatsAppClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    cfg = Config.load()
    whatsapp = WhatsAppClient(
        cfg.twilio_account_sid,
        cfg.twilio_auth_token,
        cfg.twilio_whatsapp_from,
        cfg.whatsapp_to,
        content_sid=cfg.twilio_content_sid or None,
    )
    whatsapp.send_motion_alert(
        camera="Test Camera",
        timestamp="2026-06-14 14:02:00",
        description="Motion detected (test message).",
    )


if __name__ == "__main__":
    main()
