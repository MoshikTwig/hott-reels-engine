"""Draw branded frames for each segment and assemble the vertical Reel with FFmpeg."""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "assets" / "logo.png"
FONT_CANDIDATES = [
    ROOT / "assets" / "fonts" / "Anton-Regular.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
PAD_SECONDS = 0.3


def _font(size):
    for path in FONT_CANDIDATES:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _wrap(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit(draw, text, max_width, max_lines, start, smallest):
    size = start
    while size > smallest:
        font = _font(size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font) <= max_width for l in lines):
            return font, lines
        size -= 6
    font = _font(smallest)
    return font, _wrap(draw, text, font, max_width)


def _centered(draw, lines, font, y, fill, gap=1.12):
    height = font.size * gap
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        draw.text(((draw.im.size[0] - width) / 2, y + i * height), line, font=font, fill=fill)
    return y + len(lines) * height


def background(width, height, brand):
    """Near-black canvas with a soft gold glow and film grain."""
    black, gold = _hex(brand["black"]), _hex(brand["gold"])
    base = Image.new("RGB", (width, height), black)
    glow = Image.new("L", (width, height), 0)
    ImageDraw.Draw(glow).ellipse((-width * 0.3, height * 0.18, width * 1.3, height * 0.72), fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    base = Image.composite(Image.new("RGB", (width, height), gold), base, glow)
    noise = Image.effect_noise((width // 2, height // 2), 18).resize((width, height))
    base = Image.blend(base, Image.merge("RGB", [noise] * 3), 0.04)
    draw = ImageDraw.Draw(base)
    inset = 36
    draw.rectangle((inset, inset, width - inset, height - inset), outline=gold, width=3)
    return base


def _logo(width):
    logo = Image.open(LOGO).convert("RGBA")
    return logo.resize((width, int(logo.height * width / logo.width)), Image.LANCZOS)


def _stamp(img, text, y, brand):
    gold, black, white = _hex(brand["gold"]), _hex(brand["black"]), _hex(brand["white"])
    font = _font(76)
    probe = ImageDraw.Draw(img)
    w = int(probe.textlength(text, font=font)) + 80
    h = 120
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    if text == "CONFIRMED":
        d.rounded_rectangle((0, 0, w - 1, h - 1), 14, fill=gold)
        d.text((40, 14), text, font=font, fill=black)
    else:
        d.rounded_rectangle((3, 3, w - 4, h - 4), 14, outline=white, width=6)
        d.text((40, 14), text, font=font, fill=white)
    tile = tile.rotate(6, expand=True, resample=Image.BICUBIC)
    img.paste(tile, ((img.width - tile.width) // 2, int(y)), tile)
    return y + tile.height


def draw_frame(segment, index, total, bg, brand):
    img = bg.copy()
    draw = ImageDraw.Draw(img)
    gold, white = _hex(brand["gold"]), _hex(brand["white"])
    W, H = img.size
    last = index == total - 1

    draw.rectangle((36, 36, 36 + (W - 72) * (index + 1) / total, 48), fill=gold)

    if last:
        # End card: full logo, the question, a call to comment. No subtitle.
        logo = _logo(380)
        img.paste(logo, ((W - logo.width) // 2, 150), logo)
        font, lines = _fit(draw, segment["screen"], W - 180, 3, 140, 80)
        y = _centered(draw, lines, font, 150 + logo.height + 80, gold)
        _centered(draw, ["COMMENT BELOW"], _font(64), y + 50, white)
        return img

    logo = _logo(170)
    img.paste(logo, ((W - logo.width) // 2, 90), logo)
    if segment.get("style") == "quote":
        text, max_lines, biggest, smallest = f"\u201c{segment['screen']}\u201d", 6, 120, 70
    else:
        text, max_lines, biggest, smallest = segment["screen"], 3, 180, 96
    font, lines = _fit(draw, text, W - 160, max_lines, biggest, smallest)
    block = len(lines) * font.size * 1.12
    y = _centered(draw, lines, font, max(420, 760 - block / 2), gold)
    if segment.get("stamp"):
        y = _stamp(img, segment["stamp"], y + 30, brand)
    if segment.get("style") == "quote":
        return img  # the quote on screen is already what the voice says
    # Subtitles stay above the bottom fifth, which the Reels buttons cover.
    sub_font, sub_lines = _fit(draw, segment["voice"], W - 200, 4, 58, 44)
    _centered(draw, sub_lines, sub_font, max(1240, y + 70), white, gap=1.25)
    return img


def segment_video(frame_path, audio_path, seconds, out_path, fps):
    frames = int((seconds + PAD_SECONDS) * fps)
    zoom = (
        f"scale=2160:-1,zoompan=z='min(1+0.0006*on,1.08)':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(frame_path), "-i", str(audio_path),
         "-vf", zoom, "-af", f"apad=pad_dur={PAD_SECONDS}", "-t", f"{seconds + PAD_SECONDS:.2f}",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out_path)],
        check=True,
    )


def assemble(segment_paths, out_path, music=None, music_volume=0.12):
    workdir = Path(out_path).parent
    listing = workdir / "segments.txt"
    listing.write_text("".join(f"file '{Path(p).name}'\n" for p in segment_paths))
    joined = workdir / "joined.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(joined)],
        check=True,
    )
    if not music:
        joined.replace(out_path)
        return
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-stream_loop", "-1", "-i", str(music),
         "-filter_complex",
         f"[1:a]volume={music_volume}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path)],
        check=True,
    )
    joined.unlink()
