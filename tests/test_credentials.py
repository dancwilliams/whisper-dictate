"""Tests for secure credential storage."""

from unittest.mock import patch

import pytest

from whisper_dictate import credentials


class TestStoreCredential:
    """Test credential storage."""

    @patch("whisper_dictate.credentials.keyring")
    def test_store_credential_success(self, mock_keyring):
        """Test storing a credential successfully."""
        credentials.store_credential("test_key", "test_value")

        mock_keyring.set_password.assert_called_once_with(
            credentials.SERVICE_NAME, "test_key", "test_value"
        )

    @patch("whisper_dictate.credentials.keyring")
    def test_store_credential_empty_key(self, mock_keyring):
        """Test storing with empty key raises ValueError."""
        with pytest.raises(ValueError, match="key cannot be empty"):
            credentials.store_credential("", "test_value")

        with pytest.raises(ValueError, match="key cannot be empty"):
            credentials.store_credential("   ", "test_value")

        mock_keyring.set_password.assert_not_called()

    @patch("whisper_dictate.credentials.keyring")
    def test_store_credential_empty_value(self, mock_keyring):
        """Test storing with empty value raises ValueError."""
        with pytest.raises(ValueError, match="value cannot be empty"):
            credentials.store_credential("test_key", "")

        with pytest.raises(ValueError, match="value cannot be empty"):
            credentials.store_credential("test_key", "   ")

        mock_keyring.set_password.assert_not_called()

    @patch("whisper_dictate.credentials.keyring")
    def test_store_credential_keyring_error(self, mock_keyring):
        """Test handling of keyring errors during storage."""
        from keyring.errors import KeyringError

        mock_keyring.set_password.side_effect = KeyringError("Backend error")

        with pytest.raises(credentials.CredentialStorageError, match="Failed to store credential"):
            credentials.store_credential("test_key", "test_value")


class TestRetrieveCredential:
    """Test credential retrieval."""

    @patch("whisper_dictate.credentials.keyring")
    def test_retrieve_credential_found(self, mock_keyring):
        """Test retrieving an existing credential."""
        mock_keyring.get_password.return_value = "test_value"

        result = credentials.retrieve_credential("test_key")

        assert result == "test_value"
        mock_keyring.get_password.assert_called_once_with(credentials.SERVICE_NAME, "test_key")

    @patch("whisper_dictate.credentials.keyring")
    def test_retrieve_credential_not_found(self, mock_keyring):
        """Test retrieving a non-existent credential returns None."""
        mock_keyring.get_password.return_value = None

        result = credentials.retrieve_credential("test_key")

        assert result is None
        mock_keyring.get_password.assert_called_once_with(credentials.SERVICE_NAME, "test_key")

    @patch("whisper_dictate.credentials.keyring")
    def test_retrieve_credential_empty_key(self, mock_keyring):
        """Test retrieving with empty key raises ValueError."""
        with pytest.raises(ValueError, match="key cannot be empty"):
            credentials.retrieve_credential("")

        with pytest.raises(ValueError, match="key cannot be empty"):
            credentials.retrieve_credential("   ")

        mock_keyring.get_password.assert_not_called()

    @patch("whisper_dictate.credentials.keyring")
    def test_retrieve_credential_keyring_error(self, mock_keyring):
        """Test handling of keyring errors during retrieval."""
        from keyring.errors import KeyringError

        mock_keyring.get_password.side_effect = KeyringError("Backend error")

        with pytest.raises(
            credentials.CredentialStorageError, match="Failed to retrieve credential"
        ):
            credentials.retrieve_credential("test_key")


class TestDeleteCredential:
    """Test credential deletion."""

    @patch("whisper_dictate.credentials.keyring")
    def test_delete_credential_success(self, mock_keyring):
        """Test deleting a credential successfully."""
        credentials.delete_credential("test_key")

        mock_keyring.delete_password.assert_called_once_with(credentials.SERVICE_NAME, "test_key")

    @patch("whisper_dictate.credentials.keyring")
    def test_delete_credential_not_found(self, mock_keyring):
        """Test deleting non-existent credential doesn't raise error."""
        from keyring.errors import PasswordDeleteError

        mock_keyring.delete_password.side_effect = PasswordDeleteError()

        # Should not raise
        credentials.delete_credential("test_key")

        mock_keyring.delete_password.assert_called_once_with(credentials.SERVICE_NAME, "test_key")

    @patch("whisper_dictate.credentials.keyring")
    def test_delete_credential_empty_key(self, mock_keyring):
        """Test deleting with empty key raises ValueError."""
        with pytest.raises(ValueError, match="key cannot be empty"):
            credentials.delete_credential("")

        with pytest.raises(ValueError, match="key cannot be empty"):
            credentials.delete_credential("   ")

        mock_keyring.delete_password.assert_not_called()

    @patch("whisper_dictate.credentials.keyring")
    def test_delete_credential_keyring_error(self, mock_keyring):
        """Test handling of keyring errors during deletion."""
        from keyring.errors import KeyringError

        mock_keyring.delete_password.side_effect = KeyringError("Backend error")

        with pytest.raises(credentials.CredentialStorageError, match="Failed to delete credential"):
            credentials.delete_credential("test_key")


class TestMigrateFromPlaintext:
    """Test migration of plaintext credentials."""

    @patch("whisper_dictate.credentials.store_credential")
    def test_migrate_from_plaintext_success(self, mock_store):
        """Test successful migration of plaintext credential."""
        result = credentials.migrate_from_plaintext("my_api_key", "test_key")

        assert result is True
        mock_store.assert_called_once_with("test_key", "my_api_key")

    @patch("whisper_dictate.credentials.store_credential")
    def test_migrate_from_plaintext_empty_value(self, mock_store):
        """Test migration with empty value returns False."""
        result = credentials.migrate_from_plaintext("", "test_key")
        assert result is False

        result = credentials.migrate_from_plaintext("   ", "test_key")
        assert result is False

        mock_store.assert_not_called()

    @patch("whisper_dictate.credentials.store_credential")
    def test_migrate_from_plaintext_storage_error(self, mock_store):
        """Test migration handles storage errors gracefully."""
        mock_store.side_effect = credentials.CredentialStorageError("Storage failed")

        result = credentials.migrate_from_plaintext("my_api_key", "test_key")

        assert result is False


class TestIsCredentialStored:
    """Test checking if credential exists."""

    @patch("whisper_dictate.credentials.retrieve_credential")
    def test_is_credential_stored_true(self, mock_retrieve):
        """Test checking for existing credential."""
        mock_retrieve.return_value = "some_value"

        result = credentials.is_credential_stored("test_key")

        assert result is True
        mock_retrieve.assert_called_once_with("test_key")

    @patch("whisper_dictate.credentials.retrieve_credential")
    def test_is_credential_stored_false(self, mock_retrieve):
        """Test checking for non-existent credential."""
        mock_retrieve.return_value = None

        result = credentials.is_credential_stored("test_key")

        assert result is False
        mock_retrieve.assert_called_once_with("test_key")

    @patch("whisper_dictate.credentials.retrieve_credential")
    def test_is_credential_stored_error_returns_false(self, mock_retrieve):
        """Test that errors during check return False."""
        mock_retrieve.side_effect = credentials.CredentialStorageError("Error")

        result = credentials.is_credential_stored("test_key")

        assert result is False
