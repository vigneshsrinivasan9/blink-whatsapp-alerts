"""Telegram Bot notifier — a free, reliable fallback for WhatsApp/Twilio.

Why Telegram as a fallback:
* **Free and unlimited** — no per-message cost, so it keeps working after Twilio
  trial credits are exhausted.
* **Native image upload** — the bot uploads the frame bytes directly via
  ``sendPhoto`` / ``sendMediaGroup``, so it does NOT need a public media URL or
  the cloudflared tunnel that WhatsApp requires.

Setup (one time):
1. In Telegram, message ``@BotFather`` -> ``/newbot`` -> follow prompts. It gives
   you a bot **token** like ``123456:ABC-DEF...``.
2. Send any message to your new bot from your phone (so it can reply to you).
3. Get your **chat id**: open
   ``https://api.telegram.org/bot<TOKEN>/getUpdates`` in a browser and read
   ``result[].message.chat.id``.
4. Put both in ``.env`` as ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``.
"""
import json
import logging
import mimetypes
import urllib.error
import urllib.request
import uuid
from typing import Optional

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def _multipart(fields: dict, files: list) -> tuple[bytes, str]:
    """Build a multipart/form-data body. ``files`` is a list of
    (field_name, filename, content_bytes, content_type)."""
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"
    body = bytearray()
    for name, value in fields.items():
        body += b"--" + boundary.encode() + crlf
        body += f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf
        body += str(value).encode() + crlf
    for name, filename, content, ctype in files:
        body += b"--" + boundary.encode() + crlf
        body += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'
        ).encode() + crlf
        body += f"Content-Type: {ctype}".encode() + crlf + crlf
        body += content + crlf
    body += b"--" + boundary.encode() + b"--" + crlf
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class TelegramClient:
    def __init__(self, token: Optional[str], chat_id: Optional[str], timeout: int = 30):
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def _post(self, method: str, body: bytes, content_type: str) -> bool:
        url = f"{API_BASE}/bot{self._token}/{method}"
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": content_type}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
            if not data.get("ok"):
                log.error("Telegram %s failed: %s", method, data)
                return False
            return True
        except urllib.error.HTTPError as e:
            log.error("Telegram %s HTTP %s: %s", method, e.code, e.read().decode()[:200])
        except Exception:  # noqa: BLE001
            log.exception("Telegram %s call failed", method)
        return False

    def send(self, text: str, image_paths: Optional[list] = None) -> bool:
        """Send a text message, optionally with images uploaded directly.

        * 0 images -> sendMessage
        * 1 image  -> sendPhoto with caption
        * N images -> sendMediaGroup (album) with caption on the first
        Returns True on success."""
        if not self.enabled:
            return False

        images = []
        for p in (image_paths or []):
            try:
                with open(p, "rb") as f:
                    images.append((p, f.read()))
            except OSError:
                log.warning("Telegram: could not read image %s", p)

        if not images:
            body, ct = _multipart({"chat_id": self._chat_id, "text": text}, [])
            return self._post("sendMessage", body, ct)

        if len(images) == 1:
            name, content = images[0]
            ctype = mimetypes.guess_type(name)[0] or "image/jpeg"
            files = [("photo", "frame.jpg", content, ctype)]
            body, ct = _multipart(
                {"chat_id": self._chat_id, "caption": text}, files
            )
            return self._post("sendPhoto", body, ct)

        # Album: up to 10 photos, caption on the first.
        images = images[:10]
        media = []
        files = []
        for i, (name, content) in enumerate(images):
            attach = f"file{i}"
            ctype = mimetypes.guess_type(name)[0] or "image/jpeg"
            item = {"type": "photo", "media": f"attach://{attach}"}
            if i == 0:
                item["caption"] = text
            media.append(item)
            files.append((attach, f"{attach}.jpg", content, ctype))
        body, ct = _multipart(
            {"chat_id": self._chat_id, "media": json.dumps(media)}, files
        )
        return self._post("sendMediaGroup", body, ct)

    def send_motion_alert(
        self,
        camera: str,
        timestamp: str,
        description: str = "Motion detected.",
        image_paths: Optional[list] = None,
    ) -> bool:
        body = f"{description}\n🚨 Motion on '{camera}' at {timestamp}."
        return self.send(body, image_paths=image_paths)
