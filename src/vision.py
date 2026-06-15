"""Describe camera frames using GitHub Models (OpenAI GPT-4o vision).

Uses the free GitHub Models inference endpoint, authenticated with a GitHub
personal access token (GITHUB_TOKEN). Falls back to a generic description if
the token is missing or the request fails, so the alert pipeline never breaks.
"""
import base64
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Free GitHub Models endpoint (Azure-style). The newer models.github.ai
# endpoint requires a billable account; this one works with a standard PAT.
ENDPOINT = "https://models.inference.ai.azure.com/chat/completions"

SYSTEM_PROMPT = (
    "You are a home security camera assistant. You are shown a numbered sequence "
    "of frames (frame 1, frame 2, ...) sampled in chronological order from a short "
    "motion-triggered video clip. Watch the WHOLE sequence and summarise what "
    "happens.\n\n"
    "Respond ONLY with a JSON object of the form:\n"
    '{"description": "<1-2 short sentences>", "key_frame": <N>}\n'
    "Guidelines for 'description':\n"
    "- Keep it concise: 1-2 sentences, roughly 15-35 words. No padding or "
    "filler.\n"
    "- Capture the key action and its progression, plus a few salient, clearly "
    "visible details: who/what appears, anything carried (laptop, bag, package), "
    "notable gestures or expressions (waving, smiling), and direction of movement "
    "(entering, leaving, approaching the door).\n"
    "- Natural and specific, like a brief eyewitness note, e.g. 'A man in a blue "
    "shirt walks in carrying a laptop, sets it down, then waves and smiles before "
    "leaving to the right.'\n"
    "- Only state what is actually visible; do not invent details. Do NOT mention "
    "frames, images, or the camera.\n"
    "If nothing meaningful is visible, use description 'Motion detected but no "
    "clear activity.'\n"
    "Set 'key_frame' to the NUMBER of the single frame that best/most clearly "
    "shows the main activity (subject most visible and central). "
    "Output ONLY the JSON, with no extra text."
)


@dataclass
class VisionResult:
    description: str
    key_frame_path: Optional[str] = None


def _subsample(paths: list[str], max_frames: int) -> list[str]:
    """Evenly pick at most ``max_frames`` items, preserving order (keeps first
    and last). Avoids overflowing the model's image limit while still covering
    the whole clip."""
    if max_frames <= 0 or len(paths) <= max_frames:
        return paths
    step = (len(paths) - 1) / (max_frames - 1)
    idx = sorted({round(i * step) for i in range(max_frames)})
    return [paths[i] for i in idx]


def _parse_response(text: str, selected: list[str]) -> VisionResult:
    """Parse the model's JSON reply into a VisionResult, mapping the 1-based
    key_frame number back to an actual frame path. Degrades gracefully if the
    reply isn't valid JSON."""
    description = text
    key_path: Optional[str] = None
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        obj = json.loads(m.group(0)) if m else json.loads(text)
        description = str(obj.get("description", text)).strip() or text
        kf = obj.get("key_frame")
        if kf is not None:
            i = int(kf) - 1  # frames are presented 1-based to the model
            if 0 <= i < len(selected):
                key_path = selected[i]
    except Exception:  # noqa: BLE001 - tolerate non-JSON replies
        log.debug("Could not parse key_frame from vision reply: %r", text)
    return VisionResult(description=description, key_frame_path=key_path)


class VisionDescriber:
    def __init__(
        self,
        token: Optional[str],
        model: str = "gpt-4o-mini",
        timeout: int = 60,
        max_frames: int = 16,
        detail: str = "low",
    ):
        self._token = token
        self._model = model
        self._timeout = timeout
        self._max_frames = max_frames
        # Image detail sent to the model: "low" (flat ~85 tokens/image — lets us
        # analyse many frames, good for tracking movement), "high" (sharper, sees
        # small objects / facial expressions / gestures, but costs far more tokens
        # so use fewer frames), or "auto".
        self._detail = detail or "low"

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def describe(self, jpeg_paths: list[str]) -> Optional[VisionResult]:
        """Analyse the JPEG frames (a chronological sequence) and return a
        VisionResult with a one-line description plus the path of the frame that
        best shows the activity. Returns None on failure (caller falls back to a
        generic message)."""
        if not self._token or not jpeg_paths:
            return None

        selected = _subsample(jpeg_paths, self._max_frames)
        log.info(
            "Vision analysing %d of %d captured frame(s).",
            len(selected),
            len(jpeg_paths),
        )

        content = [
            {
                "type": "text",
                "text": (
                    "These frames are in chronological order from one motion clip. "
                    "In 1-2 short sentences, describe the key activity with a few "
                    "salient details (objects carried, gestures, direction), then "
                    "pick the frame number that best shows the main activity."
                ),
            }
        ]
        for n, path in enumerate(selected, start=1):
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                # Label each image so the model can reference it by number.
                content.append({"type": "text", "text": f"frame {n}:"})
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            # Detail level is configurable (VISION_DETAIL). "low"
                            # is a flat ~85 tokens/image so we can feed many frames
                            # from the whole clip; "high" sees finer details
                            # (expressions, small objects) but costs many more
                            # tokens, so pair it with a smaller VISION_MAX_FRAMES.
                            "detail": self._detail,
                        },
                    }
                )
            except OSError:
                log.warning("Could not read frame %s", path)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "max_tokens": 160,
            "temperature": 0.3,
        }
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            result = _parse_response(text, selected)
            log.info(
                "Vision description: %s (key frame: %s)",
                result.description,
                result.key_frame_path and os.path.basename(result.key_frame_path),
            )
            return result
        except urllib.error.HTTPError as e:
            log.error("Vision API HTTP %s: %s", e.code, e.read().decode()[:200])
        except Exception:  # noqa: BLE001
            log.exception("Vision API call failed")
        return None
