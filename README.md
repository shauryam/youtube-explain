# ytexplain

Turn a YouTube video — or a whole playlist — into a PDF that explains the material
properly, so an hour of tutorial becomes ten minutes of reading.

It is not a summariser. It reads the transcript, works out what the video is teaching,
plans a document, and then writes each section in full: mechanisms explained, terms
defined, commands and code preserved, pitfalls called out. Hindi (and other
non-English) videos are written out in English.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and an [OpenRouter](https://openrouter.ai/keys) key.

```bash
uv sync
cp .env.example .env      # then paste your OPENROUTER_API_KEY into .env
```

## Usage

```bash
# one video -> out/<title>.pdf
uv run ytexplain "https://www.youtube.com/watch?v=VIDEO_ID"

# a playlist -> one PDF per video, in out/<playlist>/
uv run ytexplain "https://www.youtube.com/playlist?list=PLAYLIST_ID"

# a playlist as a single book-style PDF
uv run ytexplain "https://www.youtube.com/playlist?list=PLAYLIST_ID" --combined

# a watch URL that also carries a list= id, treated as the whole playlist
uv run ytexplain "https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID" --playlist
```

Bare video IDs, `youtu.be`, `/shorts/`, `/live/` and `/embed/` links all work.

### Options

| Flag | Effect |
| --- | --- |
| `-o, --output PATH` | exact output path (single video, or a combined playlist) |
| `-d, --out-dir DIR` | where PDFs go (default `out/`) |
| `--playlist` | expand a watch URL that also carries a `list=` id |
| `--max-videos N` | only the first N videos of a playlist |
| `--combined` | one PDF for the playlist instead of one per video |
| `--fast` | two model calls instead of one-per-section: cheaper, less depth |
| `--concurrency N` | sections written in parallel (default 4) |
| `--model SLUG` | any OpenRouter model (default `anthropic/claude-sonnet-5`) |
| `--lang en,hi` | preferred caption languages |
| `--include-transcript` | append the raw transcript to the PDF |
| `--markdown` | also write a `.md` beside each PDF |
| `--no-cache` | ignore cached transcripts and model responses |

## How it works

1. **Resolve** the URL. Playlists are enumerated with `yt-dlp`; titles and channel come
   from YouTube's oEmbed endpoint, which is fast and needs no API key.
2. **Fetch the transcript** with `youtube-transcript-api`, preferring human captions over
   auto-generated ones and English over other languages. If YouTube blocks that request,
   it falls back to pulling caption URLs through `yt-dlp`.
3. **Plan the document.** The whole transcript goes to the model, which returns a
   structured outline: title, abstract, prerequisites, a section list with the time range
   each one covers, glossary terms and takeaways.
4. **Write each section** in a separate call that receives only that section's slice of
   the transcript plus the outline for context, running several in parallel.

   This split is the point. A single call has to fit an entire document into one response,
   so it summarises. Per-section calls each have room to actually explain, and the outline
   keeps them from overlapping or repeating each other.
5. **Render** to PDF: cover page, clickable table of contents, PDF bookmarks, styled
   code blocks, tables and callouts.

Transcripts and model responses are cached in `.cache/`, keyed by content, so re-running
a video — to change PDF options, for instance — costs nothing.

### Language handling

The model is told to produce English regardless of the transcript language, and to
translate meaning rather than words. This matters for Hindi tech tutorials in two ways:
Devanagari captions get translated properly, and the machine-translated `en-IN` caption
tracks many Hindi channels carry ("In start you will feel that, it is so easy") get
rewritten into idiomatic English instead of being copied through.

With `--include-transcript`, non-Latin transcripts render using a system Unicode font.
ReportLab does not do complex text shaping, so Devanagari conjuncts in that optional
appendix are legible but not typographically perfect. The explainer itself is English and
unaffected.

## Cost and time

Roughly, with `claude-sonnet-5` on a 10-minute video: about 70 seconds and $0.15 for the
full per-section mode, or $0.08 in `--fast` mode. Longer videos scale with the number of
sections, not linearly with length, since each section call only sees its own slice.

## Development

```bash
uv run pytest                          # unit tests, no network or API key needed
uv run python scripts/render_sample.py # check PDF layout without spending anything
```
