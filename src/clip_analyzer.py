"""Capture frames for a motion event from a Blink camera.

Strategy (fast + robust):
1. Request a fresh snapshot (snap_picture) and save it — this is instant and
   always available, giving us at least one frame for vision + WhatsApp media.
2. Best-effort: download the most recent recorded clip and extract frames
   spanning the ENTIRE clip (sampled at a steady FPS) with the bundled ffmpeg,
   so the vision model sees the whole sequence of activity rather than just the
   first moment. Clips lag behind motion (Blink must record and upload them), so
   this is optional and never blocks the alert.
"""
import glob
import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger(__name__)


def _resolve_ffmpeg() -> str:
    """Find an ffmpeg binary, in priority order:
    1. FFMPEG_BINARY env var (explicit override),
    2. system ffmpeg on PATH (preferred on Linux/ARM, e.g. Raspberry Pi),
    3. the binary bundled by imageio-ffmpeg (works on Windows/x86).
    Returns "ffmpeg" as a last resort."""
    override = os.getenv("FFMPEG_BINARY")
    if override and os.path.exists(override):
        return override

    system = shutil.which("ffmpeg")
    if system:
        return system

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        log.warning("Could not resolve a bundled ffmpeg; falling back to 'ffmpeg'.")
        return "ffmpeg"


FFMPEG = _resolve_ffmpeg()


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_") or "cam"


async def capture_frames(
    blink,
    camera_name: str,
    out_dir: str,
    clip_fps: float = 2.0,
) -> list[str]:
    """Capture frames for the given camera.

    Returns a chronological list of JPEG paths: the fresh snapshot first,
    followed by frames sampled across the whole recorded clip (at ``clip_fps``
    frames per second).
    """
    os.makedirs(out_dir, exist_ok=True)
    camera = blink.cameras.get(camera_name)
    if camera is None:
        return []

    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"{_safe(camera_name)}_{stamp}"
    frames: list[str] = []

    # 1) Fresh snapshot (instant, reliable).
    snap_path = os.path.join(out_dir, f"{base}_snap.jpg")
    try:
        await camera.snap_picture()
        await blink.refresh(force=True)
        await camera.image_to_file(snap_path)
        if os.path.exists(snap_path) and os.path.getsize(snap_path) > 0:
            frames.append(snap_path)
    except Exception:  # noqa: BLE001
        log.exception("Snapshot capture failed for %s", camera_name)

    # 2) Best-effort: extract frames across the ENTIRE clip.
    if clip_fps > 0:
        mp4_path = os.path.join(out_dir, f"{base}.mp4")
        try:
            await camera.video_to_file(mp4_path)
            if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
                clip_frames = _extract_all_frames(mp4_path, out_dir, base, clip_fps)
                frames.extend(clip_frames)
                log.info(
                    "Extracted %d frame(s) across the clip for '%s'.",
                    len(clip_frames),
                    camera_name,
                )
        except Exception:  # noqa: BLE001
            log.debug("Clip download/extract skipped for %s", camera_name, exc_info=True)

    return frames


def _extract_all_frames(
    mp4_path: str, out_dir: str, base: str, fps: float
) -> list[str]:
    """Extract frames spanning the whole clip at ``fps`` frames per second.

    Uses ffmpeg's ``fps`` filter, which walks the entire video and emits an
    evenly-spaced frame every 1/fps seconds — covering the full duration rather
    than just the start. Returns the extracted JPEG paths in chronological order.
    """
    pattern = os.path.join(out_dir, f"{base}_f%03d.jpg")
    cmd = [
        FFMPEG, "-y", "-i", mp4_path,
        "-vf", f"fps={fps},scale=640:-1",
        "-qscale:v", "3",
        pattern,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except Exception:  # noqa: BLE001
        log.debug("ffmpeg frame extraction failed for %s", mp4_path, exc_info=True)
        return []

    out = sorted(glob.glob(os.path.join(out_dir, f"{base}_f*.jpg")))
    return [p for p in out if os.path.getsize(p) > 0]
