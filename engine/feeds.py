"""Read the wrestling RSS feeds and return stories we have not posted yet."""

import calendar
import html
import re
import time

import feedparser
import requests

from engine import state

MAX_AGE_HOURS = 36
SAME_STORY = 0.6  # share of title words two headlines must share to count as the same story
STOPWORDS = {"a", "an", "the", "of", "on", "in", "at", "to", "for", "and", "or", "is", "are", "was", "with",
             "his", "her", "their", "as", "by", "from", "after", "new", "wwe", "aew", "news", "report"}
SYNONYMS = {"championship": "title", "champion": "title", "belt": "title", "wins": "win", "won": "win",
            "beats": "beat", "defeats": "beat", "defeated": "beat", "returns": "return", "returning": "return"}


def _words(title):
    words = re.findall(r"[a-z0-9']+", (title or "").lower())
    return {SYNONYMS.get(w, w) for w in words if w not in STOPWORDS and len(w) > 1}


def same_story(title_a, title_b):
    a, b = _words(title_a), _words(title_b)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= SAME_STORY


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _feed_image(entry):
    """The story's own photo, if the feed includes one."""
    for media in entry.get("media_content", []) + entry.get("media_thumbnail", []):
        if media.get("url") and media.get("medium", "image") == "image":
            return media["url"]
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    content = " ".join(c.get("value", "") for c in entry.get("content", [])) + entry.get("summary", "")
    match = re.search(r"<img[^>]+src=[\"']([^\"']+)", content)
    return html.unescape(match.group(1)) if match else ""


def fresh_stories(feed_urls, limit=15):
    seen = set(state.load("seen_stories", []))
    used_titles = state.load("used_titles", [])
    cutoff = time.time() - MAX_AGE_HOURS * 3600
    stories = []
    for url in feed_urls:
        # Fetch with a timeout first: feedparser on its own can wait forever on a slow site.
        try:
            page = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (HeadOfTheTableTalk Reels engine)"},
                                timeout=30)
            page.raise_for_status()
        except requests.RequestException as error:
            print(f"Could not read feed {url}: {error}")
            continue
        parsed = feedparser.parse(page.content)
        if parsed.bozo and not parsed.entries:
            print(f"Could not read feed {url}: {parsed.bozo_exception}")
            continue
        for entry in parsed.entries:
            link = entry.get("link", "")
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            stamp = calendar.timegm(published) if published else time.time()
            title = _clean(entry.get("title"))
            if not link or link in seen or stamp < cutoff:
                continue
            # Other sites run the same story under a new link, so also skip headlines we already used
            # and headlines that repeat a story already picked from another feed this run.
            if any(same_story(title, used) for used in used_titles) or \
                    any(same_story(title, s["title"]) for s in stories):
                continue
            stories.append({
                "title": title,
                "summary": _clean(entry.get("summary"))[:600],
                "link": link,
                "source": _clean(parsed.feed.get("title", url)),
                "published": stamp,
                "image": _feed_image(entry),
            })
    stories.sort(key=lambda s: s["published"], reverse=True)
    return stories[:limit]


def mark_used(link, title=""):
    seen = state.load("seen_stories", [])
    seen.append(link)
    state.save("seen_stories", seen[-500:])
    if title:
        titles = state.load("used_titles", [])
        titles.append(title)
        state.save("used_titles", titles[-200:])
