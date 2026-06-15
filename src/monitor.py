"""Continuous monitor: detect Blink motion -> capture frames -> describe with
vision -> send alert via WhatsApp (Twilio) with Telegram as a free fallback."""
import asyncio
import logging
import os
import socket
import time

import aiohttp
from aiohttp import ClientSession

from .blink_client import create_blink_from_cache, detect_motion
from .clip_analyzer import capture_frames
from .config import Config
from .media_server import start_media_server
from .notifier import Notifier
from .telegram_client import TelegramClient
from .vision import VisionDescriber
from .whatsapp_client import WhatsAppClient

log = logging.getLogger(__name__)


async def run(cfg: Config) -> None:
    whatsapp = WhatsAppClient(
        cfg.twilio_account_sid,
        cfg.twilio_auth_token,
        cfg.twilio_whatsapp_from,
        cfg.whatsapp_to,
        content_sid=cfg.twilio_content_sid or None,
    )
    telegram = TelegramClient(
        cfg.telegram_bot_token or None, cfg.telegram_chat_id or None
    )
    notifier = Notifier(whatsapp=whatsapp, telegram=telegram, mode=cfg.notify_mode)
    vision = VisionDescriber(
        cfg.github_token or None,
        model=cfg.vision_model,
        max_frames=cfg.vision_max_frames,
        detail=cfg.vision_detail,
    )

    frames_dir = os.path.abspath(cfg.frames_dir)
    os.makedirs(frames_dir, exist_ok=True)

    # Serve frames over HTTP so Twilio can fetch them (needs PUBLIC_BASE_URL to
    # actually attach images; otherwise alerts are text-only).
    media_server = None
    if cfg.public_base_url:
        media_server = start_media_server(frames_dir, cfg.media_port)
        log.info("Image attachments enabled via %s", cfg.public_base_url)
    else:
        log.info("PUBLIC_BASE_URL not set -> sending text-only alerts (no images).")

    log.info(
        "Vision: %s | Telegram fallback: %s | Mode: %s | Poll: %ds | Cooldown: %ds",
        "ENABLED" if vision.enabled else "disabled (no GITHUB_TOKEN)",
        "ENABLED" if notifier.telegram_enabled else "disabled (no TELEGRAM_*)",
        cfg.notify_mode,
        cfg.poll_interval,
        cfg.alert_cooldown,
    )

    last_alert: dict[str, float] = {}

    try:
        async with ClientSession() as session:
            blink = await create_blink_from_cache(cfg.blink_creds_file, session)
            log.info("Monitoring camera(s): %s", list(blink.cameras.keys()))

            while True:
                try:
                    await blink.refresh(force=True)
                    states = {
                        name: bool(getattr(cam, "motion_detected", False))
                        for name, cam in blink.cameras.items()
                    }
                    log.info(
                        "Poll @ %s | motion: %s",
                        time.strftime("%H:%M:%S"),
                        ", ".join(f"{n}={'YES' if s else 'no'}" for n, s in states.items()),
                    )
                    for camera in detect_motion(blink):
                        now = time.monotonic()
                        if now - last_alert.get(camera, 0) < cfg.alert_cooldown:
                            log.info("Motion on '%s' but within cooldown; skipping.", camera)
                            continue
                        last_alert[camera] = now
                        await _handle_motion(
                            cfg, blink, camera, frames_dir, vision, notifier
                        )
                except (
                    aiohttp.ClientError,
                    socket.gaierror,
                    ConnectionError,
                    asyncio.TimeoutError,
                    AttributeError,  # blinkpy raises this when a request returns None
                ) as e:
                    # Transient network/Blink-backend hiccup (e.g. DNS failure,
                    # throttling). Log concisely and keep polling; no traceback.
                    log.warning(
                        "Transient connection issue (%s); will retry next poll.",
                        type(e).__name__,
                    )
                except Exception:  # noqa: BLE001 - keep loop alive on unexpected errors
                    log.exception("Unexpected error during cycle; will retry.")

                await asyncio.sleep(cfg.poll_interval)
    finally:
        if media_server is not None:
            media_server.shutdown()


async def _handle_motion(cfg, blink, camera, frames_dir, vision, notifier) -> None:
    """Process a single motion event end-to-end."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log.info("Motion on '%s' -> capturing frames...", camera)

    frames = await capture_frames(blink, camera, frames_dir, clip_fps=cfg.clip_fps)

    description = "Motion detected."
    key_frame = None
    if frames and vision.enabled:
        result = await asyncio.to_thread(vision.describe, frames)
        if result:
            description = result.description
            key_frame = result.key_frame_path

    # Pick the frames that best show the activity (centered on the model's key
    # frame). The same selection is used for both channels: WhatsApp needs public
    # URLs (via the tunnel), while Telegram uploads the local files directly.
    media_frames = []
    if frames:
        media_frames = _select_media_frames(frames, key_frame, cfg.media_max_frames)

    media_urls = None
    if cfg.public_base_url and media_frames:
        media_urls = [
            f"{cfg.public_base_url}/{os.path.basename(p)}" for p in media_frames
        ]

    notifier.send_motion_alert(
        camera,
        timestamp,
        description=description,
        media_urls=media_urls,
        image_paths=media_frames or None,
    )
    log.info("Alert sent for '%s': %s", camera, description)


def _select_media_frames(frames: list, key_frame, max_items: int) -> list:
    """Choose which frames to attach to WhatsApp.

    Centers the selection on ``key_frame`` (the model's most-representative
    frame) so the image actually matches the description. Adds nearby frames for
    context, keeping chronological order. Falls back to an even sample if the key
    frame is unknown."""
    if max_items <= 0 or not frames:
        return []
    if key_frame is None or key_frame not in frames:
        return _evenly_sample(frames, max_items)

    center = frames.index(key_frame)
    chosen = {center}
    offset = 1
    # Expand outward from the key frame until we have enough.
    while len(chosen) < min(max_items, len(frames)):
        for i in (center - offset, center + offset):
            if 0 <= i < len(frames):
                chosen.add(i)
            if len(chosen) >= min(max_items, len(frames)):
                break
        offset += 1
    return [frames[i] for i in sorted(chosen)]


def _evenly_sample(items: list, max_items: int) -> list:
    """Pick at most ``max_items`` evenly-spaced items, keeping first and last."""
    if max_items <= 0 or len(items) <= max_items:
        return items
    step = (len(items) - 1) / (max_items - 1)
    idx = sorted({round(i * step) for i in range(max_items)})
    return [items[i] for i in idx]
