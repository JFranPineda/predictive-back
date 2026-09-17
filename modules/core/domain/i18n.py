"""Translatable catalogue text.

Half the strings a user reads in this system are *data*, not code: status names,
techniques, magnitudes, standards, fault modes, operating parameters. A .po file
cannot reach them, because a company adds its own from the UI.

So catalogue rows carry their translations with them, and the language is
resolved with an explicit fallback chain instead of "whatever is in `name`".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_LANGUAGE = "es"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "en")


class UnsupportedLanguage(ValueError):
    pass


def normalise_language(tag: str | None) -> str | None:
    """`es-PE` -> `es`, `EN` -> `en`, anything unknown -> None.

    Returning None rather than the default matters: the caller has its own
    fallback chain, and silently answering "es" here would swallow the
    company's configured language."""
    if not tag:
        return None
    base = tag.strip().lower().replace("_", "-").split("-")[0]
    return base if base in SUPPORTED_LANGUAGES else None


def resolve_language(
    *,
    requested: str | None = None,
    user_preference: str | None = None,
    company_default: str | None = None,
) -> str:
    """Request header → user preference → company default → `es`."""
    for candidate in (requested, user_preference, company_default):
        resolved = normalise_language(candidate)
        if resolved:
            return resolved
    return DEFAULT_LANGUAGE


def parse_accept_language(header: str | None) -> str | None:
    """First supported language of an `Accept-Language` header, by quality."""
    if not header:
        return None
    entries: list[tuple[float, str]] = []
    for index, part in enumerate(header.split(",")):
        chunk, _, params = part.strip().partition(";")
        quality = 1.0
        if params.startswith("q="):
            try:
                quality = float(params[2:])
            except ValueError:
                quality = 0.0
        # Preserve the header order for equal quality values.
        entries.append((-quality, chunk.strip()) if chunk else (0.0, ""))
        del index
    for _, tag in sorted(entries, key=lambda item: item[0]):
        resolved = normalise_language(tag)
        if resolved:
            return resolved
    return None


@dataclass(frozen=True, slots=True)
class TranslatedText:
    """`{"es": "Alarma", "en": "Alarm"}` with a guaranteed answer.

    A missing translation falls back to the default language and then to any
    value present — showing a Spanish label to an English user is bad, showing
    an empty cell is worse.
    """

    values: dict[str, str]

    def get(self, language: str, fallback: str = DEFAULT_LANGUAGE) -> str:
        for candidate in (language, fallback):
            value = self.values.get(candidate, "").strip()
            if value:
                return value
        return next((v for v in self.values.values() if v.strip()), "")

    def with_translation(self, language: str, value: str) -> TranslatedText:
        if language not in SUPPORTED_LANGUAGES:
            raise UnsupportedLanguage(language)
        return TranslatedText({**self.values, language: value})

    def missing(self) -> tuple[str, ...]:
        """Which supported languages have no text yet. Feeds the "translations
        pending" badge in the catalogue screens."""
        return tuple(
            language
            for language in SUPPORTED_LANGUAGES
            if not self.values.get(language, "").strip()
        )

    @classmethod
    def of(cls, value: Any, default_language: str = DEFAULT_LANGUAGE) -> TranslatedText:
        """Accepts a plain string (legacy rows) or a dict, so a migration can be
        gradual instead of a big-bang rewrite."""
        if isinstance(value, TranslatedText):
            return value
        if isinstance(value, dict):
            return cls({str(k): str(v) for k, v in value.items()})
        return cls({default_language: str(value or "")})
