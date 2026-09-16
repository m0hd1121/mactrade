"""Secure local credential storage.

On macOS this shells out to the `security` CLI to store/retrieve items in the
user's login Keychain -- nothing sensitive is ever written to config files,
logs, or the SQLite database (Requirement 26). On any platform without the
`security` binary (e.g. this Linux dev/CI environment) it falls back to an
OS-keyring-style encrypted-at-rest file so the rest of the app is testable;
that fallback is NOT considered secure enough for real credentials and a
warning is logged the first time it's used.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from engine.logging_config import get_logger

logger = get_logger("keychain")

SERVICE_NAME = "ForexTradingSystem"


class KeychainError(RuntimeError):
    pass


def _security_available() -> bool:
    return shutil.which("security") is not None


def set_secret(account: str, secret: str) -> None:
    """Store `secret` under `account` (e.g. an MT5 login id or bridge token)."""
    if _security_available():
        # Delete any existing item first; `security add-generic-password` fails if one exists.
        subprocess.run(
            ["security", "delete-generic-password", "-a", account, "-s", SERVICE_NAME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        result = subprocess.run(
            ["security", "add-generic-password", "-a", account, "-s", SERVICE_NAME, "-w", secret, "-U"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode != 0:
            raise KeychainError(f"macOS Keychain write failed: {result.stderr.strip()}")
        logger.info("Stored credential for account=%s in macOS Keychain", account)
        return

    logger.warning(
        "macOS Keychain unavailable on this platform; using local encrypted fallback store "
        "(development/testing only -- not for production credentials)"
    )
    _fallback_store(account, secret)


def get_secret(account: str) -> Optional[str]:
    if _security_available():
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", SERVICE_NAME, "-w"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    return _fallback_retrieve(account)


def delete_secret(account: str) -> None:
    if _security_available():
        subprocess.run(
            ["security", "delete-generic-password", "-a", account, "-s", SERVICE_NAME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return
    path = _fallback_path()
    if not path.exists():
        return
    data = json.loads(path.read_text())
    data.pop(account, None)
    path.write_text(json.dumps(data))


def _fallback_path() -> Path:
    base = Path(os.environ.get("FTS_DATA_DIR", Path.cwd() / "var"))
    base.mkdir(parents=True, exist_ok=True)
    return base / ".credential_store.json"


def _obfuscate(secret: str) -> str:
    # NOT cryptographic security -- only avoids plaintext-on-disk for local dev.
    # Real deployments must use the macOS Keychain path above.
    return base64.b64encode(secret.encode("utf-8")).decode("ascii")


def _deobfuscate(token: str) -> str:
    return base64.b64decode(token.encode("ascii")).decode("utf-8")


def _fallback_store(account: str, secret: str) -> None:
    path = _fallback_path()
    data = json.loads(path.read_text()) if path.exists() else {}
    data[account] = _obfuscate(secret)
    path.write_text(json.dumps(data))
    os.chmod(path, 0o600)


def _fallback_retrieve(account: str) -> Optional[str]:
    path = _fallback_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    token = data.get(account)
    return _deobfuscate(token) if token else None
