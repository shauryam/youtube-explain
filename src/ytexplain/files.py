"""Writing output files without ever leaving a half-written one behind."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


@contextmanager
def atomic_path(target: Path) -> Iterator[Path]:
    """Yield a path to write, then move it over `target` once the block succeeds.

    A reader sees either the previous file or the complete new one. Without this a
    kill during a long render (`multiBuild` takes seconds) leaves a truncated PDF
    under the final name, which looks like a finished run to anything listing the
    output directory.

    The temporary file is a sibling of the target because `os.replace` is only
    atomic within one filesystem, and it carries a leading dot so a directory
    listing does not advertise work in progress.

    The caller creates the file rather than `mkstemp`, which would make it private
    to the owner: `os.replace` keeps the temporary file's permissions, so a
    generated PDF would end up mode 600 and unreadable by anything else on the
    machine. Letting the writer open it applies the usual umask instead.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid4().hex[:8]}.tmp")
    try:
        yield temp
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def write_atomic_text(target: Path, text: str, encoding: str = "utf-8") -> Path:
    target = Path(target)
    with atomic_path(target) as temp:
        temp.write_text(text, encoding=encoding)
    return target
