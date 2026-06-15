"""Configuration loaded from environment / .env file."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


@dataclass
class Config:
    # Blink
    blink_username: str
    blink_password: str
    blink_creds_file: str

    # Twilio / WhatsApp
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str
    whatsapp_to: str
    twilio_content_sid: str

    # Telegram fallback (free; no tunnel needed)
    telegram_bot_token: str
    telegram_chat_id: str
    notify_mode: str

    # Monitor
    poll_interval: int
    alert_cooldown: int

    # Vision (GitHub Models)
    github_token: str
    vision_model: str
    vision_detail: str
    clip_fps: float
    vision_max_frames: int
    media_max_frames: int

    # Media serving (for WhatsApp image attachments)
    public_base_url: str
    media_port: int
    frames_dir: str

    @classmethod
    def load(cls) -> "Config":
        return cls(
            blink_username=_require("BLINK_USERNAME"),
            blink_password=_require("BLINK_PASSWORD"),
            blink_creds_file=os.getenv("BLINK_CREDS_FILE", "blink_creds.json"),
            twilio_account_sid=_require("TWILIO_ACCOUNT_SID"),
            twilio_auth_token=_require("TWILIO_AUTH_TOKEN"),
            twilio_whatsapp_from=_require("TWILIO_WHATSAPP_FROM"),
            whatsapp_to=_require("WHATSAPP_TO"),
            twilio_content_sid=os.getenv("TWILIO_CONTENT_SID", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            notify_mode=os.getenv("NOTIFY_MODE", "whatsapp_first"),
            poll_interval=int(os.getenv("POLL_INTERVAL", "15")),
            alert_cooldown=int(os.getenv("ALERT_COOLDOWN", "60")),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            vision_model=os.getenv("VISION_MODEL", "gpt-4o-mini"),
            vision_detail=os.getenv("VISION_DETAIL", "low"),
            clip_fps=float(os.getenv("CLIP_FPS", "2")),
            vision_max_frames=int(os.getenv("VISION_MAX_FRAMES", "16")),
            media_max_frames=int(os.getenv("MEDIA_MAX_FRAMES", "4")),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            media_port=int(os.getenv("MEDIA_PORT", "8088")),
            frames_dir=os.getenv("FRAMES_DIR", "frames"),
        )
