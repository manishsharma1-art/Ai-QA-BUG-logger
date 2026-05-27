"""
Startup env-var validator for the QA Bug Logger Bot.

Inspects the loaded Settings for shapes known to indicate a corrupted
--set-env-vars deploy (specifically the RC2 space-separator bug that
concatenated `DEMO_SPACE_ID=...` into the API key value).

Never raises, never mutates settings — only logs warnings prefixed
`ENV_VALIDATION:` so they are greppable in /logs.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List

logger = logging.getLogger("qa_bugbot.env_validator")

# Required keys the validator expects to be non-empty.
REQUIRED_KEYS = ("llm_api_key", "openproject_base_url")

# RC2 corruption signature: a value containing `=` followed by an UPPER_SNAKE token,
# e.g. "8cf6...e08ea593 DEMO_SPACE_ID=AAQAhf6qdAw".
_RC2_CORRUPTION_RE = re.compile(r"=[A-Z][A-Z0-9_]{2,}")

# DEMO_SPACE_ID shape: alphanumeric plus -_ (Google Chat space id format).
_SPACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# LLM_API_KEY expected gateway prefix.
_LLM_KEY_PREFIX = "sk-"


def validate_env_vars(settings) -> List[str]:
    """
    Run 5 structural checks against the loaded Settings.

    Returns:
        list[str] of human-readable warning messages (may be empty).
        Each warning is also logged at WARNING level prefixed `ENV_VALIDATION:`.
        On empty result, logs `ENV_VALIDATION: all checks passed` at INFO.

    Never raises. Never mutates settings.
    """
    warnings: List[str] = []

    # Helper: get a setting attribute defensively
    def _get(key: str, default: str = "") -> str:
        return getattr(settings, key, default) or ""

    # ── Check 1: required keys non-empty ──
    for key in REQUIRED_KEYS:
        value = _get(key)
        if not value:
            warnings.append(f"{key.upper()} is empty")

    # ── Check 2: no whitespace / CR / LF in any string value ──
    for field_name in dir(settings):
        if field_name.startswith("_"):
            continue
        try:
            value = getattr(settings, field_name)
        except Exception:
            continue
        if not isinstance(value, str) or not value:
            continue
        if value != value.strip() or "\n" in value or "\r" in value:
            warnings.append(
                f"{field_name.upper()} contains whitespace/newline — likely corrupted"
            )

    # ── Check 3: RC2 corruption signature (=UPPER_SNAKE token inside a value) ──
    for field_name in ("default_openproject_api_key", "llm_api_key", "demo_space_id"):
        value = _get(field_name)
        if value and _RC2_CORRUPTION_RE.search(value):
            warnings.append(
                f"{field_name.upper()} appears corrupted: contains '=KEY=' substring "
                f"(suggests --set-env-vars used space separator instead of comma)"
            )

    # ── Check 4: LLM_API_KEY starts with the gateway prefix ──
    llm_key = _get("llm_api_key")
    if llm_key and not llm_key.startswith(_LLM_KEY_PREFIX):
        warnings.append(
            f"LLM_API_KEY does not start with expected '{_LLM_KEY_PREFIX}' prefix"
        )

    # ── Check 5: DEMO_SPACE_ID shape (only when non-empty — empty is its own warning) ──
    demo_space = _get("demo_space_id")
    if demo_space:
        if not _SPACE_ID_RE.match(demo_space):
            warnings.append(
                f"DEMO_SPACE_ID does not match expected shape (alphanumeric + -_): "
                f"got {demo_space!r}"
            )
    else:
        warnings.append(
            "DEMO_SPACE_ID is empty — demo-space fallback for unregistered users will be disabled"
        )

    # ── Emit log lines ──
    for w in warnings:
        logger.warning("ENV_VALIDATION: %s", w)
    if not warnings:
        logger.info("ENV_VALIDATION: all checks passed")

    return warnings


def read_build_marker() -> str:
    """
    Resolve the build marker for this running container.

    Order of precedence:
      1. /app/BUILD_MARKER file (written at Docker build time, see task 7.2)
      2. BUILD_MARKER env var
      3. dev-<unix-timestamp> fallback for local development
    """
    marker_path = "/app/BUILD_MARKER"
    try:
        if os.path.exists(marker_path):
            with open(marker_path, "r", encoding="utf-8") as f:
                value = f.read().strip()
                if value:
                    return value
    except Exception:
        pass

    env_value = os.environ.get("BUILD_MARKER", "").strip()
    if env_value:
        return env_value

    import time
    return f"dev-{int(time.time())}"
