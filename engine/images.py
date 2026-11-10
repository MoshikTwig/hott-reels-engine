"""Find real, freely licensed photos of wrestlers on Wikimedia Commons.

Commons only hosts free content (Creative Commons or public domain), mostly
fan photos from live events. Each photo used is credited in the caption.
"""

import html
import re

import requests

from engine import render

FACE_TRIES = 5

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "HeadOfTheTableTalkReels/1.0 (https://github.com/MoshikTwig/hott-reels-engine)"}
SKIP_WORDS = ("logo", "signature", "poster", "map", "chart", "diagram", "flag", "belt", "ticket")


def _plain(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def search(query, limit=20):
    """Return candidate photos for a query, best first. Tries the exact name first."""
    for text in (f'"{query}"', query):
        results = _search(text, query, limit)
        if results:
            return results
    return []


def _search(text, query, limit):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{text} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600,
    }
    response = requests.get(API, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {}).values()
    name_words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", query)]
    results = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        title = page.get("title", "")
        meta = info.get("extmetadata", {})
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < 700 or info.get("height", 0) < 700:
            continue
        if any(word in title.lower() for word in SKIP_WORDS):
            continue
        score = sum(word in title.lower() for word in name_words) * 10
        score += 5 if info["height"] >= info["width"] else 0
        score -= page.get("index", 0) * 0.1
        results.append({
            "score": score,
            "url": info.get("thumburl") or info["url"],
            "title": title,
            "artist": _plain(meta.get("Artist", {}).get("value")) or "Unknown",
            "license": _plain(meta.get("LicenseShortName", {}).get("value")) or "see Commons",
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


class PhotoPicker:
    """Hands out a different photo for each segment, reusing earlier ones only when it must."""

    def __init__(self, workdir):
        self.workdir = workdir
        self.cache = {}
        self.used = set()
        self.credits = []
        self.last = None

    def photo_for(self, query, index):
        if not query:
            return self.last
        if query not in self.cache:
            try:
                self.cache[query] = search(query)
            except requests.RequestException as error:
                print(f"Photo search failed for {query!r}: {error}")
                self.cache[query] = []
        # Look at the best few candidates and take the first that clearly shows a face,
        # so a robe on a hanger or a wide crowd shot never stands in for the wrestler.
        path = self.workdir / f"photo_{index}.jpg"
        fallback, tried = None, 0
        for candidate in self.cache[query]:
            if candidate["url"] in self.used:
                continue
            if tried == FACE_TRIES:
                break
            try:
                response = requests.get(candidate["url"], headers=HEADERS, timeout=60)
                response.raise_for_status()
            except requests.RequestException as error:
                print(f"Could not download {candidate['title']}: {error}")
                continue
            tried += 1
            path.write_bytes(response.content)
            if render.cv2 is None or render.has_face(path):
                return self._take(candidate, path)
            fallback = fallback or (candidate, response.content)
        if fallback:
            path.write_bytes(fallback[1])
            return self._take(fallback[0], path)
        print(f"No new photo found for {query!r}, reusing the previous one.")
        return self.last

    def _take(self, candidate, path):
        self.used.add(candidate["url"])
        self.credits.append(f"{candidate['artist']} ({candidate['license']})")
        self.last = path
        return path

    def credit_line(self):
        if not self.credits:
            return ""
        unique = list(dict.fromkeys(self.credits))
        return "Photos via Wikimedia Commons: " + "; ".join(unique)
