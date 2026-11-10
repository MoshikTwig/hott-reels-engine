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


async def _speak(text, path, voice, rate, pitch="+0Hz"):
    """Save the audio and return each spoken word with its start and end in seconds."""
    words = []
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    with open(path, "wb") as audio:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((start, start + chunk["duration"] / 1e7, chunk["text"]))
    return words


def _even_words(text, seconds):
    """Spread words evenly when real timings are missing."""
    tokens = text.split()
    step = seconds / max(len(tokens), 1)
    return [(i * step, (i + 1) * step, word) for i, word in enumerate(tokens)]


def _silence(text, path):
    # Offline stand-in for testing: about 2.6 words per second.
    seconds = max(1.5, len(text.split()) / 2.6)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{seconds:.2f}", str(path)],
        check=True,
    )


def narrate(segments, workdir, voice, rate, pitch="+0Hz"):
    """Write one mp3 per segment and return (path, length, word timings) for each."""
    clips = []
    for i, segment in enumerate(segments):
        path = workdir / f"voice_{i}.mp3"
        words = []
        if os.environ.get("VOICE") == "silent":
            _silence(segment["voice"], path)
        else:
            words = asyncio.run(_speak(segment["voice"], path, voice, rate, pitch))
        seconds = duration(path)
        clips.append((path, seconds, words or _even_words(segment["voice"], seconds)))
    return clips
