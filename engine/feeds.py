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
            })
    stories.sort(key=lambda s: s["published"], reverse=True)
    return stories[:limit]


def mark_used(link):
    seen = state.load("seen_stories", [])
    seen.append(link)
    state.save("seen_stories", seen[-500:])
