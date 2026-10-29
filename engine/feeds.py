"""Read the wrestling RSS feeds and return stories we have not posted yet."""

import calendar
import html
import re
import time

import feedparser

from engine import state

MAX_AGE_HOURS = 36


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
    cutoff = time.time() - MAX_AGE_HOURS * 3600
    stories = []
    for url in feed_urls:
        parsed = feedparser.parse(url, agent="Mozilla/5.0 (HeadOfTheTableTalk Reels engine)")
        if parsed.bozo and not parsed.entries:
            print(f"Could not read feed {url}: {parsed.bozo_exception}")
            continue
        for entry in parsed.entries:
            link = entry.get("link", "")
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            stamp = calendar.timegm(published) if published else time.time()
            if not link or link in seen or stamp < cutoff:
                continue
            stories.append({
                "title": _clean(entry.get("title")),
                "summary": _clean(entry.get("summary"))[:600],
                "link": link,
                "source": _clean(parsed.feed.get("title", url)),
                "published": stamp,
                "image": _feed_image(entry),
            })
    stories.sort(key=lambda s: s["published"], reverse=True)
    return stories[:limit]


def mark_used(link):
    seen = state.load("seen_stories", [])
    seen.append(link)
    state.save("seen_stories", seen[-500:])
