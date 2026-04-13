from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from goodpdf.settings.config import AppConfig


def load_api_key(config: AppConfig) -> str:
    try:
        return keyring.get_password(config.keyring_service, config.keyring_username) or ""
    except KeyringError:
        return ""


def save_api_key(config: AppConfig, api_key: str) -> bool:
    try:
        keyring.set_password(config.keyring_service, config.keyring_username, api_key)
    except KeyringError:
        return False
    return True


def clear_api_key(config: AppConfig) -> bool:
    try:
        keyring.delete_password(config.keyring_service, config.keyring_username)
    except PasswordDeleteError:
        return True
    except KeyringError:
        return False
    return True
