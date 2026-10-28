"""Turn each script line into narration with free Microsoft neural voices."""

import asyncio
import os
import subprocess

import edge_tts


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


async def _speak(text, path, voice, rate):
    await edge_tts.Communicate(text, voice, rate=rate).save(str(path))


def _silence(text, path):
    # Offline stand-in for testing: about 2.6 words per second.
    seconds = max(1.5, len(text.split()) / 2.6)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{seconds:.2f}", str(path)],
        check=True,
    )


def narrate(segments, workdir, voice, rate):
    """Write one mp3 per segment and return their paths and lengths."""
    clips = []
    for i, segment in enumerate(segments):
        path = workdir / f"voice_{i}.mp3"
        if os.environ.get("VOICE") == "silent":
            _silence(segment["voice"], path)
        else:
            asyncio.run(_speak(segment["voice"], path, voice, rate))
        clips.append((path, duration(path)))
    return clips
