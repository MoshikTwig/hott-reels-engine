"""Post to the Facebook Page and its linked Instagram account through Meta's Graph API."""

import os
import time

import requests

GRAPH = "https://graph.facebook.com/v23.0"


class MetaError(Exception):
    pass


def _call(method, path, token, params=None, **kwargs):
    response = requests.request(method, f"{GRAPH}/{path}", params={"access_token": token, **(params or {})},
                                timeout=120, **kwargs)
    data = response.json() if response.content else {}
    if not response.ok or "error" in data:
        message = data.get("error", {}).get("message", response.text[:300])
        raise MetaError(f"{method} {path}: {message}")
    return data


def page_token():
    token = os.environ.get("META_PAGE_TOKEN")
    if not token:
        raise SystemExit("META_PAGE_TOKEN is not set. Add it as a GitHub secret (see the setup guide).")
    return token


def accounts(token):
    """The Page the token belongs to, and the Instagram account linked to it (or None)."""
    page = _call("GET", "me", token, {"fields": "id,name,instagram_business_account{id,username}"})
    return page, page.get("instagram_business_account")


def post_facebook(token, page_id, image_path, caption):
    """Publish the image with its caption on the Page. Returns the photo id and the post id."""
    with open(image_path, "rb") as image:
        data = _call("POST", f"{page_id}/photos", token, data={"caption": caption, "published": "true"},
                     files={"source": image})
    return data["id"], data.get("post_id", data["id"])


def photo_url(token, photo_id):
    """A public URL of the uploaded photo, which Instagram needs to fetch the image."""
    images = _call("GET", photo_id, token, {"fields": "images"})["images"]
    return max(images, key=lambda image: image["width"])["source"]


def post_instagram(token, ig_id, image_url, caption):
    container = _call("POST", f"{ig_id}/media", token, data={"image_url": image_url, "caption": caption})["id"]
    for _ in range(24):
        status = _call("GET", container, token, {"fields": "status_code"}).get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise MetaError("Instagram could not process the image.")
        time.sleep(5)
    return _call("POST", f"{ig_id}/media_publish", token, data={"creation_id": container})["id"]
