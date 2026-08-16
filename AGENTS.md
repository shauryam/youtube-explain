# Working in this repository

If a `CodingAgents.md` sits in the parent directory, follow its shared rules too. This file
stands on its own without it.

ytexplain turns YouTube videos and playlists into PDF explainers that replace watching.
Read `docs/ARCHITECTURE.md` before changing anything — it explains the two-pass generation
design, what each module owns, and several non-obvious constraints that are easy to
reintroduce as bugs.

## Conventions

- **uv only.** `uv run <cmd>`, `uv add <package>`. Never `pip install` or activate the venv
  by hand; `uv.lock` is committed and must stay in sync with `pyproject.toml`.
- **Prompts live in `prompts.py`.** Do not inline prompt text in `explain.py`.
- **Provider code lives in `llm.py`.** Everything upstream talks to `complete` and
  `complete_json` only.
- **Rendering is split**: `render/markdown.py` parses, `render/pdf.py` styles. Keep visual
  choices out of the parser.
- **Anything both renderers need lives in `models.py`.** The reading-time estimate is there
  for that reason; deriving it separately in `render/pdf.py` and `render/text.py` would let
  the two disagree.
- Comments explain constraints and reasoning, not what the next line does.

## Before finishing a change

```bash
uv run pytest                          # no network or API key needed
uv run python scripts/render_sample.py # only if you touched rendering
```

`.env` holds the OpenRouter key and is gitignored — never commit it or echo its contents.
Real end-to-end runs are cached in `.cache/`, so rerunning a video you have already
processed is free.
