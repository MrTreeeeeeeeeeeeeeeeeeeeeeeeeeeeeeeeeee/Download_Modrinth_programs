from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ResolvedToken:
    token: str | None
    source: str


def normalize_token(value: str | None) -> str | None:
    """Normalize supported token input forms into the raw Authorization value."""
    if value is None:
        return None

    token = value.strip().strip('"').strip("'").strip()
    if not token:
        return None

    if token.lower().startswith("authorization:"):
        token = token.split(":", 1)[1].strip()

    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    return token or None


def mask_token(value: str | None) -> str:
    token = normalize_token(value)
    if not token:
        return "(none)"
    if len(token) <= 8:
        return f"{token[:2]}..."
    return f"{token[:4]}...{token[-4:]}"


def resolve_token(
    *,
    cli_token: str | None = None,
    saved_token: str | None = None,
    no_token: bool = False,
    env: Mapping[str, str] | None = None,
    env_var: str = "MODRINTH_TOKEN",
) -> ResolvedToken:
    if no_token:
        return ResolvedToken(None, "none")

    env_values = os.environ if env is None else env
    candidates = (
        ("cli", cli_token),
        ("env", env_values.get(env_var)),
        ("saved", saved_token),
    )

    for source, value in candidates:
        token = normalize_token(value)
        if token:
            return ResolvedToken(token, source)

    return ResolvedToken(None, "none")
