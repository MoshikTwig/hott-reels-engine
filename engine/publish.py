"""Publish the next post of today's queue to the Facebook Page and Instagram.

Two ways, whichever secret is set:
- MAKE_WEBHOOK_URL: hand the post to a Make.com scenario, which posts it with Make's own Meta connection.
  Make needs the image at a public URL: the queue branch of this (public) repo.
- META_PAGE_TOKEN: post directly through the Graph API with a Page token from a Meta developer app.

python -m engine.publish --queue out    # publish the next unpublished post from out/<today>-news/
python -m engine.publish --check        # only test the connection, post nothing
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import requests

from engine import meta, notify


def _image_url(date_dir, image_name):
    repo = os.environ.get("GITHUB_REPOSITORY", "MoshikTwig/hott-reels-engine")
    return f"https://raw.githubusercontent.com/{repo}/queue/{date_dir}/{image_name}"


def _send_to_make(post, image_url, test=False):
    response = requests.post(os.environ["MAKE_WEBHOOK_URL"], timeout=120, json={
        "image_url": image_url, "caption": post["caption"], "headline": post["image_headline"], "test": test,
    })
    if not response.ok:
        raise meta.MetaError(f"Make answered {response.status_code}: {response.text[:300]}")


def check():
    if os.environ.get("MAKE_WEBHOOK_URL"):
        # A sample with every field, so Make learns the data structure while its webhook is listening.
        # Send it before the scenario is switched on, or it gets posted.
        repo = os.environ.get("GITHUB_REPOSITORY", "MoshikTwig/hott-reels-engine")
        sample = {"caption": "Test from the Head of the Table Talk engine", "image_headline": "TEST"}
        _send_to_make(sample, f"https://raw.githubusercontent.com/{repo}/main/assets/logo.png", test=True)
        print("Sent a sample post to the Make webhook.")
        notify.send_text("Sent a sample to Make. It should now show image_url, caption, headline and test.")
        return
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

    errors = []
    if os.environ.get("MAKE_WEBHOOK_URL"):
        try:
            _send_to_make(post, _image_url(today.name, image.name))
            post["sent_to_make"] = True
        except (meta.MetaError, requests.RequestException) as error:
            errors.append(f"Make: {error}")
        return _finish(posts_file, posts, index, errors)

    token = meta.page_token()
    page, instagram = meta.accounts(token)
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
    return _finish(posts_file, posts, index, errors)


def _finish(posts_file, posts, index, errors):
    """Record the attempt so it is never posted twice, and tell Telegram how it went."""
    post = posts[index]
    post["published"] = dt.datetime.now(dt.UTC).isoformat(timespec="minutes")
    post["errors"] = errors
    posts_file.write_text(json.dumps(posts, indent=2))

    label = f"Post {index + 1} of {len(posts)} ({post['image_headline']})"
    places = [name for name, key in (("Facebook", "facebook_post"), ("Instagram", "instagram_post")) if post.get(key)]
    if post.get("sent_to_make"):
        lines = [f"{label} was sent to Make for Facebook and Instagram."]
    else:
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
