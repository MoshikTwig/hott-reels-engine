"""Publish the next post of today's queue to the Facebook Page and Instagram.

python -m engine.publish --queue out    # publish the next unpublished post from out/<today>-news/
python -m engine.publish --check        # only show which Page and Instagram account the token reaches
"""

import argparse
import datetime as dt
import json
from pathlib import Path

from engine import meta, notify


def check():
    page, instagram = meta.accounts(meta.page_token())
    print(f"Facebook Page: {page['name']} ({page['id']})")
    print(f"Instagram: @{instagram['username']}" if instagram else "Instagram: none linked to this Page")
    notify.send_text(f"Meta connection works. Page: {page['name']}. "
                     + (f"Instagram: @{instagram['username']}." if instagram else "No Instagram account is linked."))


def publish_next(queue_dir):
    today = queue_dir / f"{dt.datetime.now(dt.UTC):%Y-%m-%d}-news"
    posts_file = today / "posts.json"
    if not posts_file.exists():
        print(f"No posts queued for today in {today}.")
        return True
    posts = json.loads(posts_file.read_text())
    waiting = [i for i, post in enumerate(posts) if not post.get("published")]
    if not waiting:
        print("All of today's posts are already published.")
        return True
    index = waiting[0]
    post = posts[index]
    image = today / Path(post["image"]).name

    token = meta.page_token()
    page, instagram = meta.accounts(token)
    errors = []
    try:
        photo_id, post["facebook_post"] = meta.post_facebook(token, page["id"], image, post["caption"])
    except meta.MetaError as error:
        errors.append(f"Facebook: {error}")
        photo_id = None
    if instagram and photo_id:
        try:
            post["instagram_post"] = meta.post_instagram(token, instagram["id"], meta.photo_url(token, photo_id),
                                                         post["caption"])
        except meta.MetaError as error:
            errors.append(f"Instagram: {error}")
    post["published"] = dt.datetime.now(dt.UTC).isoformat(timespec="minutes")
    post["errors"] = errors
    posts_file.write_text(json.dumps(posts, indent=2))

    label = f"Post {index + 1} of {len(posts)} ({post['image_headline']})"
    places = [name for name, key in (("Facebook", "facebook_post"), ("Instagram", "instagram_post")) if post.get(key)]
    lines = [f"{label} is live on {' and '.join(places)}." if places else f"{label} could not be posted."]
    if post.get("facebook_post"):
        lines.append(f"https://www.facebook.com/{post['facebook_post']}")
    lines += errors
    notify.send_text("\n".join(lines))
    print("\n".join(lines))
    return not errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=Path("out"), help="Folder that holds <date>-news/")
    parser.add_argument("--check", action="store_true", help="Only test the connection, post nothing")
    args = parser.parse_args()
    if args.check:
        check()
    elif not publish_next(args.queue):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
