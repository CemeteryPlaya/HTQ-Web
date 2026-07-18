"""Transmux WebM/Opus voice messages → Ogg/Opus container.

Browsers vary in what ``MediaRecorder`` can produce:

* Firefox writes native ``audio/ogg;codecs=opus``.
* Chromium-based browsers only emit ``audio/webm;codecs=opus``, even when
  the requested mimeType is ``audio/ogg``.

The frontend always uploads voice files with a ``.ogg`` filename per the
product requirement, but the bytes inside may be a WebM container. This
helper detects that case and re-muxes the bitstream into a real Ogg
container with ``ffmpeg -c copy`` — a stream copy, no re-encode, finishes
in <100ms even for several minutes of audio.

Falls back to the original buffer if ffmpeg is missing, the input isn't
recognised as WebM, or the conversion fails — better to ship the file as
WebM than lose the user's voice message.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile

log = logging.getLogger(__name__)


_WEBM_CONTENT_TYPES = {
    "audio/webm",
    "audio/webm;codecs=opus",
    "audio/webm; codecs=opus",
}


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def should_transmux_to_ogg(content_type: str, filename: str) -> bool:
    """Trigger transmux only for the voice-message shape: WebM input + .ogg name."""
    if not filename.lower().endswith(".ogg"):
        return False
    ct = (content_type or "").lower().replace(" ", "")
    return ct in {c.replace(" ", "") for c in _WEBM_CONTENT_TYPES}


async def transmux_webm_to_ogg(buffer: bytes) -> bytes | None:
    """Run ``ffmpeg -c copy`` to repackage WebM/Opus → Ogg/Opus.

    Returns the new bytes on success, ``None`` on failure (caller keeps the
    original buffer). Uses temp files because ffmpeg expects a seekable
    input for WebM/Matroska parsing — pipe-to-stdin isn't reliable.
    """
    if not _has_ffmpeg():
        log.warning("transmux_skipped: ffmpeg not installed")
        return None

    src_path: str | None = None
    dst_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as src:
            src.write(buffer)
            src_path = src.name
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as dst:
            dst_path = dst.name

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",  # overwrite output
            "-loglevel", "error",
            "-i", src_path,
            "-c:a", "copy",  # stream copy — Opus stays Opus
            "-map_metadata", "-1",
            "-f", "ogg",
            dst_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            log.warning("transmux_timeout")
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return None

        if proc.returncode != 0:
            log.warning(
                "transmux_failed code=%s stderr=%s",
                proc.returncode,
                (stderr or b"").decode(errors="replace")[:200],
            )
            return None

        with open(dst_path, "rb") as f:
            out = f.read()
        if not out:
            return None
        return out
    finally:
        for p in (src_path, dst_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
