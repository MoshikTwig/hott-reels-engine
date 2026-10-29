"""Send the finished Reel to Telegram for review before posting."""

import os

import requests


def send_for_review(video_path, caption, label):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram secrets not set, skipping review message.")
        return
    base = f"https://api.telegram.org/bot{token}"
    with open(video_path, "rb") as video:
        response = requests.post(
            f"{base}/sendVideo",
            data={"chat_id": chat_id, "caption": f"New Reel to review: {label}"[:1024],
                  "supports_streaming": "true"},
            files={"video": video},
            timeout=300,
        )
    response.raise_for_status()
    requests.post(f"{base}/sendMessage", data={"chat_id": chat_id, "text": caption[:4096]},
                  timeout=60).raise_for_status()


def send_posts(posts):
    """Send each finished post: the image, then its caption on its own so it copies cleanly."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram secrets not set, skipping review messages.")
        return
    base = f"https://api.telegram.org/bot{token}"

    def say(text):
        requests.post(f"{base}/sendMessage", timeout=60, data={
            "chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": "true",
        }).raise_for_status()

    say(f"Today's {len(posts)} posts are ready. For each one: save the image and copy the text under it. "
        "The same text works on Facebook and Instagram.")
    for i, post in enumerate(posts, 1):
        with open(post["image"], "rb") as image:
            requests.post(f"{base}/sendPhoto", timeout=120, files={"photo": image}, data={
                "chat_id": chat_id, "caption": f"Post {i} of {len(posts)}",
            }).raise_for_status()
        say(post["caption"])
