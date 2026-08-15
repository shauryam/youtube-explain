"""Runtime configuration, resolved from CLI flags then environment then defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "anthropic/claude-sonnet-5"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class ConfigError(RuntimeError):
    pass


@dataclass(slots=True)
class Settings:
    model: str
    output_dir: Path
    cache_dir: Path
    api_key: str | None = None
    use_cache: bool = True

    @classmethod
    def load(
        cls,
        *,
        model: str | None = None,
        output_dir: str | Path | None = None,
        cache_dir: str | Path | None = None,
        use_cache: bool = True,
    ) -> Settings:
        load_dotenv()
        return cls(
            api_key=os.environ.get("OPENROUTER_API_KEY") or None,
            model=model or os.environ.get("YTEXPLAIN_MODEL") or DEFAULT_MODEL,
            output_dir=Path(output_dir or os.environ.get("YTEXPLAIN_OUTPUT_DIR") or "out"),
            cache_dir=Path(cache_dir or os.environ.get("YTEXPLAIN_CACHE_DIR") or ".cache"),
            use_cache=use_cache,
        )

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigError(
                "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key "
                "from https://openrouter.ai/keys"
            )
        return self.api_key
