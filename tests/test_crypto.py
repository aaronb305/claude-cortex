"""Tests for the crypto module."""

import pytest
import os
import stat
from pathlib import Path
from unittest.mock import patch

from continuous_claude.ledger.crypto import (
    is_crypto_available,
    CRYPTO_AVAILABLE,
    Identity,
    KeyPair,
    TrustedKey,
    TrustLevel,
    VerifyResult,
    KeyManager,
    KeyStore,
    _compute_key_id,
    sign_block_hash,
    verify_block_signature,
    get_identity_path,
    get_keystore_path,
    load_identity_for_ledger,
    load_keystore_for_ledger,
)


# Skip all tests if cryptography is not installed
pytestmark = pytest.mark.skipif(
    not CRYPTO_AVAILABLE,
    reason="cryptography package not installed"
)


class TestIdentity:
    """Tests for Identity dataclass."""

    def test_identity_creation(self):
        """Should create identity with required fields."""
        identity = Identity(name="Test User", machine="test-machine")
        assert identity.name == "Test User"
        assert identity.machine == "test-machine"
        assert identity.email is None

    def test_identity_with_email(self):
        """Should create identity with optional email."""
        identity = Identity(
            name="Test User",
            machine="test-machine",
            email="test@example.com"
        )
        assert identity.email == "test@example.com"

    def test_identity_to_dict(self):
        """Should serialize to dictionary."""
        identity = Identity(
            name="Test User",
            machine="test-machine",
            email="test@example.com"
        )
        data = identity.to_dict()
        assert data == {
            "name": "Test User",
            "machine": "test-machine",
            "email": "test@example.com",
        }

    def test_identity_from_dict(self):
        """Should deserialize from dictionary."""
        data = {
            "name": "Test User",
            "machine": "test-machine",
            "email": "test@example.com",
        }
        identity = Identity.from_dict(data)
        assert identity.name == "Test User"
        assert identity.machine == "test-machine"
        assert identity.email == "test@example.com"


class TestKeyIdFormat:
    """Tests for key ID format."""

    def test_key_id_format_is_6_uppercase_hex(self, ledger_path):
        """Key ID should be 6 uppercase hex characters."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test", machine="test-machine")

        keypair = manager.generate_keypair(identity)

        assert len(keypair.key_id) == 6
        # Verify uppercase hex format (isupper() returns False for all-digit strings)
        assert all(c in "0123456789ABCDEF" for c in keypair.key_id)
        assert keypair.key_id == keypair.key_id.upper()  # Ensure it's uppercase

    def test_compute_key_id_consistency(self):
        """Same public key should produce same key ID."""
        # Use a fixed test value
        public_key_bytes = b"test_public_key_bytes_32_chars!"

        key_id_1 = _compute_key_id(public_key_bytes)
        key_id_2 = _compute_key_id(public_key_bytes)

        assert key_id_1 == key_id_2
        assert len(key_id_1) == 6
        assert key_id_1 == key_id_1.upper()  # Ensure uppercase (isupper() fails on all-digit strings)


class TestGenerateKeypair:
    """Tests for keypair generation."""

    def test_generate_keypair_creates_files(self, ledger_path):
        """Should create identity.json and .private_key files."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")

        manager.generate_keypair(identity)

        assert (ledger_path / "identity.json").exists()
        assert (ledger_path / ".private_key").exists()

    def test_generate_keypair_returns_keypair(self, ledger_path):
        """Should return a valid KeyPair object."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")

        keypair = manager.generate_keypair(identity)

        assert isinstance(keypair, KeyPair)
        assert len(keypair.public_key) > 0
        assert len(keypair.private_key) > 0
        assert len(keypair.key_id) == 6

    def test_generate_keypair_raises_if_exists(self, ledger_path):
        """Should raise FileExistsError if keypair already exists."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")

        manager.generate_keypair(identity)

        with pytest.raises(FileExistsError):
            manager.generate_keypair(identity)

    def test_private_key_permissions(self, ledger_path):
        """Private key should have restricted permissions (600)."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")

        manager.generate_keypair(identity)

        private_key_path = ledger_path / ".private_key"
        mode = stat.S_IMODE(os.stat(private_key_path).st_mode)
        assert mode == 0o600


class TestHasIdentity:
    """Tests for has_identity method."""

    def test_has_identity_returns_false_when_none(self, ledger_path):
        """Should return False when no identity is configured."""
        manager = KeyManager(ledger_path)
        assert manager.has_identity() is False

    def test_has_identity_returns_true_when_configured(self, ledger_path):
        """Should return True when identity is configured."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")

        manager.generate_keypair(identity)

        assert manager.has_identity() is True

    def test_has_identity_requires_both_files(self, ledger_path):
        """Should return False if only one file exists."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")

        manager.generate_keypair(identity)

        # Remove private key
        (ledger_path / ".private_key").unlink()
        assert manager.has_identity() is False


class TestSignAndVerify:
    """Tests for signing and verification."""

    def test_sign_and_verify(self, ledger_path):
        """Should sign data and verify signature successfully."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")
        keypair = manager.generate_keypair(identity)

        data = "test data to sign"
        signature = manager.sign(data)

        result = manager.verify(data, signature, keypair.key_id)

        assert result == VerifyResult.VALID

    def test_sign_returns_base64(self, ledger_path):
        """Signature should be base64-encoded."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")
        manager.generate_keypair(identity)

        signature = manager.sign("test data")

        # Should be valid base64
        import base64
        try:
            decoded = base64.b64decode(signature)
            assert len(decoded) > 0
        except Exception:
            pytest.fail("Signature is not valid base64")

    def test_verify_invalid_signature(self, ledger_path):
        """Invalid signature should return INVALID_SIGNATURE."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")
        keypair = manager.generate_keypair(identity)

        data = "test data"
        invalid_signature = "aW52YWxpZF9zaWduYXR1cmU="  # base64 of "invalid_signature"

        result = manager.verify(data, invalid_signature, keypair.key_id)

        assert result == VerifyResult.INVALID_SIGNATURE

    def test_verify_unknown_key(self, ledger_path):
        """Unknown key ID should return UNKNOWN_KEY."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test User", machine="test-machine")
        manager.generate_keypair(identity)

        data = "test data"
        signature = manager.sign(data)

        result = manager.verify(data, signature, "UNKNWN")

        assert result == VerifyResult.UNKNOWN_KEY


class TestKeyStoreOperations:
    """Tests for KeyStore (compatibility wrapper)."""

    def test_add_trusted_key(self, ledger_path):
        """Should add a trusted key via KeyManager."""
        manager = KeyManager(ledger_path)

        # Generate a keypair in a separate ledger to get a real key
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_identity = Identity(name="Other User", machine="other-machine")
        other_manager.generate_keypair(other_identity)

        # Export and import
        pem = other_manager.export_public_key()
        identity = Identity(name="Trusted User", machine="trusted-machine")

        trusted_key = manager.import_public_key(pem, identity)

        assert trusted_key is not None
        assert len(trusted_key.key_id) == 6

    def test_list_trusted_keys(self, ledger_path):
        """Should list all trusted keys."""
        manager = KeyManager(ledger_path)

        # Add multiple trusted keys
        for i in range(3):
            other_ledger = ledger_path.parent / f"other_ledger_{i}"
            other_ledger.mkdir()
            other_manager = KeyManager(other_ledger)
            other_manager.generate_keypair(
                Identity(name=f"User {i}", machine=f"machine-{i}")
            )
            pem = other_manager.export_public_key()
            manager.import_public_key(
                pem, Identity(name=f"Trusted User {i}", machine=f"machine-{i}")
            )

        keys = manager.list_trusted_keys()

        assert len(keys) == 3

    def test_get_trusted_key(self, ledger_path):
        """Should retrieve a trusted key by ID."""
        manager = KeyManager(ledger_path)

        # Add a trusted key
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_manager.generate_keypair(
            Identity(name="Other User", machine="other-machine")
        )
        pem = other_manager.export_public_key()
        trusted_key = manager.import_public_key(
            pem, Identity(name="Trusted User", machine="trusted-machine")
        )

        retrieved = manager.get_trusted_key(trusted_key.key_id)

        assert retrieved is not None
        assert retrieved.key_id == trusted_key.key_id
        assert retrieved.identity.name == "Trusted User"

    def test_remove_trusted_key(self, ledger_path):
        """Should remove a trusted key."""
        manager = KeyManager(ledger_path)

        # Add a trusted key
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_manager.generate_keypair(
            Identity(name="Other User", machine="other-machine")
        )
        pem = other_manager.export_public_key()
        trusted_key = manager.import_public_key(
            pem, Identity(name="Trusted User", machine="trusted-machine")
        )

        result = manager.remove_trusted_key(trusted_key.key_id)

        assert result is True
        assert manager.get_trusted_key(trusted_key.key_id) is None

    def test_set_trust_level(self, ledger_path):
        """Should change trust level for a key."""
        manager = KeyManager(ledger_path)

        # Add a trusted key with default level (MARGINAL)
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_manager.generate_keypair(
            Identity(name="Other User", machine="other-machine")
        )
        pem = other_manager.export_public_key()
        trusted_key = manager.import_public_key(
            pem,
            Identity(name="Trusted User", machine="trusted-machine"),
            trust_level=TrustLevel.MARGINAL
        )

        # Change to FULL trust
        result = manager.set_trust_level(trusted_key.key_id, TrustLevel.FULL)

        assert result is True
        updated = manager.get_trusted_key(trusted_key.key_id)
        assert updated.trust_level == TrustLevel.FULL

    def test_verify_with_trusted_key(self, ledger_path):
        """Should verify signature using a trusted key."""
        manager = KeyManager(ledger_path)
        manager.generate_keypair(Identity(name="Local", machine="local-machine"))

        # Create another keypair and add as trusted
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_keypair = other_manager.generate_keypair(
            Identity(name="Other User", machine="other-machine")
        )

        # Sign data with other key
        data = "test data from other"
        signature = other_manager.sign(data)

        # Add other's key as trusted
        pem = other_manager.export_public_key()
        manager.import_public_key(
            pem,
            Identity(name="Trusted Other", machine="other-machine"),
            trust_level=TrustLevel.FULL
        )

        # Verify with trusted key
        result = manager.verify(data, signature, other_keypair.key_id)

        assert result == VerifyResult.VALID


class TestKeyStoreClass:
    """Tests for KeyStore wrapper class."""

    def test_keystore_add_key(self, ledger_path):
        """Should add key via KeyStore interface."""
        keystore = KeyStore(ledger_path)

        # Generate a key to import
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_manager.generate_keypair(
            Identity(name="Other User", machine="other-machine")
        )
        pem = other_manager.export_public_key()

        trusted_key = keystore.add_key("Test User", pem)

        assert trusted_key is not None
        assert trusted_key.identity.name == "Test User"

    def test_keystore_list_keys(self, ledger_path):
        """Should list keys via KeyStore interface."""
        keystore = KeyStore(ledger_path)

        # Add a key
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_manager.generate_keypair(
            Identity(name="Other User", machine="other-machine")
        )
        pem = other_manager.export_public_key()
        keystore.add_key("Test User", pem)

        keys = keystore.list_keys()

        assert len(keys) == 1

    def test_keystore_get_key_with_prefix(self, ledger_path):
        """Should support prefix match for get_key."""
        keystore = KeyStore(ledger_path)

        # Add a key
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_manager.generate_keypair(
            Identity(name="Other User", machine="other-machine")
        )
        pem = other_manager.export_public_key()
        trusted_key = keystore.add_key("Test User", pem)

        # Get by prefix (first 3 chars)
        prefix = trusted_key.key_id[:3].lower()
        retrieved = keystore.get_key(prefix)

        assert retrieved is not None
        assert retrieved.key_id == trusted_key.key_id


class TestKeyManagerIntegration:
    """Integration tests for KeyManager."""

    def test_full_workflow_generate_sign_trust_verify(self, ledger_path):
        """Full workflow: generate keypair, sign, add trusted, verify."""
        # Setup two ledgers
        ledger_a_path = ledger_path / "ledger_a"
        ledger_b_path = ledger_path / "ledger_b"
        ledger_a_path.mkdir()
        ledger_b_path.mkdir()

        manager_a = KeyManager(ledger_a_path)
        manager_b = KeyManager(ledger_b_path)

        # Generate keypairs
        keypair_a = manager_a.generate_keypair(
            Identity(name="User A", machine="machine-a")
        )
        keypair_b = manager_b.generate_keypair(
            Identity(name="User B", machine="machine-b")
        )

        # Sign data with A's key
        data = "message from A to B"
        signature = manager_a.sign(data)

        # B adds A's key as trusted
        pem_a = manager_a.export_public_key()
        manager_b.import_public_key(
            pem_a,
            Identity(name="User A (trusted)", machine="machine-a"),
            trust_level=TrustLevel.FULL
        )

        # B verifies A's signature
        result = manager_b.verify(data, signature, keypair_a.key_id)

        assert result == VerifyResult.VALID

    def test_export_import_roundtrip(self, ledger_path):
        """Export PEM and import it as trusted key."""
        # Create source keypair
        source_path = ledger_path / "source"
        source_path.mkdir()
        source_manager = KeyManager(source_path)
        source_keypair = source_manager.generate_keypair(
            Identity(name="Source", machine="source-machine")
        )

        # Export public key
        pem = source_manager.export_public_key()

        # Import in another ledger
        target_path = ledger_path / "target"
        target_path.mkdir()
        target_manager = KeyManager(target_path)
        imported_key = target_manager.import_public_key(
            pem,
            Identity(name="Imported Source", machine="source-machine")
        )

        # Key IDs should match
        assert imported_key.key_id == source_keypair.key_id


class TestBlockSigning:
    """Tests for block signing functions."""

    def test_sign_block_hash(self, ledger_path):
        """Should sign block hash and return signature data."""
        manager = KeyManager(ledger_path)
        keypair = manager.generate_keypair(
            Identity(name="Test", machine="test-machine")
        )

        block_hash = "abc123def456789"
        result = sign_block_hash(block_hash, manager)

        assert result is not None
        assert "author_key_id" in result
        assert "signature" in result
        assert result["author_key_id"] == keypair.key_id

    def test_sign_block_hash_returns_none_without_keypair(self, ledger_path):
        """Should return None when no keypair is configured."""
        manager = KeyManager(ledger_path)

        block_hash = "abc123def456789"
        result = sign_block_hash(block_hash, manager)

        assert result is None

    def test_verify_block_signature(self, ledger_path):
        """Should verify a signed block successfully."""
        manager = KeyManager(ledger_path)
        keypair = manager.generate_keypair(
            Identity(name="Test", machine="test-machine")
        )

        block_hash = "abc123def456789"
        signature_data = sign_block_hash(block_hash, manager)

        block = {
            "hash": block_hash,
            "signature": signature_data,
        }

        result = verify_block_signature(block, manager)

        assert result == VerifyResult.VALID

    def test_unsigned_block_returns_unsigned(self, ledger_path):
        """Should return UNSIGNED for block without signature."""
        manager = KeyManager(ledger_path)
        manager.generate_keypair(
            Identity(name="Test", machine="test-machine")
        )

        block = {
            "hash": "abc123def456789",
        }

        result = verify_block_signature(block, manager)

        assert result == VerifyResult.UNSIGNED


class TestUntrustedKey:
    """Tests for untrusted key behavior."""

    def test_verify_with_untrusted_key_returns_untrusted(self, ledger_path):
        """Should return UNTRUSTED for keys with trust level NONE."""
        manager = KeyManager(ledger_path)
        manager.generate_keypair(Identity(name="Local", machine="local-machine"))

        # Create and sign with another keypair
        other_ledger = ledger_path.parent / "other_ledger"
        other_ledger.mkdir()
        other_manager = KeyManager(other_ledger)
        other_keypair = other_manager.generate_keypair(
            Identity(name="Other", machine="other-machine")
        )

        data = "test data"
        signature = other_manager.sign(data)

        # Add other's key as untrusted
        pem = other_manager.export_public_key()
        manager.import_public_key(
            pem,
            Identity(name="Untrusted", machine="other-machine"),
            trust_level=TrustLevel.NONE
        )

        result = manager.verify(data, signature, other_keypair.key_id)

        assert result == VerifyResult.UNTRUSTED


class TestHelperFunctions:
    """Tests for helper/compatibility functions."""

    def test_get_identity_path(self, ledger_path):
        """Should return correct identity.json path."""
        path = get_identity_path(ledger_path)
        assert path == ledger_path / "identity.json"

    def test_get_keystore_path(self, ledger_path):
        """Should return correct trusted_keys.json path."""
        path = get_keystore_path(ledger_path)
        assert path == ledger_path / "trusted_keys.json"

    def test_load_identity_for_ledger(self, ledger_path):
        """Should load identity from ledger."""
        manager = KeyManager(ledger_path)
        manager.generate_keypair(
            Identity(name="Test User", machine="test-machine", email="test@example.com")
        )

        identity = load_identity_for_ledger(ledger_path)

        assert identity is not None
        assert identity.name == "Test User"
        assert identity.machine == "test-machine"
        assert identity.email == "test@example.com"

    def test_load_identity_for_ledger_returns_none_when_missing(self, ledger_path):
        """Should return None when identity.json doesn't exist."""
        identity = load_identity_for_ledger(ledger_path)
        assert identity is None

    def test_load_keystore_for_ledger(self, ledger_path):
        """Should return KeyStore instance for ledger."""
        keystore = load_keystore_for_ledger(ledger_path)
        assert isinstance(keystore, KeyStore)


class TestGracefulDegradation:
    """Tests for graceful degradation when cryptography is not installed."""

    def test_is_crypto_available_returns_correct_value(self):
        """Should correctly report crypto availability."""
        # Since we skip if crypto is not available, this should be True
        assert is_crypto_available() is True

    @pytest.mark.skipif(
        not CRYPTO_AVAILABLE,
        reason="This test requires cryptography to be installed"
    )
    def test_mocked_crypto_unavailable_sign(self, ledger_path):
        """Sign should raise RuntimeError when crypto unavailable."""
        manager = KeyManager(ledger_path)

        with patch("continuous_claude.ledger.crypto.CRYPTO_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="cryptography package not installed"):
                manager.sign("test data")

    @pytest.mark.skipif(
        not CRYPTO_AVAILABLE,
        reason="This test requires cryptography to be installed"
    )
    def test_mocked_crypto_unavailable_generate(self, ledger_path):
        """Generate keypair should raise RuntimeError when crypto unavailable."""
        manager = KeyManager(ledger_path)
        identity = Identity(name="Test", machine="test")

        with patch("continuous_claude.ledger.crypto.CRYPTO_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="cryptography package not installed"):
                manager.generate_keypair(identity)

    @pytest.mark.skipif(
        not CRYPTO_AVAILABLE,
        reason="This test requires cryptography to be installed"
    )
    def test_mocked_crypto_unavailable_verify(self, ledger_path):
        """Verify should return UNSIGNED when crypto unavailable."""
        manager = KeyManager(ledger_path)

        with patch("continuous_claude.ledger.crypto.CRYPTO_AVAILABLE", False):
            result = manager.verify("data", "sig", "key_id")
            assert result == VerifyResult.UNSIGNED

    @pytest.mark.skipif(
        not CRYPTO_AVAILABLE,
        reason="This test requires cryptography to be installed"
    )
    def test_mocked_crypto_unavailable_sign_block(self, ledger_path):
        """sign_block_hash should return None when crypto unavailable."""
        manager = KeyManager(ledger_path)

        with patch("continuous_claude.ledger.crypto.CRYPTO_AVAILABLE", False):
            result = sign_block_hash("hash", manager)
            assert result is None

    @pytest.mark.skipif(
        not CRYPTO_AVAILABLE,
        reason="This test requires cryptography to be installed"
    )
    def test_mocked_crypto_unavailable_verify_block(self, ledger_path):
        """verify_block_signature should return UNSIGNED when crypto unavailable."""
        manager = KeyManager(ledger_path)

        block = {"hash": "abc", "signature": {"author_key_id": "KEY", "signature": "sig"}}

        with patch("continuous_claude.ledger.crypto.CRYPTO_AVAILABLE", False):
            result = verify_block_signature(block, manager)
            assert result == VerifyResult.UNSIGNED


class TestTrustedKeyDataclass:
    """Tests for TrustedKey dataclass."""

    def test_trusted_key_to_dict(self, ledger_path):
        """Should serialize TrustedKey to dictionary."""
        key = TrustedKey(
            key_id="ABC123",
            public_key=b"public_key_bytes",
            identity=Identity(name="Test", machine="test"),
            trust_level=TrustLevel.FULL,
            vouched_by=["DEF456"],
        )

        data = key.to_dict()

        assert data["key_id"] == "ABC123"
        assert data["trust_level"] == "full"
        assert data["vouched_by"] == ["DEF456"]
        assert "public_key" in data
        assert "identity" in data

    def test_trusted_key_from_dict(self):
        """Should deserialize TrustedKey from dictionary."""
        import base64
        from datetime import datetime, timezone

        data = {
            "key_id": "ABC123",
            "public_key": base64.b64encode(b"public_key_bytes").decode(),
            "identity": {"name": "Test", "machine": "test", "email": None},
            "trust_level": "marginal",
            "added_at": "2024-01-15T10:30:00+00:00",
            "vouched_by": ["DEF456"],
        }

        key = TrustedKey.from_dict(data)

        assert key.key_id == "ABC123"
        assert key.public_key == b"public_key_bytes"
        assert key.identity.name == "Test"
        assert key.trust_level == TrustLevel.MARGINAL
        assert key.vouched_by == ["DEF456"]


class TestVerifyResult:
    """Tests for VerifyResult enum."""

    def test_verify_result_values(self):
        """Should have all expected verification result values."""
        assert VerifyResult.VALID.value == "valid"
        assert VerifyResult.INVALID_SIGNATURE.value == "invalid_signature"
        assert VerifyResult.UNKNOWN_KEY.value == "unknown_key"
        assert VerifyResult.UNTRUSTED.value == "untrusted"
        assert VerifyResult.UNSIGNED.value == "unsigned"


class TestTrustLevel:
    """Tests for TrustLevel enum."""

    def test_trust_level_values(self):
        """Should have all expected trust level values."""
        assert TrustLevel.FULL.value == "full"
        assert TrustLevel.MARGINAL.value == "marginal"
        assert TrustLevel.NONE.value == "none"
