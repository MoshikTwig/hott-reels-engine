"""Write a Reel script and caption with the free Gemini API."""

import json
import os
import re

import requests

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

BRAND_RULES = """You write for Head of the Table Talk, a wrestling media brand on Facebook and Instagram.
Rules:
- English only. Punchy, emotional, easy to read, for wrestling fans.
- Never invent facts. Only use facts from the story given or well-documented wrestling history.
- Anything unconfirmed is labeled "Reportedly" or "Rumor".
- The script is spoken by a narrator over our own motion graphics. Total 70 to 100 words (about 30 to 40 seconds).
- Segment 1 is the hook: one line that stops the scroll. The last segment is a direct question to the viewer.
- 4 to 6 segments. Each "voice" line is one or two short sentences.
- Each "screen" text is 2 to 5 words in capitals, the punchline of that segment.
- "stamp" is "CONFIRMED", "RUMOR" or null. Use stamps only for news.
- The caption opens with a bold-style headline in capitals, then 1 or 2 sentences ending in a question,
  then 4 or 5 hashtags. The first hashtag is exactly #HeadOfTheTableTalk.
Return only JSON in this shape:
{"title": "...", "segments": [{"voice": "...", "screen": "...", "stamp": null}], "caption": "..."}"""

FORMAT_BRIEFS = {
    "table_report": (
        "Format: THE TABLE REPORT, a 30-second news breakdown. Hook, what happened, the confirmed detail, "
        "anything reported but unconfirmed, why it matters, closing question.\n"
        "Pick the ONE story below that wrestling fans will care about most, and add a field "
        '"story_index" with its number.'
    ),
    "classic_rewind": (
        "Format: CLASSIC REWIND, a 40-second story of a legendary wrestling moment. Hook, the date and place, "
        "the build-up, the moment itself, why it still matters, closing question."
    ),
    "verdict": (
        "Format: THE VERDICT, a 30-second debate. Hook, the case for one side with real facts, the case for "
        "the other side, closing question asking fans to vote in the comments."
    ),
}


def write_script(fmt, material, model):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set. Add it as a GitHub secret.")
    prompt = f"{BRAND_RULES}\n\n{FORMAT_BRIEFS[fmt]}\n\n{material}"
    response = requests.post(
        API_URL.format(model=os.environ.get("GEMINI_MODEL", model)),
        headers={"x-goog-api-key": key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
        },
        timeout=120,
    )
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return enforce_rules(json.loads(text))


def enforce_rules(script, hashtag="#HeadOfTheTableTalk"):
    """Fix the rules the brand never bends, whatever the model returned."""
    caption = script.get("caption", "").strip()
    tags = re.findall(r"#\w+", caption)
    if not tags or tags[0] != hashtag:
        caption = re.sub(re.escape(hashtag) + r"\b\s*", "", caption).rstrip()
        first_tag = re.search(r"#\w+", caption)
        if first_tag:
            caption = caption[: first_tag.start()] + hashtag + " " + caption[first_tag.start():]
        else:
            caption += "\n" + hashtag
    script["caption"] = caption
    for segment in script["segments"]:
        segment["screen"] = segment.get("screen", "").upper()
        if segment.get("stamp") not in ("CONFIRMED", "RUMOR"):
            segment["stamp"] = None
    return script


def story_material(stories):
    lines = [f"[{i}] {s['title']} ({s['source']})\n{s['summary']}" for i, s in enumerate(stories)]
    return "Stories:\n" + "\n\n".join(lines)
