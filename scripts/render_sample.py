"""Render a synthetic explainer so PDF layout can be checked without API calls."""

from __future__ import annotations

from pathlib import Path

from ytexplain.models import (
    Document,
    Explainer,
    Section,
    Segment,
    Transcript,
    VideoMeta,
)
from ytexplain.render import build_pdf
from ytexplain.render.text import to_markdown

BODY = """Python's `asyncio` event loop runs a single thread and interleaves work at
`await` points. That is the whole trick: **nothing is preempted**, so a coroutine keeps
the loop until it yields. See the [docs](https://docs.python.org/3/library/asyncio.html).

### Why a task is not a thread

- A *task* wraps a coroutine and schedules it on the loop.
  - It starts running only after the current coroutine yields.
  - Cancellation is delivered as an exception at the next `await`.
- A thread is preempted by the interpreter every few milliseconds.

1. Create the coroutine object.
2. Wrap it with `asyncio.create_task`.
3. Await it, or gather several at once.

> A blocking call such as `time.sleep(5)` freezes every task on the loop, because the
> loop never regains control. Use `await asyncio.sleep(5)` instead.

```python
import asyncio

async def fetch(name: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return f"{name} done"

async def main() -> None:
    results = await asyncio.gather(fetch("a", 0.2), fetch("b", 0.1))
    print(results)

asyncio.run(main())
```

| Primitive | Blocks the loop | Use when |
| --- | --- | --- |
| `time.sleep` | Yes | never inside a coroutine |
| `asyncio.sleep` | No | pacing async work |
| `run_in_executor` | No | wrapping blocking library calls |

---

The ordering above is deterministic for a given schedule, which is why tests over
`asyncio` code are reproducible in practice.
"""


def main() -> None:
    transcript = Transcript(
        segments=[
            Segment(start=float(i * 12), duration=12.0, text=f"caption cue number {i}")
            for i in range(40)
        ],
        language_code="hi",
        is_generated=True,
        source="sample",
    )
    explainer = Explainer(
        title="How the asyncio event loop actually schedules your coroutines",
        abstract="A walkthrough of the single-threaded event loop, how tasks are scheduled, "
        "and why one blocking call stalls an entire async program.",
        prerequisites=["Basic Python functions and exceptions", "What a coroutine is"],
        sections=[
            Section(heading="The event loop in one thread", focus="", start=0, end=200, body=BODY),
            Section(heading="Tasks, cancellation and gather", focus="", start=200, end=480, body=BODY),
        ],
        key_terms=[
            ("Event loop", "The scheduler that runs coroutines and resumes them at await points."),
            ("Task", "A coroutine wrapped so the loop can schedule it independently."),
        ],
        takeaways=["Never block the loop", "Cancellation lands at the next await"],
        source_language="hi",
        translated=True,
        model="anthropic/claude-sonnet-5",
    )
    document = Document(
        meta=VideoMeta(
            video_id="dQw4w9WgXcQ",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Asyncio deep dive",
            channel="Sample Channel",
            duration=480,
        ),
        explainer=explainer,
        transcript=transcript,
    )

    out = Path("out/sample.pdf")
    build_pdf([document], out, include_transcript=True)
    Path("out/sample.md").write_text(to_markdown(document), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")

    combined = build_pdf([document, document], Path("out/sample-playlist.pdf"), collection_title="Sample playlist")
    print(f"wrote {combined} ({combined.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
