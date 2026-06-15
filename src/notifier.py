"""Notification orchestrator with automatic failover.

Coordinates one or more delivery channels so an alert still gets through if the
primary channel fails (e.g. Twilio/WhatsApp credits exhausted).

Modes (NOTIFY_MODE):
* ``whatsapp_first`` (default) — try WhatsApp; if it fails, fall back to Telegram.
* ``telegram_first``           — try Telegram; if it fails, fall back to WhatsApp.
* ``both``                     — always send on every enabled channel (redundant).
* ``whatsapp_only`` / ``telegram_only`` — single channel, no fallback.

WhatsApp attaches images via public ``media_urls`` (needs the tunnel); Telegram
uploads the local image files directly (no tunnel needed), so the orchestrator
passes both forms and each channel uses what it needs.
"""
import logging
from typing import Optional

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, whatsapp=None, telegram=None, mode: str = "whatsapp_first"):
        self._whatsapp = whatsapp
        self._telegram = telegram
        self._mode = (mode or "whatsapp_first").lower()

    @property
    def telegram_enabled(self) -> bool:
        return bool(self._telegram and self._telegram.enabled)

    def _send_whatsapp(self, camera, timestamp, description, media_urls) -> bool:
        if not self._whatsapp:
            return False
        return self._whatsapp.send_motion_alert(
            camera, timestamp, description=description, media_urls=media_urls
        )

    def _send_telegram(self, camera, timestamp, description, image_paths) -> bool:
        if not self.telegram_enabled:
            return False
        return self._telegram.send_motion_alert(
            camera, timestamp, description=description, image_paths=image_paths
        )

    def send_motion_alert(
        self,
        camera: str,
        timestamp: str,
        description: str = "Motion detected.",
        media_urls: Optional[list] = None,
        image_paths: Optional[list] = None,
    ) -> bool:
        """Deliver an alert according to the configured mode/failover. Returns
        True if at least one channel succeeded."""
        wa = lambda: self._send_whatsapp(camera, timestamp, description, media_urls)  # noqa: E731
        tg = lambda: self._send_telegram(camera, timestamp, description, image_paths)  # noqa: E731

        if self._mode == "both":
            ok_wa = wa()
            ok_tg = tg()
            return ok_wa or ok_tg

        if self._mode == "whatsapp_only":
            return wa()

        if self._mode == "telegram_only":
            return tg()

        if self._mode == "telegram_first":
            if tg():
                return True
            log.warning("Telegram send failed; falling back to WhatsApp.")
            return wa()

        # default: whatsapp_first
        if wa():
            return True
        if self.telegram_enabled:
            log.warning(
                "WhatsApp send failed (credits exhausted?); falling back to Telegram."
            )
            return tg()
        log.error(
            "WhatsApp send failed and no Telegram fallback is configured. "
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable it."
        )
        return False
