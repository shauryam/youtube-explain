"""Runtime configuration, resolved from CLI flags then environment then defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv, set_key

DEFAULT_MODEL = "z-ai/glm-5.2"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MODELS_ENDPOINT = "https://openrouter.ai/api/v1/models"


class ConfigError(RuntimeError):
    pass


def dotenv_path() -> Path:
    """The `.env` to read and write: the nearest one from the working directory upward.

    `load_dotenv()` on its own searches upward from this file, which for an installed
    copy means somewhere inside the virtualenv — so the `.env` beside the videos you are
    working on would be ignored. `usecwd` puts the search where the user expects it, and
    keeps reading and writing the same file.
    """
    found = find_dotenv(usecwd=True)
    return Path(found) if found else Path.cwd() / ".env"


@dataclass(slots=True)
class Settings:
    model: str
    output_dir: Path
    cache_dir: Path
    api_key: str | None = None
    use_cache: bool = True
    # False means nobody chose this model and DEFAULT_MODEL applied, which is what
    # lets the CLI tell a first run apart from a deliberate choice.
    model_configured: bool = True

    @classmethod
    def load(
        cls,
        *,
        model: str | None = None,
        output_dir: str | Path | None = None,
        cache_dir: str | Path | None = None,
        use_cache: bool = True,
    ) -> Settings:
        load_dotenv(dotenv_path())
        chosen = model or os.environ.get("YTEXPLAIN_MODEL")
        return cls(
            api_key=os.environ.get("OPENROUTER_API_KEY") or None,
            model=chosen or DEFAULT_MODEL,
            output_dir=Path(output_dir or os.environ.get("YTEXPLAIN_OUTPUT_DIR") or "out"),
            cache_dir=Path(cache_dir or os.environ.get("YTEXPLAIN_CACHE_DIR") or ".cache"),
            use_cache=use_cache,
            model_configured=bool(chosen),
        )

    def remember_model(self, path: str | Path | None = None) -> Path:
        """Persist this model as `YTEXPLAIN_MODEL`, so a chosen model survives the run.

        `set_key` rewrites an existing assignment instead of appending a second one, and
        leaves the rest of the file — the API key above all — untouched.
        """
        target = Path(path) if path else dotenv_path()
        target.touch(exist_ok=True)
        set_key(str(target), "YTEXPLAIN_MODEL", self.model, quote_mode="never")
        return target

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigError(
                "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key "
                "from https://openrouter.ai/keys"
            )
        return self.api_key
