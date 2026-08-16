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
git clone https://github.com/shauryam/youtube-explain
cd youtube-explain
uv sync
cp .env.example .env      # then paste your OPENROUTER_API_KEY into .env
```

### Working with uv

The project is uv-managed: dependencies are declared in `pyproject.toml`, pinned in the
committed `uv.lock`, and installed into a local `.venv`. Python 3.13 is pinned by
`.python-version`, and uv downloads it if you do not have it.

- **Never activate the venv.** `uv run <command>` runs inside it and syncs it first, so
  `uv run ytexplain ...` is always correct even after pulling changes.
- **Add a dependency** with `uv add <package>` (`uv add --dev <package>` for tooling); it
  updates `pyproject.toml` and `uv.lock` together. Do not use `pip install` — it writes into
  the venv without recording anything, so the next `uv sync` silently discards it.
- **`uv sync`** rebuilds the environment to match the lockfile, and is also the fix if the
  project folder moves (see [Moving or copying the project](#moving-or-copying-the-project)).
- **One-off tools without installing them**: `uvx ruff check src tests`.
- `uv run python -m ytexplain "URL"` is equivalent to the `ytexplain` command if you prefer
  the module form.

To call it from anywhere instead of from the project directory:

```bash
uv tool install .        # installs a global `ytexplain`; `uv tool uninstall ytexplain` reverts
```

Two caveats once installed globally: it reads the nearest `.env` from the directory you run
in and upward, so either keep one there or export `OPENROUTER_API_KEY` in your shell profile,
and `out/` and `.cache/` are resolved relative to wherever you run it — set
`YTEXPLAIN_OUTPUT_DIR` and `YTEXPLAIN_CACHE_DIR` to absolute paths to keep one shared cache.

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

### How arguments are handled

```
ytexplain [options] URL [URL ...]
```

- **Always quote the URL.** In zsh the `?` and `&` in a YouTube link are shell
  metacharacters, and an unquoted link fails with `no matches found`.
- **Several sources in one run.** Any mix of videos and playlists:
  `ytexplain "URL1" "URL2" "PLAYLIST_URL"`. Each is processed in turn and the summary at
  the end lists every PDF written.
- **One failure does not stop the run.** An unreachable video, or one with captions
  disabled, is reported under `not generated:` at the end while everything else still
  produces output. This matters for long playlists.
- **`-o/--output` applies to a single result** — one video, or a playlist with `--combined`.
  It is ignored when a run has several sources, since one path cannot name several files.
  For multiple outputs use `-d/--out-dir`; playlists get a subfolder named after the
  playlist, with files numbered in playlist order.
- `uv run ytexplain --help` prints the full list.

Exit codes, for scripting:

| Code | Meaning |
| --- | --- |
| `0` | at least one PDF was written |
| `1` | nothing could be generated |
| `2` | configuration error, such as a missing API key |

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
| `--model SLUG` | any OpenRouter model (default `z-ai/glm-5.2`) |
| `--pick-model [SEARCH]` | choose the model interactively from OpenRouter's catalogue |
| `--lang en,hi` | preferred caption languages |
| `--include-transcript` | append the raw transcript to the PDF |
| `--markdown` | also write a `.md` beside each PDF |
| `--no-cache` | ignore cached transcripts and model responses |

### Choosing a model

The first time you run ytexplain without a model configured, it asks:

```
No model chosen yet. Falling back to the default, z-ai/glm-5.2.
Press Enter to keep it, or type a search to pick another:
Remember z-ai/glm-5.2 in .env? [y/n] (y):
```

Press Enter twice and you are done — the answer goes into `YTEXPLAIN_MODEL` in your `.env`
and the question does not come back. Type a search term instead (`claude`, `gemini`, `4.7`)
and you get the matching models to choose from. Decline the save and the choice applies to
that run only.

The question is skipped whenever a model is already configured, and whenever the output is
not a terminal, so scripts, cron jobs and CI never block on it — they use the default, or
whatever `--model` says.

Afterwards, any OpenRouter slug works without touching the code:

```bash
uv run ytexplain "URL" --model anthropic/claude-sonnet-5   # a slug you already know
uv run ytexplain "URL" --pick-model                        # search and choose, this run only
uv run ytexplain "URL" --pick-model glm                    # same, pre-filtered
```

`--pick-model` reads the live catalogue from OpenRouter, which needs no API key, and shows
each match with its context window and price per million tokens. Unlike the first-run
question it never writes to `.env`; to change your default later, edit `YTEXPLAIN_MODEL` or
delete the line to be asked again.

### Environment variables

Set these in `.env` (see `.env.example`). The nearest `.env` from the directory you run in,
searching upward, is the one used and the one the first-run question writes to. Command line
flags win over them.

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | required; from https://openrouter.ai/keys |
| `YTEXPLAIN_MODEL` | default model, same values as `--model`; leave it out to be asked once |
| `YTEXPLAIN_OUTPUT_DIR` | default output directory, same as `--out-dir` |
| `YTEXPLAIN_CACHE_DIR` | where the cache lives (default `.cache`) |

### Reading the run summary

Every run ends with a line like:

```
9 model calls (1 from cache), 24,265 in / 9,480 out tokens, $0.1433
```

`from cache` counts calls served from disk that cost nothing, and the dollar figure is what
OpenRouter actually billed for this run, not an estimate.

### Caching and cost control

Transcripts and model responses are cached under `.cache/` (`transcripts/` and
`completions/`), keyed by a hash of the inputs that determine the result. A few hundred
kilobytes per handful of videos, and it is gitignored.

This means **re-running the same video is free** — the second run reports
`0 model calls (10 from cache), $0.0000` and just re-renders. What that does and does not
cover:

| Change | Costs anything? |
| --- | --- |
| `--include-transcript`, `--markdown`, `-o`, `--out-dir`, `--combined` | free — rendering only |
| `--concurrency` | free — scheduling only |
| `--model`, `--fast`, editing prompts | new calls; the model and prompt text are part of the key |
| `--lang` | refetches the transcript, then rewrites |

So iterating on PDF appearance is free, while changing what the model is asked is not.

To force fresh generation, either pass `--no-cache` for one run or delete what you want to
rebuild:

```bash
rm -rf .cache                # everything
rm -rf .cache/completions    # keep transcripts, regenerate the writing
```

Clear it when a video's captions have been corrected, or when you have changed prompts and
want to compare output rather than reuse the old text.

### Moving or copying the project

uv stores absolute paths inside `.venv`, so the environment breaks if the folder moves.
Recreate it:

```bash
rm -rf .venv && uv sync
```

Nothing else is path-dependent: `.env`, `.cache/` and `out/` all move with the folder.

## Documentation

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the tool is built and how to change
  it: the two-pass design and why, module responsibilities, "how do I add X" recipes, and the
  constraints that are easy to trip over.
- **[AGENTS.md](AGENTS.md)** — conventions for anyone (or any agent) editing the repo.

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
   code blocks, tables and callouts. The cover and each chapter state an estimated
   reading time, so you can see up front what an hour of video became.

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

Cost is set by the model, so read these as examples rather than a price list. A 12-minute
tutorial on the default `z-ai/glm-5.2` came to 7 calls, 84 seconds and $0.0194 billed, for a
10-page PDF. `anthropic/claude-sonnet-5` measured about $0.15 on a 10-minute video, or $0.08
in `--fast` mode. Longer videos scale with the number of sections, not linearly with length,
since each section call only sees its own slice.

Switching models starts the cache from scratch, because the model slug is part of every
cache key. The first run on a new model pays full price even for videos you have already
processed.

## Development

```bash
uv run pytest                          # unit tests, no network or API key needed
uv run python scripts/render_sample.py # check PDF layout without spending anything
```

## License

MIT — see [LICENSE](LICENSE).

Bugs and questions are best raised as a GitHub issue; otherwise
mittalshaurya92@gmail.com.
