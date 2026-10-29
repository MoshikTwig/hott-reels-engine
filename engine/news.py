"""Write the day's wrestling news posts for Facebook from the RSS feeds.

python -m engine.news              # write today's posts and send them to Telegram
python -m engine.news --dry-run    # only print them
"""

import argparse
import datetime as dt
import json
from pathlib import Path

import yaml

from engine import feeds, notify, writer

ROOT = Path(__file__).resolve().parent.parent

NEWS_PROMPT = """You run the Facebook page Head of the Table Talk, a wrestling news and discussion page.
From the stories below, pick the {count} that wrestling fans will care about most, and write one Facebook
post for each. Never pick two stories about the same event.

Rules for every post:
- English only. Punchy, emotional, easy to read on a phone.
- Line 1 is the headline in CAPITALS between two matching emojis, for example: \U0001F525 CM PUNK JUST CHANGED EVERYTHING \U0001F525
- Then 2 to 4 short lines with the facts. Only use facts from the story given. Never invent names,
  dates, quotes or numbers.
- If the story is a report or rumor and not confirmed, say so clearly with "Reportedly" or "Rumor:".
- Then one line with a direct question that makes fans want to comment.
- Do not include a link; it is added after your text.
- Last line: 4 or 5 hashtags. The first is exactly #HeadOfTheTableTalk.

Return only JSON: {{"posts": [{{"story_index": 0, "post": "..."}}]}}

{stories}"""


def write_posts(stories, model, count):
    answer = writer.ask_json(NEWS_PROMPT.format(count=count, stories=writer.story_material(stories)), model)
    posts, used = [], set()
    for item in answer.get("posts", [])[:count]:
        index = int(item.get("story_index", -1))
        if not 0 <= index < len(stories) or index in used:
            continue
        used.add(index)
        story = stories[index]
        body, _, tags = item["post"].strip().rpartition("\n")
        if "#" not in tags:
            body, tags = item["post"].strip(), ""
        text = writer.hashtag_first(f"{body.strip()}\n\n\U0001F449 {story['link']}\n\n{tags.strip()}")
        posts.append({"text": text, "link": story["link"], "title": story["title"], "source": story["source"]})
    return posts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="Print the posts without sending or saving")
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    stories = feeds.fresh_stories(config["feeds"], limit=25)
    if not stories:
        raise SystemExit("No fresh stories in the feeds right now.")
    print(f"{len(stories)} fresh stories found.")
    posts = write_posts(stories, config["ai"]["model"], args.count)

    out = ROOT / "out" / f"{dt.date.today():%Y-%m-%d}-news"
    out.mkdir(parents=True, exist_ok=True)
    (out / "posts.json").write_text(json.dumps(posts, indent=2))
    for i, post in enumerate(posts, 1):
        print(f"\n===== Post {i} (from {post['source']}: {post['title']}) =====\n{post['text']}")

    if args.dry_run:
        return
    notify.send_posts(posts)
    for post in posts:
        feeds.mark_used(post["link"])


if __name__ == "__main__":
    main()
