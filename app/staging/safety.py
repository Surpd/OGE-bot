"""Fail before migrations/webhook registration when staging isolation is unproven."""

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

from app.config import Settings


def running_sha() -> str:
    # Render supplies this from the checkout; Docker receives a build-time stamp.
    stamped = os.getenv("RENDER_GIT_COMMIT") or os.getenv("APP_BUILD_SHA")
    if stamped:
        return stamped
    root = Path(__file__).resolve().parents[2]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def validate_settings(s: Settings) -> None:
    configured = any(
        (
            s.staging_owner_id,
            s.staging_bot_id,
            s.staging_hostname,
            s.staging_release_sha,
            s.staging_production_bot_id,
            s.staging_production_hostname,
        )
    )
    if s.app_env != "staging":
        if configured:
            raise RuntimeError("Staging settings require APP_ENV=staging")
        return
    if (
        not s.staging_owner_id
        or not s.staging_bot_id
        or not s.staging_production_bot_id
        or s.staging_bot_id == s.staging_production_bot_id
    ):
        raise RuntimeError("Staging requires distinct bot identities and one owner")
    token_id = (s.telegram_bot_token or "").partition(":")[0]
    if token_id != str(s.staging_bot_id):
        raise RuntimeError("The token does not identify the approved staging bot")
    url = urlsplit(s.webhook_base_url or "")
    if (
        url.scheme != "https"
        or url.netloc != s.staging_hostname
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or not s.staging_hostname
        or not s.staging_production_hostname
        or s.staging_hostname == s.staging_production_hostname
        or not s.telegram_webhook_secret
    ):
        raise RuntimeError("Staging requires its own HTTPS origin and webhook secret")
    if not re.fullmatch(r"[0-9a-f]{40}", s.staging_release_sha or ""):
        raise RuntimeError("Pin STAGING_RELEASE_SHA to the candidate commit")
    if running_sha() != s.staging_release_sha:
        raise RuntimeError("Running code does not match STAGING_RELEASE_SHA")
    if s.openai_api_key is not None or s.oge_grading_enabled:
        raise RuntimeError("Staging forbids model credentials and paid grading")
    if not s.database_url:
        raise RuntimeError("Staging requires its isolated database")


async def validate_database(pool: asyncpg.Pool, s: Settings) -> None:
    exists = await pool.fetchval("SELECT to_regclass('staging.identity') IS NOT NULL")
    if s.app_env != "staging":
        if exists:
            raise RuntimeError("A staging database cannot serve another environment")
        return
    if not exists:
        raise RuntimeError("Initialize a NEW empty staging database before starting the app")
    row = await pool.fetchrow(
        "SELECT *, current_database() AS db, current_user AS role FROM staging.identity"
    )
    if (
        row is None
        or row["bot_id"] != s.staging_bot_id
        or row["owner_id"] != s.staging_owner_id
        or row["hostname"] != s.staging_hostname
        or row["database_name"] != row["db"]
        or row["database_role"] != row["role"]
    ):
        raise RuntimeError("Staging database identity does not match this instance")
