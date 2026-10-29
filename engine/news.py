"""Make the day's finished wrestling news posts (branded image + captions) for Facebook and Instagram.

python -m engine.news              # make today's posts and send them to Telegram
python -m engine.news --dry-run    # only make them, in out/<date>-news/
"""

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import yaml

from engine import feeds, notify, postimage, writer

ROOT = Path(__file__).resolve().parent.parent
# Multi-topic articles: their main photo rarely matches any single story in them.
ROUNDUP = re.compile(r"round-?up|news and notes|notes:|recap|live coverage|rumor mill", re.I)

NEWS_PROMPT = """You run the Facebook page Head of the Table Talk, a wrestling news and discussion page.
From the stories below, pick the {count} that wrestling fans will care about most, best first, and write one
post for each. Never pick two stories about the same event. Skip roundups and digests that cover several
topics, because their photo won't match the story you write about.

Rules for every post:
- English only. Punchy, emotional, easy to read on a phone.
- Line 1 is the headline in CAPITALS between two matching emojis, for example: \U0001F525 CM PUNK JUST CHANGED EVERYTHING \U0001F525
- Then 2 to 4 short lines with the facts. Only use facts from the story given. Never invent names,
  dates, quotes or numbers. Summaries often stop mid-sentence with [...]: never guess how they continue.
- If the story is a report or rumor and not confirmed, say so clearly with "Reportedly" or "Rumor:".
- Then one line with a direct question that makes fans want to comment.
- Do not include a link; it is added after your text.
- Last line: 4 or 5 hashtags. The first is exactly #HeadOfTheTableTalk.

Each post also gets a big headline printed on its photo:
- "image_headline": 4 to 8 words, no emojis, the hook in plain words, true to the story
  (for example: CM PUNK REPORTEDLY SIGNS NEW WWE CONTRACT). Keep "Reportedly" for unconfirmed news.
- "highlight": the 1 to 3 words of image_headline to color gold, usually the wrestler's name.
- "tag": one of BREAKING, CONFIRMED, REPORT, RUMOR, RESULTS.

Return only JSON: {{"posts": [{{"story_index": 0, "post": "...", "image_headline": "...", "highlight": "...",
"tag": "..."}}]}}

{stories}"""


def write_posts(stories, model, count):
    """Ask for a few spare posts, so stories without a usable photo can be skipped."""
    answer = writer.ask_json(NEWS_PROMPT.format(count=count, stories=writer.story_material(stories)), model)
    posts, used = [], set()
    for item in answer.get("posts", []):
        index = int(item.get("story_index", -1))
        if not 0 <= index < len(stories) or index in used:
            continue
        used.add(index)
        story = stories[index]
        body, _, tags = item["post"].strip().rpartition("\n")
        if "#" not in tags:
            body, tags = item["post"].strip(), ""
        credit = postimage.source_name(story["link"])
        posts.append({
            "facebook": writer.hashtag_first(f"{body.strip()}\n\n\U0001F449 {story['link']}\n\n{tags.strip()}"),
            "instagram": writer.hashtag_first(f"{body.strip()}\n\nSource: {credit}\n\n{tags.strip()}"),
            "image_headline": item.get("image_headline") or story["title"],
            "highlight": item.get("highlight", ""),
            "tag": item.get("tag", "").upper(),
            "credit": credit,
            "story": story,
        })
    return posts


def add_images(posts, brand, out, count):
    """Render the branded image for each post until there are enough; skip stories without a photo."""
    ready = []
    for post in posts:
        photo = postimage.story_photo(post["story"])
        if photo is None:
            print(f"No usable photo for {post['story']['title']}, skipping it.")
            continue
        post["image"] = str(postimage.render_post(photo, post["image_headline"], post["highlight"], post["tag"],
                                                  post["credit"], brand, out / f"post-{len(ready) + 1}.jpg"))
        ready.append(post)
        if len(ready) == count:
            break
    return ready


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="Print the posts without sending or saving")
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    stories = [s for s in feeds.fresh_stories(config["feeds"], limit=30) if not ROUNDUP.search(s["title"])][:25]
    if not stories:
        raise SystemExit("No fresh stories in the feeds right now.")
    print(f"{len(stories)} fresh stories found.")
    out = ROOT / "out" / f"{dt.date.today():%Y-%m-%d}-news"
    out.mkdir(parents=True, exist_ok=True)
    posts = write_posts(stories, config["ai"]["model"], args.count + 3)
    posts = add_images(posts, config["brand"], out, args.count)
    if not posts:
        raise SystemExit("None of today's stories had a usable photo.")
    (out / "posts.json").write_text(json.dumps(posts, indent=2))
    for i, post in enumerate(posts, 1):
        print(f"\n===== Post {i} ({post['story']['source']}: {post['story']['title']}) =====")
        print(f"Image: {post['image']}\n--- Facebook ---\n{post['facebook']}\n--- Instagram ---\n{post['instagram']}")

    if args.dry_run:
        return
    notify.send_posts(posts)
    for post in posts:
        feeds.mark_used(post["story"]["link"])


if __name__ == "__main__":
    main()
