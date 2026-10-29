# Head of the Table Talk Reels engine

Makes a branded, original 30 to 40 second vertical Reel every day, for free:

1. Reads the wrestling RSS feeds (or picks an evergreen topic from `topics.yaml`).
2. Writes the script and caption with the free Gemini API, following the brand rules.
3. Narrates it with free Microsoft neural voices (`edge-tts`).
4. Finds real, freely licensed photos of the wrestlers on Wikimedia Commons (credited in the caption), adds slow zoom, a gold headline bar and word-by-word captions, and renders the video with FFmpeg.
5. Sends the Reel and caption to Telegram for review. Nothing is posted automatically yet.

## Daily news posts

Every day at 05:00 UTC, `.github/workflows/news-posts.yml` reads the feeds, picks the 3 stories fans will care about most, and makes a finished post for each:

- A branded 1080x1350 image: the article's own main photo, a big headline with the wrestler's name in gold, a BREAKING / REPORT / RUMOR tag, the logo, and the photo source. Stories without a usable photo are skipped.
- One caption for Facebook and Instagram: a capitals headline, the facts (rumors labeled), a question for the comments, the source's name and hashtags starting with `#HeadOfTheTableTalk`. No links to other websites, since Facebook shows posts that send people away to fewer people.

After the news, it adds one **Table Debate** post: a hot take or question about another of the day's stories, on that story's own photo, with the page's opinion and a question for fans.

The images and captions arrive in Telegram ready to post.

Run it by hand from **Actions → Daily news posts**. Tick **dry_run** to only make the posts, saved under the run's **Artifacts**.

## Reel formats

| Format | When | What |
| --- | --- | --- |
| `who_said_it` | Mon, Sat | Quiz: a famous quote, 3 seconds to guess in the comments, then the reveal |
| `table_report` | Tue, Fri | News breakdown from the feeds, with CONFIRMED / RUMOR stamps |
| `said_it_best` | Wed | One legendary promo line and the story behind it |
| `behind_character` | Thu | A true story about the real person behind a wrestler |
| `classic_rewind` | Sun | A legendary moment from `topics.yaml` |
| `verdict` | by hand | A debate from `topics.yaml`, ending with a vote |

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
