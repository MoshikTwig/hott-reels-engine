"""Write a Reel script and caption with the free Gemini API."""

import json
import os
import re
import time

import requests

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

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
- "image" is the name of the real wrestler (or person) the segment is about, exactly as their best-known
  ring name, for example "Ric Flair" or "Roman Reigns". It is used to find a real photo of them, so every
  segment except the last must have one. Spread different wrestlers across segments when the story allows.
- "style" is "quote" when the screen text is a quote someone said, otherwise null. Quote screen text keeps its
  normal capitalization, has no quotation marks, and is at most 15 words. Only use real, well-documented quotes,
  attributed to the right person. Never make up a quote.
- The caption opens with a bold-style headline in capitals, then 1 or 2 sentences ending in a question,
  then 4 or 5 hashtags. The first hashtag is exactly #HeadOfTheTableTalk.
Return only JSON in this shape:
{"title": "...", "segments": [{"voice": "...", "screen": "...", "image": "...", "stamp": null, "style": null}], "caption": "..."}"""

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
    "said_it_best": (
        "Format: SAID IT BEST, a 35-second Reel about one famous promo line. Hook, the line itself as a quote "
        "segment, when and where it was said, the story behind it, why fans still repeat it, closing question "
        "about who the best talker ever is."
    ),
    "behind_character": (
        "Format: BEHIND THE CHARACTER, a 40-second true human story about the real person behind a wrestler: "
        "family, a comeback, an illness beaten, a real friendship or rivalry. Warm and emotional, never gossip. "
        "Hook, who they are on TV, the real-life story in 2 or 3 beats, what it shows about them, closing question."
    ),
    "who_said_it": (
        "Format: WHO SAID IT?, a 30-second quiz. Exactly 6 segments in this order: "
        "Segments 1 to 3 must not give the answer away: their image is \"WWE crowd\". "
        "1) hook inviting viewers to guess (screen: WHO SAID IT?); "
        "2) the famous quote, read aloud (style: quote, screen: the quote); "
        "3) the voice says only \"Three. Two. One.\" (screen: COMMENT YOUR GUESS); "
        "4) the reveal of who said it (screen: their name); "
        "5) when and why they said it; "
        "6) closing question asking how many got it right."
    ),
}


BUSY_FALLBACK = "gemini-flash-lite-latest"


def _available_flash_model(key):
    """Google retires model names over time, so ask which Flash model this key can use now."""
    response = requests.get(MODELS_URL, headers={"x-goog-api-key": key},
                            params={"pageSize": 1000}, timeout=60)
    response.raise_for_status()
    names = [
        m["name"].removeprefix("models/") for m in response.json().get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    if "gemini-flash-latest" in names:
        return "gemini-flash-latest"
    skip = ("lite", "image", "tts", "live", "audio", "preview", "exp", "thinking")
    flash = [n for n in names if "flash" in n and not any(word in n for word in skip)]
    if not flash:
        raise SystemExit(f"No usable Gemini Flash model for this key. Available: {names}")
    return sorted(flash, reverse=True)[0]


def _generate(model, key, prompt, attempts=5):
    """Call the model, retrying the slow or busy answers the free tier sometimes gives."""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                API_URL.format(model=model),
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
                },
                timeout=300,
            )
        except requests.exceptions.RequestException as error:
            if attempt == attempts:
                raise SystemExit(f"Gemini API did not answer after {attempts} tries: {error}")
            print(f"Gemini API try {attempt} failed ({error}), retrying.")
        else:
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == attempts:
                return response
            print(f"Gemini API try {attempt} returned {response.status_code}, retrying.")
        time.sleep(20 * attempt)


def ask_json(prompt, model):
    """Send a prompt to Gemini and return its JSON answer."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set. Add it as a GitHub secret.")
    model = os.environ.get("GEMINI_MODEL", model)
    response = _generate(model, key, prompt)
    if response.status_code == 404:
        fallback = _available_flash_model(key)
        print(f"Model {model} is not available, using {fallback} instead.")
        response = _generate(fallback, key, prompt)
    if response.status_code in (429, 500, 502, 503, 504):
        # Busy spells on the free tier usually hit one model; the lighter one often still answers.
        print(f"{model} is busy, trying {BUSY_FALLBACK} instead.")
        response = _generate(BUSY_FALLBACK, key, prompt)
    if not response.ok:
        raise SystemExit(f"Gemini API error {response.status_code}: {response.text[:500]}")
    return json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])


def write_script(fmt, material, model):
    return enforce_rules(ask_json(f"{BRAND_RULES}\n\n{FORMAT_BRIEFS[fmt]}\n\n{material}", model))


def hashtag_first(text, hashtag="#HeadOfTheTableTalk"):
    """Make sure the brand hashtag is the first hashtag in the text."""
    text = text.strip()
    tags = re.findall(r"#\w+", text)
    if tags and tags[0] == hashtag:
        return text
    text = re.sub(re.escape(hashtag) + r"\b\s*", "", text).rstrip()
    first_tag = re.search(r"#\w+", text)
    if first_tag:
        return text[: first_tag.start()] + hashtag + " " + text[first_tag.start():]
    return text + "\n" + hashtag


def enforce_rules(script, hashtag="#HeadOfTheTableTalk"):
    """Fix the rules the brand never bends, whatever the model returned."""
    script["caption"] = hashtag_first(script.get("caption", ""), hashtag)
    for segment in script["segments"]:
        if segment.get("stamp") not in ("CONFIRMED", "RUMOR"):
            segment["stamp"] = None
        if segment.get("style") == "quote":
            segment["screen"] = segment.get("screen", "").strip().strip('"\u201c\u201d')
        else:
            segment["style"] = None
            segment["screen"] = segment.get("screen", "").upper()
    return script


def story_material(stories):
    lines = [f"[{i}] {s['title']} ({s['source']})\n{s['summary']}" for i, s in enumerate(stories)]
    return "Stories:\n" + "\n\n".join(lines)
