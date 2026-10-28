"""Build each segment from a real photo, branded overlays and word-by-word captions, then assemble the Reel."""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "assets" / "logo.png"
FONT_DIR = ROOT / "assets" / "fonts"
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
    """Near-black canvas with a soft gold glow, used when no photo is found."""
    black, gold = _hex(brand["black"]), _hex(brand["gold"])
    base = Image.new("RGB", (width, height), black)
    glow = Image.new("L", (width, height), 0)
    ImageDraw.Draw(glow).ellipse((-width * 0.3, height * 0.18, width * 1.3, height * 0.72), fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    return Image.composite(Image.new("RGB", (width, height), gold), base, glow)


def _cover(img, width, height, focus_y=0.35):
    """Scale to fill the frame and crop, keeping the upper part where faces usually are."""
    scale = max(width / img.width, height / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - width) // 2
    top = int(max(0, min(img.height - height, img.height * focus_y - height * focus_y)))
    return img.crop((left, top, left + width, top + height))


def photo_canvas(photo, width, height, bg):
    """A full-screen photo. Landscape shots sit large over a blurred copy of themselves."""
    if photo is None:
        return bg.copy()
    img = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    if img.height / img.width >= 1.15:
        canvas = _cover(img, width, height)
    else:
        canvas = _cover(img, width, height).filter(ImageFilter.GaussianBlur(40))
        canvas = ImageEnhance.Brightness(canvas).enhance(0.45)
        fg_width = int(width * 1.3)
        fg = img.resize((fg_width, int(img.height * fg_width / img.width)), Image.LANCZOS)
        fg = fg.crop(((fg_width - width) // 2, 0, (fg_width - width) // 2 + width, fg.height))
        canvas.paste(fg, (0, int(height * 0.42 - fg.height / 2)))
    canvas = ImageEnhance.Contrast(canvas).enhance(1.12)
    return ImageEnhance.Color(canvas).enhance(1.08)


def _shade(img, top=460, bottom_start=1000, strength=225):
    """Dark gradients at the top and bottom so text stays readable on any photo."""
    W, H = img.size
    mask = Image.new("L", (1, H), 0)
    for y in range(H):
        if y < top:
            mask.putpixel((0, y), int(strength * (1 - y / top) ** 1.4))
        elif y > bottom_start:
            mask.putpixel((0, y), int(strength * ((y - bottom_start) / (H - bottom_start)) ** 1.2))
    mask = mask.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), (8, 8, 8)), img, mask)


def _logo(width):
    logo = Image.open(LOGO).convert("RGBA")
    return logo.resize((width, int(logo.height * width / logo.width)), Image.LANCZOS)


def _chyron(img, text, y, brand):
    """The headline: black capitals on a gold bar, like a TV graphic."""
    gold, black = _hex(brand["gold"]), _hex(brand["black"])
    draw = ImageDraw.Draw(img)
    font, lines = _fit(draw, text, img.width - 200, 2, 96, 60)
    line_h = font.size * 1.15
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        x = (img.width - w) / 2
        top = y + i * (line_h + 14)
        draw.rectangle((x - 30, top - 10, x + w + 30, top + line_h + 6), fill=gold)
        draw.text((x, top), line, font=font, fill=black)
    return y + len(lines) * (line_h + 14)


def _stamp(img, text, y, brand):
    gold, black, white = _hex(brand["gold"]), _hex(brand["black"]), _hex(brand["white"])
    font = _font(70)
    probe = ImageDraw.Draw(img)
    w = int(probe.textlength(text, font=font)) + 70
    h = 110
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    if text == "CONFIRMED":
        d.rounded_rectangle((0, 0, w - 1, h - 1), 14, fill=gold)
        d.text((35, 12), text, font=font, fill=black)
    else:
        d.rounded_rectangle((0, 0, w - 1, h - 1), 14, fill=(20, 20, 20, 200), outline=white, width=6)
        d.text((35, 12), text, font=font, fill=white)
    tile = tile.rotate(6, expand=True, resample=Image.BICUBIC)
    img.paste(tile, ((img.width - tile.width) // 2, int(y)), tile)
    return y + tile.height


def draw_frame(segment, index, total, photo, bg, brand):
    """Return the photo layer (which slowly zooms) and a transparent graphics layer (which stays still)."""
    W, H = bg.size
    gold, white = _hex(brand["gold"]), _hex(brand["white"])
    last = index == total - 1
    quote = segment.get("style") == "quote"

    base = photo_canvas(photo, W, H, bg)
    if last or quote:
        base = ImageEnhance.Brightness(base.filter(ImageFilter.GaussianBlur(14 if last else 6))).enhance(0.4)
    base = _shade(base)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rectangle((0, 0, W * (index + 1) / total, 12), fill=gold)

    if last:
        logo = _logo(360)
        layer.paste(logo, ((W - logo.width) // 2, 170), logo)
        font, lines = _fit(draw, segment["screen"], W - 160, 3, 140, 80)
        y = _centered(draw, lines, font, 170 + logo.height + 80, gold)
        _centered(draw, ["COMMENT BELOW"], _font(64), y + 50, white)
        return base, layer

    logo = _logo(120)
    layer.paste(logo, (48, 56), logo)

    if quote:
        font, lines = _fit(draw, f"\u201c{segment['screen']}\u201d", W - 140, 6, 120, 70)
        block = len(lines) * font.size * 1.12
        _centered(draw, lines, font, H * 0.45 - block / 2, white)
        return base, layer

    y = _chyron(layer, segment["screen"], 270, brand)
    if segment.get("stamp"):
        _stamp(layer, segment["stamp"], y + 20, brand)
    return base, layer


def _ass_time(seconds):
    cs = int(round(seconds * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def captions_ass(words, path, brand, max_words=3):
    """Big word-by-word captions: groups of up to 3 words, the spoken word lit in gold."""
    r, g, b = _hex(brand["gold"])
    gold = f"&H00{b:02X}{g:02X}{r:02X}"
    groups, current = [], []
    for word in words:
        current.append(word)
        if len(current) == max_words or word[2].rstrip().endswith((".", ",", "?", "!")):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    timed = []
    for group in groups:
        for i, (start, end, _) in enumerate(group):
            text = " ".join(
                (f"{{\\c{gold}}}{w.upper()}{{\\c&H00FFFFFF&}}" if j == i else w.upper())
                for j, (_, _, w) in enumerate(group)
            )
            timed.append([start, end + 0.15, text])
    for current, following in zip(timed, timed[1:]):
        current[1] = following[0]
    events = [
        f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Pop,,0,0,0,,"
        f"{{\\pos(540,1390)\\fscx106\\fscy106\\t(0,90,\\fscx100\\fscy100)}}{text}"
        for start, end, text in timed
    ]
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Pop,Anton,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,1,0,1,"
        "7,3,5,60,60,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events) + "\n"
    )


def segment_video(base_path, layer_path, audio_path, seconds, out_path, fps, index=0, ass_path=None):
    frames = int((seconds + PAD_SECONDS) * fps)
    # Alternate a slow push in with a slow pull out on the photo so cuts feel alive.
    z = "min(1+0.0009*on,1.12)" if index % 2 == 0 else "max(1.12-0.0009*on,1)"
    graph = (
        f"[0:v]scale=2160:-1,zoompan=z='{z}':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}[photo];"
        "[photo][1:v]overlay=0:0:format=auto"
    )
    if ass_path:
        graph += f",subtitles={ass_path}:fontsdir={FONT_DIR}"
    graph += "[v]"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(base_path), "-loop", "1", "-i", str(layer_path),
         "-i", str(audio_path), "-filter_complex", graph, "-map", "[v]", "-map", "2:a",
         "-af", f"apad=pad_dur={PAD_SECONDS}", "-t", f"{seconds + PAD_SECONDS:.2f}",
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
