"""Business profile library: subjects, stop words, persona and fallback texts.

A profile describes *what* an account sells. Account-specific runtime settings
(CDP port, Chrome user-data-dir, DB, tariff mode) stay in accounts/<name>.env.
Profiles are plain TOML and use only Python stdlib (tomllib).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Profile:
    name: str
    persona: str
    subject_keywords: tuple[str, ...]
    stop_patterns: tuple[str, ...]
    remote_only: bool
    fallback_enabled: bool
    fallback_templates: tuple[str, ...]


def _strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"profile field {field!r} must be an array of strings")
    return tuple(item.strip() for item in value if item.strip())


def load_profile(name: str, profiles_dir: Path) -> Profile:
    """Load and validate profiles/<name>.toml.

    Invalid/missing explicit profiles fail closed: silently falling back to another
    subject set could make the bot answer orders for the wrong tutoring offer.
    """
    name = name.strip()
    if not name or not _PROFILE_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid profile name: {name!r}")

    path = profiles_dir / f"{name}.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"profile not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML profile {path}: {exc}") from exc

    profile_id = str(data.get("id") or name).strip()
    if profile_id != name:
        raise ValueError(f"profile id {profile_id!r} does not match filename {name!r}")

    persona = str(data.get("persona") or name).strip()
    subject_keywords = _strings(data.get("subject_keywords"), "subject_keywords")
    stop_patterns = tuple(s.lower() for s in _strings(data.get("stop_patterns"), "stop_patterns"))
    remote_only = bool(data.get("remote_only", True))

    fallback = data.get("fallback") or {}
    if not isinstance(fallback, dict):
        raise ValueError("profile field 'fallback' must be a TOML table")
    fallback_enabled = bool(fallback.get("enabled", False))
    fallback_templates = _strings(fallback.get("templates"), "fallback.templates")
    if fallback_enabled and not fallback_templates:
        raise ValueError("fallback.enabled=true requires at least one fallback template")

    return Profile(
        name=name,
        persona=persona,
        subject_keywords=subject_keywords,
        stop_patterns=stop_patterns,
        remote_only=remote_only,
        fallback_enabled=fallback_enabled,
        fallback_templates=fallback_templates,
    )
