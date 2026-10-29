"""Turn a news story into a finished, branded 4:5 image post for Facebook and Instagram."""

import html
import io
import os
import re
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from engine.render import LOGO, _cover, _font, _hex

WIDTH, HEIGHT = 1080, 1350
MARGIN = 60
MIN_PHOTO_WIDTH = 600
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
SMALL_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def source_name(link):
    return urlparse(link).netloc.removeprefix("www.")


def _og_image(link):
    page = requests.get(link, headers=HEADERS, timeout=30)
    page.raise_for_status()
    for pattern in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        match = re.search(pattern, page.text, re.I)
        if match:
            return urljoin(link, html.unescape(match.group(1)))
    return ""


def _download(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(response.content))).convert("RGB")
    return img if img.width >= MIN_PHOTO_WIDTH else None


def story_photo(story):
    """The article's own main photo (what Facebook would show in a link preview), or None."""
    candidates = []
    try:
        candidates.append(_og_image(story["link"]))
    except requests.RequestException as error:
        print(f"Could not open {story['link']}: {error}")
    candidates.append(story.get("image", ""))
    for url in filter(None, candidates):
        try:
            img = _download(url)
        except (requests.RequestException, OSError) as error:
            print(f"Could not use photo {url}: {error}")
            continue
        if img:
            return img
    return None


def _shade(img):
    """Darken the top edge for the tag and the bottom half for the headline and footer."""
    mask = Image.new("L", (1, HEIGHT))
    for y in range(HEIGHT):
        top = max(0, 150 - y) * 1.0
        bottom = 0 if y < 560 else min(250, (y - 560) / (HEIGHT - 560) * 330)
        mask.putpixel((0, y), int(max(top, bottom)))
    mask = mask.resize((WIDTH, HEIGHT))
    return Image.composite(Image.new("RGB", (WIDTH, HEIGHT), (8, 8, 7)), img, mask)


def _headline_lines(draw, words, max_width, max_lines=3):
    """The biggest font that fits the headline in max_lines, and its lines as word lists."""
    for size in range(134, 75, -8):
        font = _font(size)
        lines = [[]]
        for word in words:
            if lines[-1] and draw.textlength(" ".join(lines[-1] + [word]), font=font) > max_width:
                lines.append([])
            lines[-1].append(word)
        if len(lines) <= max_lines and all(draw.textlength(" ".join(l), font=font) <= max_width for l in lines):
            break
    return font, lines


def _photo_layer(photo):
    """Tall photos fill the frame. Wide article photos (usually 16:9) would lose half their width that way,
    so they sit full width at the top over a blurred copy, and fade into it."""
    photo = photo.crop((3, 3, photo.width - 3, photo.height - 3))  # some sites add a thin border
    if photo.width / photo.height < 1.2:
        return _cover(photo, WIDTH, HEIGHT, focus_y=0.3)
    backdrop = _cover(photo, WIDTH, HEIGHT).filter(ImageFilter.GaussianBlur(40))
    backdrop = Image.blend(backdrop, Image.new("RGB", (WIDTH, HEIGHT), (8, 8, 7)), 0.55)
    height = 760
    scaled = photo.resize((max(WIDTH, round(photo.width * height / photo.height)), height), Image.LANCZOS)
    if scaled.width == WIDTH:
        scaled = photo.resize((WIDTH, round(photo.height * WIDTH / photo.width)), Image.LANCZOS)
    left = (scaled.width - WIDTH) // 2
    scaled = scaled.crop((left, 0, left + WIDTH, scaled.height))
    fade = Image.new("L", scaled.size, 255)
    for y in range(scaled.height - 220, scaled.height):
        ImageDraw.Draw(fade).line((0, y, WIDTH, y), fill=int(255 * (scaled.height - y) / 220))
    backdrop.paste(scaled, (0, 0), fade)
    return backdrop


def render_post(photo, headline, highlight, tag, credit, brand, out_path):
    gold, white = _hex(brand["gold"]), _hex(brand["white"])
    img = _shade(_photo_layer(photo))
    draw = ImageDraw.Draw(img)

    if tag:
        font = _font(46)
        width = draw.textlength(tag, font=font)
        draw.rectangle((MARGIN - 4, 52, MARGIN + width + 32, 52 + 74), fill=gold)
        draw.text((MARGIN + 14, 54), tag, font=font, fill=_hex(brand["black"]))

    gold_words = {w.strip(".,!?:'\"").upper() for w in highlight.split()}
    words = headline.upper().split()
    font, lines = _headline_lines(draw, words, WIDTH - 2 * MARGIN)
    line_height = font.size * 1.08
    y = HEIGHT - 200 - len(lines) * line_height
    draw.rectangle((MARGIN, y - 34, MARGIN + 150, y - 24), fill=gold)
    space = draw.textlength(" ", font=font)
    for line in lines:
        x = MARGIN
        for word in line:
            color = gold if word.strip(".,!?:'\"") in gold_words else white
            draw.text((x, y), word, font=font, fill=color)
            x += draw.textlength(word, font=font) + space
        y += line_height

    # The logo lives in the footer, so it never covers a face in the photo.
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.resize((round(logo.width * 150 / logo.height), 150), Image.LANCZOS)
    img.paste(logo, (MARGIN - 6, HEIGHT - 176), logo)
    left = MARGIN + logo.width + 18
    draw.line((left, HEIGHT - 110, WIDTH - MARGIN, HEIGHT - 110), fill=gold, width=3)
    draw.text((left, HEIGHT - 92), brand["name"].upper(), font=_font(40), fill=gold)
    small = ImageFont.truetype(SMALL_FONT, 22) if os.path.exists(SMALL_FONT) else _font(24)
    text = f"Photo: {credit}"
    draw.text((WIDTH - MARGIN - draw.textlength(text, font=small), HEIGHT - 70), text, font=small,
              fill=(190, 184, 172))
    img.save(out_path, quality=92)
    return out_path
