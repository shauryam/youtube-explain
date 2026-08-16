"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from .cache import Cache
from .config import DEFAULT_MODEL, ConfigError, Settings
from .llm import LLMError, Model, list_models
from .models import Document
from .pipeline import (
    Options,
    build_document,
    collect,
    make_client,
    output_path,
    slugify,
)
from .render import build_pdf
from .render.text import to_markdown

console = Console()

MODEL_LIST_LIMIT = 25


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ytexplain",
        description="Turn YouTube videos and playlists into comprehensive PDF explainers.",
    )
    parser.add_argument("urls", nargs="+", metavar="URL", help="video or playlist URLs (or bare video IDs)")
    parser.add_argument("-o", "--output", type=Path, help="output PDF path (single video only)")
    parser.add_argument("-d", "--out-dir", type=Path, help="directory for generated PDFs (default: out/)")
    parser.add_argument("--playlist", action="store_true", help="expand a watch URL that also carries a list= id")
    parser.add_argument("--max-videos", type=int, metavar="N", help="stop after N videos of a playlist")
    parser.add_argument("--combined", action="store_true", help="one PDF for the whole playlist instead of one per video")
    parser.add_argument("--model", help=f"OpenRouter model (default: {DEFAULT_MODEL})")
    parser.add_argument(
        "--pick-model",
        nargs="?",
        const="",
        metavar="SEARCH",
        help="choose the model interactively from OpenRouter's catalogue",
    )
    parser.add_argument("--fast", action="store_true", help="cheaper two-call mode; less depth per section")
    parser.add_argument("--concurrency", type=int, default=4, metavar="N", help="sections written in parallel (default: 4)")
    parser.add_argument("--lang", default="en", help="preferred caption languages, comma separated (default: en)")
    parser.add_argument("--include-transcript", action="store_true", help="append the raw transcript to the PDF")
    parser.add_argument("--markdown", action="store_true", help="also write a .md next to each PDF")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached transcripts and model responses")
    return parser.parse_args(argv)


def matching_models(models: list[Model], query: str) -> list[Model]:
    """Models whose slug or name contains `query`, case-insensitively."""
    needle = query.strip().lower()
    found = [model for model in models if needle in model.id.lower() or needle in model.name.lower()]
    return sorted(found, key=lambda model: model.id)


def _show_models(models: list[Model], current: str) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("#", justify="right")
    table.add_column("Model")
    table.add_column("Context", justify="right")
    table.add_column("$/M in", justify="right")
    table.add_column("$/M out", justify="right")
    for position, model in enumerate(models[:MODEL_LIST_LIMIT], start=1):
        table.add_row(
            str(position),
            f"{model.id} [dim](current)[/]" if model.id == current else model.id,
            f"{model.context:,}",
            f"{model.prompt_usd:.2f}",
            f"{model.completion_usd:.2f}",
        )
    console.print(table)
    if len(models) > MODEL_LIST_LIMIT:
        console.print(
            f"[dim]{len(models) - MODEL_LIST_LIMIT} more match; narrow the search to reach them.[/]"
        )


def choose_model(seed: str, current: str) -> str:
    """Ask which OpenRouter model to use, and return the chosen slug."""
    if not sys.stdin.isatty():
        raise ConfigError("--pick-model needs an interactive terminal; pass --model SLUG instead")

    models = list_models()
    console.print(f"[dim]{len(models)} models on OpenRouter. Currently using {current}.[/]")
    # Listing 400-odd models alphabetically helps nobody, so ask before showing any.
    query = seed if seed.strip() else Prompt.ask("Search models (blank for all)", default="")
    while True:
        matches = matching_models(models, query)
        if not matches:
            console.print(f"[yellow]Nothing matches[/] {query!r}")
        else:
            _show_models(matches, current)
            choice = IntPrompt.ask("Model number, or 0 to search again", default=1)
            if 1 <= choice <= min(len(matches), MODEL_LIST_LIMIT):
                return matches[choice - 1].id
            if choice != 0:
                console.print("[yellow]That number is not on the list.[/]")
        query = Prompt.ask("Search models (blank for all)", default="")


def first_run_model(settings: Settings) -> None:
    """Nobody has chosen a model yet, so confirm the default or pick another.

    Only reached on a terminal. Saving is offered because otherwise the same question
    would greet every run, and `.env` is where the answer belongs.
    """
    console.print(
        f"[bold]No model chosen yet.[/] Falling back to the default, {settings.model}."
    )
    seed = Prompt.ask("Press Enter to keep it, or type a search to pick another", default="")
    if seed.strip():
        settings.model = choose_model(seed, settings.model)
    if Confirm.ask(f"Remember {settings.model} in .env?", default=True):
        path = settings.remember_model()
        console.print(f"[dim]Wrote YTEXPLAIN_MODEL={settings.model} to {path}[/]")
    else:
        console.print(f"[dim]Using {settings.model} for this run only.[/]")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = Settings.load(
            model=args.model, output_dir=args.out_dir, use_cache=not args.no_cache
        )
        settings.require_api_key()
        if args.pick_model is not None:
            settings.model = choose_model(args.pick_model, settings.model)
            console.print(
                f"[dim]Using {settings.model} for this run."
                f" Put YTEXPLAIN_MODEL={settings.model} in .env to make it the default.[/]"
            )
        elif not settings.model_configured and sys.stdin.isatty():
            first_run_model(settings)
    except (ConfigError, LLMError) as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        return 2

    options = Options(
        fast=args.fast,
        concurrency=max(1, args.concurrency),
        languages=tuple(part.strip() for part in args.lang.split(",") if part.strip()) or ("en",),
        force_playlist=args.playlist,
        max_videos=args.max_videos,
    )
    cache = Cache(settings.cache_dir, enabled=settings.use_cache)
    # An exact path can only name one file, so it is ignored once a run has
    # several sources; otherwise each URL would overwrite the previous one.
    sole_output = args.output if len(args.urls) == 1 else None
    results: list[tuple[Path, Document]] = []
    failures: list[tuple[str, str]] = []

    with make_client(settings, cache) as client:
        for url in args.urls:
            try:
                refs, playlist_title = collect(url, options)
            except Exception as exc:  # noqa: BLE001 - report and move to the next URL
                failures.append((url, str(exc)))
                console.print(f"[bold red]Skipping[/] {url}: {exc}")
                continue

            if playlist_title:
                console.print(
                    f"[bold]Playlist:[/] {playlist_title} [dim]({len(refs)} videos)[/]"
                )
            folder = _folder_for(settings, playlist_title, args)
            documents: list[Document] = []

            for position, ref in enumerate(refs, start=1):
                label = ref.title or ref.video_id
                prefix = f"[{position}/{len(refs)}] " if len(refs) > 1 else ""
                console.print(f"{prefix}[bold cyan]{label}[/]")
                try:
                    document = _run_one(ref, client, cache, options, playlist_title)
                except Exception as exc:  # noqa: BLE001 - one bad video must not stop a playlist
                    failures.append((ref.url, str(exc)))
                    console.print(f"  [bold red]failed:[/] {exc}")
                    continue
                documents.append(document)
                console.print(
                    f"  [dim]{document.explainer.title}"
                    f" - {len(document.explainer.sections)} sections[/]"
                )

                if not (args.combined and len(refs) > 1):
                    destination = output_path(
                        document,
                        settings,
                        explicit=sole_output if len(refs) == 1 else None,
                        folder=folder,
                        index=position if len(refs) > 1 else None,
                    )
                    results.append((_write(document, destination, args), document))

            if args.combined and len(refs) > 1 and documents:
                destination = sole_output or (
                    settings.output_dir / f"{slugify(playlist_title or 'playlist')}.pdf"
                )
                path = build_pdf(
                    documents,
                    destination,
                    include_transcript=args.include_transcript,
                    collection_title=playlist_title,
                )
                console.print(f"  [green]wrote[/] {path}")
                results.append((path, documents[0]))

    _summarise(results, failures, client_usage=client.usage)
    return 0 if results else 1


def _run_one(ref, client, cache, options, playlist_title) -> Document:
    with console.status("[cyan]starting[/]", spinner="dots") as status:
        return build_document(
            ref,
            client=client,
            cache=cache,
            options=options,
            playlist_title=playlist_title,
            on_progress=lambda message: status.update(f"[cyan]{message}[/]"),
        )


def _folder_for(settings: Settings, playlist_title: str | None, args) -> Path:
    # Settings already folded in --out-dir; playlists get a subfolder of their own.
    if playlist_title and not args.combined:
        return settings.output_dir / slugify(playlist_title)
    return settings.output_dir


def _write(document: Document, destination: Path, args) -> Path:
    path = build_pdf([document], destination, include_transcript=args.include_transcript)
    console.print(f"  [green]wrote[/] {path}")
    if args.markdown:
        markdown_path = path.with_suffix(".md")
        markdown_path.write_text(to_markdown(document), encoding="utf-8")
        console.print(f"  [green]wrote[/] {markdown_path}")
    return path


def _summarise(results, failures, client_usage) -> None:
    if results:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("PDF")
        table.add_column("Sections", justify="right")
        for path, document in results:
            table.add_row(str(path), str(len(document.explainer.sections)))
        console.print()
        console.print(table)

    usage = client_usage
    if usage.calls or usage.cached_calls:
        console.print(
            f"[dim]{usage.calls} model calls ({usage.cached_calls} from cache), "
            f"{usage.prompt_tokens:,} in / {usage.completion_tokens:,} out tokens, "
            f"${usage.cost_usd:.4f}[/]"
        )
    for url, error in failures:
        console.print(f"[yellow]not generated:[/] {url} [dim]{error}[/]")


if __name__ == "__main__":
    sys.exit(main())
