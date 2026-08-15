"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .cache import Cache
from .config import DEFAULT_MODEL, ConfigError, Settings
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
    parser.add_argument("--fast", action="store_true", help="cheaper two-call mode; less depth per section")
    parser.add_argument("--concurrency", type=int, default=4, metavar="N", help="sections written in parallel (default: 4)")
    parser.add_argument("--lang", default="en", help="preferred caption languages, comma separated (default: en)")
    parser.add_argument("--include-transcript", action="store_true", help="append the raw transcript to the PDF")
    parser.add_argument("--markdown", action="store_true", help="also write a .md next to each PDF")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached transcripts and model responses")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = Settings.load(
            model=args.model, output_dir=args.out_dir, use_cache=not args.no_cache
        )
        settings.require_api_key()
    except ConfigError as exc:
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
                        explicit=args.output if len(refs) == 1 and len(args.urls) == 1 else None,
                        folder=folder,
                        index=position if len(refs) > 1 else None,
                    )
                    results.append((_write(document, destination, args), document))

            if args.combined and len(refs) > 1 and documents:
                destination = args.output or (
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
