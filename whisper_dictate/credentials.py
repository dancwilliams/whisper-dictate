"""Secure credential storage using Windows Credential Manager.

This module provides secure storage for sensitive data like API keys using
the system's native credential storage (Windows Credential Manager on Windows).
Credentials are encrypted by the operating system and tied to the user account.
"""

import logging

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

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
        ValueError: If key or value is empty
    """
    if not key or not key.strip():
        raise ValueError("Credential key cannot be empty")

    if not value or not value.strip():
        raise ValueError("Credential value cannot be empty")

    try:
        keyring.set_password(SERVICE_NAME, key, value)
        logger.info(f"Stored credential: {key}")
    except KeyringError as e:
        logger.error(f"Failed to store credential {key}: {e}")
        raise CredentialStorageError(f"Failed to store credential: {e}") from e
    except Exception as e:
        # Catch unexpected errors (e.g., backend initialization issues)
        logger.error(f"Unexpected error storing credential {key}: {e}")
        raise CredentialStorageError(f"Unexpected error storing credential: {e}") from e


def retrieve_credential(key: str) -> str | None:
    """Retrieve a credential from the system keyring.

    Args:
        key: The credential identifier (e.g., "llm_api_key")

    Returns:
        The credential value if found, None otherwise

    Raises:
        CredentialStorageError: If retrieval fails
        ValueError: If key is empty
    """
    if not key or not key.strip():
        raise ValueError("Credential key cannot be empty")

    try:
        value = keyring.get_password(SERVICE_NAME, key)
        if value:
            logger.debug(f"Retrieved credential: {key}")
        else:
            logger.debug(f"No credential found for: {key}")
        return value
    except KeyringError as e:
        logger.error(f"Failed to retrieve credential {key}: {e}")
        raise CredentialStorageError(f"Failed to retrieve credential: {e}") from e
    except Exception as e:
        # Catch unexpected errors
        logger.error(f"Unexpected error retrieving credential {key}: {e}")
        raise CredentialStorageError(f"Unexpected error retrieving credential: {e}") from e


def delete_credential(key: str) -> None:
    """Delete a credential from the system keyring.

    Args:
        key: The credential identifier (e.g., "llm_api_key")

    Raises:
        CredentialStorageError: If deletion fails
        ValueError: If key is empty
    """
    if not key or not key.strip():
        raise ValueError("Credential key cannot be empty")

    try:
        keyring.delete_password(SERVICE_NAME, key)
        logger.info(f"Deleted credential: {key}")
    except PasswordDeleteError:
        # Credential doesn't exist - not an error
        logger.debug(f"No credential to delete: {key}")
    except KeyringError as e:
        logger.error(f"Failed to delete credential {key}: {e}")
        raise CredentialStorageError(f"Failed to delete credential: {e}") from e
    except Exception as e:
        # Catch unexpected errors
        logger.error(f"Unexpected error deleting credential {key}: {e}")
        raise CredentialStorageError(f"Unexpected error deleting credential: {e}") from e


def migrate_from_plaintext(plaintext_value: str, key: str) -> bool:
    """Migrate a plaintext credential to secure storage.

    Args:
        plaintext_value: The plaintext credential value
        key: The credential identifier

    Returns:
        True if migration successful, False otherwise
    """
    if not plaintext_value or not plaintext_value.strip():
        logger.debug(f"No plaintext value to migrate for {key}")
        return False

    try:
        store_credential(key, plaintext_value)
        logger.info(f"Migrated plaintext credential to secure storage: {key}")
        return True
    except (CredentialStorageError, ValueError) as e:
        logger.warning(f"Failed to migrate credential {key}: {e}")
        return False


def is_credential_stored(key: str) -> bool:
    """Check if a credential exists in secure storage.

    Args:
        key: The credential identifier

    Returns:
        True if credential exists, False otherwise
    """
    try:
        return retrieve_credential(key) is not None
    except (CredentialStorageError, ValueError):
        return False
