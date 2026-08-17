"""Content-addressed disk cache for transcripts and model responses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .files import write_atomic_text


class Cache:
    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled

    @staticmethod
    def key(*parts: Any) -> str:
        digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()
        return digest[:32]

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{key}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(namespace, key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        if not self.enabled:
            return
        write_atomic_text(
            self._path(namespace, key), json.dumps(value, ensure_ascii=False)
        )
