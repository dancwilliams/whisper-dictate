"""Secure credential storage using Windows Credential Manager.

This module provides secure storage for sensitive data like API keys using
the system's native credential storage (Windows Credential Manager on Windows).
Credentials are encrypted by the operating system and tied to the user account.
"""

import logging

import keyring
from keyring.errors import PasswordDeleteError

logger = logging.getLogger(__name__)

# Service name for keyring storage
SERVICE_NAME = "WhisperDictate"

# Credential keys
LLM_API_KEY = "llm_api_key"


class CredentialStorageError(Exception):
    """Raised when credential storage operations fail."""

    pass


def store_credential(key: str, value: str) -> None:
    """Store a credential securely in the system keyring.

    Args:
        key: The credential identifier (e.g., "llm_api_key")
        value: The credential value to store

    Raises:
        CredentialStorageError: If storage fails
        ValueError: If value is empty
    """
    if not value or not value.strip():
        raise ValueError("Credential value cannot be empty")

    try:
        keyring.set_password(SERVICE_NAME, key, value)
        logger.info(f"Stored credential: {key}")
    except Exception as e:
        # KeyringError, or a backend that failed to initialise
        logger.error(f"Failed to store credential {key}: {e}")
        raise CredentialStorageError(f"Failed to store credential: {e}") from e


def retrieve_credential(key: str) -> str | None:
    """Retrieve a credential from the system keyring.

    Args:
        key: The credential identifier (e.g., "llm_api_key")

    Returns:
        The credential value if found, None otherwise

    Raises:
        CredentialStorageError: If retrieval fails
    """
    try:
        value = keyring.get_password(SERVICE_NAME, key)
        if value:
            logger.debug(f"Retrieved credential: {key}")
        else:
            logger.debug(f"No credential found for: {key}")
        return value
    except Exception as e:
        # KeyringError, or a backend that failed to initialise
        logger.error(f"Failed to retrieve credential {key}: {e}")
        raise CredentialStorageError(f"Failed to retrieve credential: {e}") from e


def delete_credential(key: str) -> None:
    """Delete a credential from the system keyring.

    Args:
        key: The credential identifier (e.g., "llm_api_key")

    Raises:
        CredentialStorageError: If deletion fails
    """
    try:
        keyring.delete_password(SERVICE_NAME, key)
        logger.info(f"Deleted credential: {key}")
    except PasswordDeleteError:
        # Credential doesn't exist - not an error
        logger.debug(f"No credential to delete: {key}")
    except Exception as e:
        # KeyringError, or a backend that failed to initialise
        logger.error(f"Failed to delete credential {key}: {e}")
        raise CredentialStorageError(f"Failed to delete credential: {e}") from e
