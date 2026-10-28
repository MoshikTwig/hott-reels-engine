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
