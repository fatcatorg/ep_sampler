#!/usr/bin/env python3
"""Audio helpers: WAV conversion to the EP-133 .ppak format (44.1 kHz stereo
16-bit PCM) and frame counting."""

import subprocess
import wave
from pathlib import Path


def wav_frame_count(path: Path) -> int:
    with wave.open(str(path), "rb") as w:
        return w.getnframes()


def convert_wav(src: Path, dst: Path, tool: str = "ffmpeg",
                ffmpeg_bin: str = "ffmpeg", sox_bin: str = "sox",
                extra_args: list[str] | None = None) -> None:
    """Convert `src` to 44.1 kHz stereo 16-bit PCM at `dst`."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    extra = list(extra_args or [])

    if tool == "sox":
        cmd = [sox_bin, str(src), "-c", "2", "-r", "44100",
               "-b", "16", "-e", "signed-integer"] + extra + [str(dst)]
    else:
        cmd = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(src), "-ac", "2", "-ar", "44100",
               "-c:a", "pcm_s16le"] + extra + [str(dst)]

    subprocess.run(cmd, check=True)
