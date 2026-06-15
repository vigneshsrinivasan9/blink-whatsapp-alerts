"""Thin wrapper around Twilio's WhatsApp API.

Supports two send modes:

* **Template** (recommended): uses a pre-approved Content template
  (``content_sid`` + ``content_variables``). Templates deliver even outside
  WhatsApp's 24-hour customer-service window, which is essential for
  unsolicited motion alerts that may fire days apart.
* **Freeform** (fallback): a plain text ``body``. Only delivers if the
  recipient messaged your number in the last 24 hours (e.g. the sandbox).

The motion template uses three variables:
    {{1}} = camera name
    {{2}} = timestamp
    {{3}} = activity description (generic "Motion detected." for now)
"""
import json
import logging
from typing import Optional

from twilio.rest import Client

log = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_: str,
        to: str,
        content_sid: Optional[str] = None,
    ):
        self._client = Client(account_sid, auth_token)
        self._from = from_
        self._to = to
        self._content_sid = content_sid

    def send_motion_alert(
        self,
        camera: str,
        timestamp: str,
        description: str = "Motion detected.",
        media_urls: Optional[list] = None,
    ) -> bool:
        """Send a motion alert. Uses the configured Content template when
        available, otherwise falls back to a freeform text message. When
        `media_urls` are given (public URLs), images are attached. Returns True
        on success, False on failure (e.g. exhausted Twilio credits)."""
        if self._content_sid:
            variables = {"1": camera, "2": timestamp, "3": description}
            return self._send_template(
                variables, fallback_summary=f"{camera} @ {timestamp}"
            )
        body = f"{description}\n🚨 Motion on '{camera}' at {timestamp}."
        return self.send(body, media_urls=media_urls)

    def _send_template(self, variables: dict, fallback_summary: str) -> bool:
        try:
            message = self._client.messages.create(
                from_=self._from,
                to=self._to,
                content_sid=self._content_sid,
                content_variables=json.dumps(variables),
            )
            log.info(
                "WhatsApp template sent (sid=%s): %s", message.sid, fallback_summary
            )
            return True
        except Exception:  # noqa: BLE001 - we never want to kill the loop
            log.exception("Failed to send WhatsApp template: %s", fallback_summary)
            return False

    def send(self, body: str, media_urls: Optional[list] = None) -> bool:
        """Send a freeform WhatsApp message, optionally with image media URLs.
        Logs and swallows errors so a send failure never crashes the loop.
        Returns True on success, False on failure."""
        kwargs = {"from_": self._from, "to": self._to, "body": body}
        if media_urls:
            # Twilio WhatsApp allows a single media item per message; send the
            # first as media and note the rest in the body if needed.
            kwargs["media_url"] = media_urls[:10]
        try:
            message = self._client.messages.create(**kwargs)
            log.info("WhatsApp message sent (sid=%s): %s", message.sid, body)
            return True
        except Exception:  # noqa: BLE001 - we never want to kill the loop
            log.exception("Failed to send WhatsApp message: %s", body)
            return False
