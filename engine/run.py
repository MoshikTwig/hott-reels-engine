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

from engine import feeds, notify, render, state, voice, writer

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
        return script, lambda: feeds.mark_used(story["link"])
    topic = next_topic(fmt)
    script = writer.write_script(fmt, f"Topic: {topic}", config["ai"]["model"])
    script["topic"] = topic

    def mark():
        state.save("used_topics", state.load("used_topics", []) + [topic])

    return script, mark


def build(script, config, out_dir):
    brand, video = config["brand"], config["video"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "script.json").write_text(json.dumps(script, indent=2))
    (out_dir / "caption.txt").write_text(script["caption"] + "\n")

    segments = script["segments"]
    clips = voice.narrate(segments, out_dir, config["voice"]["name"], config["voice"]["rate"])
    bg = render.background(video["width"], video["height"], brand)
    parts = []
    for i, (segment, (audio, seconds)) in enumerate(zip(segments, clips)):
        frame = out_dir / f"frame_{i}.png"
        render.draw_frame(segment, i, len(segments), bg, brand).save(frame)
        part = out_dir / f"part_{i}.mp4"
        render.segment_video(frame, audio, seconds, part, video["fps"])
        parts.append(part)

    tracks = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    music = random.choice(tracks) if tracks else None
    reel = out_dir / "reel.mp4"
    render.assemble(parts, reel, music, video["music_volume"])
    for leftover in [*parts, *out_dir.glob("voice_*.mp3"), out_dir / "segments.txt"]:
        leftover.unlink(missing_ok=True)
    return reel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["auto", "table_report", "classic_rewind", "verdict"],
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
