"""Work out what is due right now: today's news batch, the next post, or nothing.

Run often (Make's clock wakes it in each posting hour, GitHub's hourly timer is the backup). It is safe to run
any number of times: the batch is made once a day and each slot gets one post.

python -m engine.tick   # prints news, publish or nothing (and writes it to $GITHUB_OUTPUT)
"""

import datetime as dt
import os
from zoneinfo import ZoneInfo

import requests

SLOTS = [7, 11, 15, 19]  # Israel time; matches publish.slots in config.yaml
ZONE = ZoneInfo("Asia/Jerusalem")


def decide(now, posts):
    """posts: today's queued posts, or None when today's batch hasn't been made yet."""
    due = sum(1 for hour in SLOTS if now.astimezone(ZONE).hour >= hour)
    if posts is None:
        return "news" if due else "nothing"
    published = sum(1 for post in posts if post.get("published"))
    return "publish" if published < min(due, len(posts)) else "nothing"


def _todays_posts(now):
    repo = os.environ.get("GITHUB_REPOSITORY", "MoshikTwig/hott-reels-engine")
    url = f"https://raw.githubusercontent.com/{repo}/queue/{now:%Y-%m-%d}-news/posts.json"
    response = requests.get(url, params={"t": int(now.timestamp())}, timeout=30)  # skip the raw cache
    return response.json() if response.ok else None


def main():
    now = dt.datetime.now(dt.UTC)
    action = decide(now, _todays_posts(now))
    print(action)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"action={action}\n")


if __name__ == "__main__":
    main()
