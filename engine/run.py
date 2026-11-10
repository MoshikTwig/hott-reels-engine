"""Make one Reel from start to finish.

python -m engine.run                      # format from today's weekday in config.yaml
python -m engine.run --format verdict     # pick the format
python -m engine.run --script my.json     # skip the AI and render a script you wrote
"""

import argparse
import datetime as dt
import json
import random
import re
from pathlib import Path

import yaml

from engine import feeds, images, notify, render, state, voice, writer

ROOT = Path(__file__).resolve().parent.parent


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "reel"


def next_topic(fmt):
    topics = yaml.safe_load((ROOT / "topics.yaml").read_text())[fmt]
    used = state.load("used_topics", [])
    for topic in topics:
        if topic not in used:
            return topic
    raise SystemExit(f"All {fmt} topics are used. Add more to topics.yaml.")


def make_script(fmt, config):
    if fmt == "table_report":
        stories = feeds.fresh_stories(config["feeds"])
        if not stories:
            raise SystemExit("No fresh stories in the feeds right now.")
        script = writer.write_script(fmt, writer.story_material(stories), config["ai"]["model"])
        story = stories[int(script.get("story_index", 0))]
        script["source"] = story["link"]
        return script, lambda: feeds.mark_used(story["link"], story["title"])
    topic = next_topic(fmt)
    script = writer.write_script(fmt, f"Topic: {topic}", config["ai"]["model"])
    script["topic"] = topic

    def mark():
        state.save("used_topics", state.load("used_topics", []) + [topic])

    return script, mark


def build(script, config, out_dir):
    brand, video = config["brand"], config["video"]
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = script["segments"]
    narrator = {**config["voice"], **(script.get("narrator") or {})}  # a script may bring its own voice
    try:
        clips = voice.narrate(segments, out_dir, narrator["name"], narrator["rate"], narrator.get("pitch", "+0Hz"))
        print(f"Voice: {narrator['name']}")
    except Exception as error:  # noqa: BLE001  an unknown voice must not cost us the Reel
        print(f"Voice {narrator['name']} failed ({error}); using {config['voice']['name']} instead.")
        clips = voice.narrate(segments, out_dir, config["voice"]["name"], config["voice"]["rate"])
    bg = render.background(video["width"], video["height"], brand)
    photos = images.PhotoPicker(out_dir)
    parts = []
    previous_era = None
    for i, (segment, (audio, seconds, words)) in enumerate(zip(segments, clips)):
        if segment.get("images"):  # a THEN / NOW split screen
            photo = [photos.photo_for(query, f"{i}_{k}", reuse=True) for k, query in enumerate(segment["images"][:2])]
        else:
            photo = photos.photo_for(segment.get("image"), i)
        era = segment.get("era")
        base, layer = render.draw_frame(segment, i, len(segments), photo, bg, brand)
        frame, overlay = out_dir / f"frame_{i}.jpg", out_dir / f"layer_{i}.png"
        base.save(frame, quality=92)
        layer.save(overlay)
        ass = None
        if i < len(segments) - 1 and segment.get("style") != "quote":
            ass = out_dir / f"captions_{i}.ass"
            render.captions_ass(words, ass, brand)
        part = out_dir / f"part_{i}.mp4"
        render.segment_video(frame, overlay, audio, seconds, part, video["fps"], i, ass,
                             look=None if segment.get("images") else era,
                             static_burst=era == "modern" and previous_era == "classic")
        previous_era = era
        parts.append(part)

    credit = photos.credit_line()
    if credit:
        script["caption"] = f"{script['caption']}\n\n{credit}"
    (out_dir / "script.json").write_text(json.dumps(script, indent=2))
    (out_dir / "caption.txt").write_text(script["caption"] + "\n")

    tracks = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    music = random.choice(tracks) if tracks else None
    reel = out_dir / "reel.mp4"
    cuts, clock = [], 0.0
    for _, seconds, _ in clips:
        cuts.append(clock)
        clock += seconds + render.PAD_SECONDS
    render.assemble(parts, reel, music, video["music_volume"], cuts=cuts)
    for leftover in [*parts, *out_dir.glob("voice_*.mp3"), *out_dir.glob("captions_*.ass"),
                     *out_dir.glob("layer_*.png"), *out_dir.glob("photo_*.jpg"),
                     out_dir / "segments.txt"]:
        leftover.unlink(missing_ok=True)
    return reel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["auto", *writer.FORMAT_BRIEFS],
                        default="auto")
    parser.add_argument("--script", help="Render this script JSON instead of asking the AI")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    fmt = args.format
    if fmt == "auto":
        fmt = config["schedule"][dt.date.today().weekday()]

    mark_used = lambda: None
    if args.script:
        script = writer.enforce_rules(json.loads(Path(args.script).read_text()))
    else:
        script, mark_used = make_script(fmt, config)

    title = script.get("title", fmt)
    out_dir = ROOT / "out" / f"{dt.date.today():%Y-%m-%d}-{slugify(title)}"
    reel = build(script, config, out_dir)
    print(f"Reel ready: {reel}")

    if not args.no_notify:
        notify.send_for_review(reel, script["caption"], title)
    mark_used()


if __name__ == "__main__":
    main()
