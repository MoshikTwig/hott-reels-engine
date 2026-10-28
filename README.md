# Head of the Table Talk Reels engine

Makes a branded, original 30 to 40 second vertical Reel every day, for free:

1. Reads the wrestling RSS feeds (or picks an evergreen topic from `topics.yaml`).
2. Writes the script and caption with the free Gemini API, following the brand rules.
3. Narrates it with free Microsoft neural voices (`edge-tts`).
4. Draws gold-on-black frames with the logo and renders the video with FFmpeg.
5. Sends the Reel and caption to Telegram for review. Nothing is posted automatically yet.

## Formats

| Format | When | What |
| --- | --- | --- |
| `table_report` | Mon, Wed, Fri, Sun | News breakdown from the feeds, with CONFIRMED / RUMOR stamps |
| `classic_rewind` | Tue, Sat | A legendary moment from `topics.yaml` |
| `verdict` | Thu | A debate from `topics.yaml`, ending with a vote |

Change the days in `config.yaml`, and add topics to the end of `topics.yaml`.

## Setup (one time)

Add these in **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Where to get it |
| --- | --- |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) → Create API key |
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` on Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Send your bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` |

Optional: drop royalty-free `.mp3` tracks (for example from the YouTube Audio Library) in `assets/music/`.

## Running it

- Automatically every day at 06:00 UTC.
- By hand: **Actions → Make a Reel → Run workflow**, and choose a format.
- The video and caption are attached to each run under **Artifacts**, and sent to Telegram if set up.

Locally:

```bash
pip install -r requirements.txt   # needs ffmpeg installed too
GEMINI_API_KEY=... python -m engine.run --format verdict
python -m engine.run --script examples/montreal-screwjob.json --no-notify   # no AI needed
```

## Content rules the engine enforces

- English only, no footage or images of real wrestlers, only our own graphics and narration.
- The first hashtag is always `#HeadOfTheTableTalk`.
- Unconfirmed news is labeled "Reportedly" or "Rumor".
