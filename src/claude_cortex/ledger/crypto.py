"""Cryptographic utilities for block signing and verification."""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
import json
import hashlib
import base64
import os

# Check if cryptography package is available
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def is_crypto_available() -> bool:
    """Check if cryptographic signing is available.

    Returns:
        True if the cryptography package is installed
    """
    return CRYPTO_AVAILABLE


class TrustLevel(Enum):
    """Trust levels for keys."""
    FULL = "full"
    MARGINAL = "marginal"
    NONE = "none"


class VerifyResult(Enum):
    """Result of signature verification."""
    VALID = "valid"
    INVALID_SIGNATURE = "invalid_signature"
    UNKNOWN_KEY = "unknown_key"
    UNTRUSTED = "untrusted"
    UNSIGNED = "unsigned"


@dataclass
class Identity:
    """Information about a key owner."""
    name: str
    machine: str
    email: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "machine": self.machine,
            "email": self.email,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Identity":
        """Create Identity from dictionary."""
        return cls(
            name=data["name"],
            machine=data["machine"],
            email=data.get("email"),
        )


@dataclass
class KeyPair:
    """A public/private key pair."""
    public_key: bytes
    private_key: bytes
    key_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TrustedKey:
    """A trusted public key with metadata."""
    key_id: str
    public_key: bytes
    identity: Identity
    trust_level: TrustLevel = TrustLevel.FULL
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    vouched_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "key_id": self.key_id,
            "public_key": base64.b64encode(self.public_key).decode("ascii"),
            "identity": self.identity.to_dict(),
            "trust_level": self.trust_level.value,
            "added_at": self.added_at.isoformat(),
            "vouched_by": self.vouched_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrustedKey":
        """Create TrustedKey from dictionary."""
        added_at = data.get("added_at")
        if isinstance(added_at, str):
            added_at = datetime.fromisoformat(added_at)
        else:
            added_at = datetime.now(timezone.utc)

        return cls(
            key_id=data["key_id"],
            public_key=base64.b64decode(data["public_key"]),
            identity=Identity.from_dict(data["identity"]),
            trust_level=TrustLevel(data.get("trust_level", "marginal")),
            added_at=added_at,
            vouched_by=data.get("vouched_by", []),
        )


def _compute_key_id(public_key_bytes: bytes) -> str:
    """Compute key ID from public key bytes.

    Key ID is first 6 characters of SHA-256 hash of public key, uppercase.

    Args:
        public_key_bytes: Raw public key bytes

    Returns:
        6-character uppercase key ID
    """
    return hashlib.sha256(public_key_bytes).hexdigest()[:6].upper()


class KeyManager:
    """
    Manages cryptographic keys for signing and verification.

    Files:
    - identity.json: This ledger's public key and identity
    - .private_key: This ledger's private key (mode 600)
    - trusted_keys.json: Other users' public keys
    """

    def __init__(self, ledger_path: Path):
        """Initialize key manager for a ledger.

        Args:
            ledger_path: Path to the ledger directory
        """
        self.path = ledger_path
        self.identity_file = ledger_path / "identity.json"
        self.private_key_file = ledger_path / ".private_key"
        self.trusted_keys_file = ledger_path / "trusted_keys.json"

    def generate_keypair(self, identity: Identity) -> KeyPair:
        """
        Generate a new Ed25519 keypair for signing.
        Saves public key to identity.json and private key to .private_key

        Args:
            identity: Identity information for the key owner

        Returns:
            The generated KeyPair

        Raises:
            RuntimeError: If cryptography package is not available
            FileExistsError: If a keypair already exists
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "cryptography package not installed. "
                "Install with: uv add cryptography"
            )

        if self.has_keypair():
            raise FileExistsError(
                f"Keypair already exists at {self.identity_file}. "
                "Remove existing keys before generating new ones."
            )

        # Generate Ed25519 keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Get raw bytes
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        # Compute key ID
        key_id = _compute_key_id(public_bytes)
        created_at = datetime.now(timezone.utc)

        # Ensure ledger directory exists
        self.path.mkdir(parents=True, exist_ok=True)

        # Save identity.json with public key and identity
        identity_data = {
            "key_id": key_id,
            "public_key": base64.b64encode(public_bytes).decode("ascii"),
            "identity": identity.to_dict(),
            "created_at": created_at.isoformat(),
        }
        with open(self.identity_file, "w") as f:
            json.dump(identity_data, f, indent=2)

        # Save private key with restricted permissions (600)
        with open(self.private_key_file, "wb") as f:
            f.write(private_bytes)
        os.chmod(self.private_key_file, 0o600)

        return KeyPair(
            public_key=public_bytes,
            private_key=private_bytes,
            key_id=key_id,
            created_at=created_at,
        )

    def has_keypair(self) -> bool:
        """Check if this ledger has a keypair configured.

        Returns:
            True if both identity.json and .private_key exist
        """
        return self.identity_file.exists() and self.private_key_file.exists()

    def has_identity(self) -> bool:
        """Alias for has_keypair() for API compatibility.

        Returns:
            True if a keypair is configured for signing
        """
        return self.has_keypair()

    def get_public_key(self) -> Optional[bytes]:
        """Get this ledger's public key.

        Returns:
            Raw public key bytes, or None if not configured
        """
        if not self.identity_file.exists():
            return None

        try:
            with open(self.identity_file) as f:
                data = json.load(f)
            return base64.b64decode(data["public_key"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def get_key_id(self) -> Optional[str]:
        """Get this ledger's key ID.

        Returns:
            Key ID string, or None if not configured
        """
        if not self.identity_file.exists():
            return None

        try:
            with open(self.identity_file) as f:
                data = json.load(f)
            return data.get("key_id")
        except (json.JSONDecodeError, KeyError):
            return None

    def _load_private_key(self) -> Optional[bytes]:
        """Load private key from file.

        Returns:
            Raw private key bytes, or None if not available
        """
        if not self.private_key_file.exists():
            return None

        try:
            with open(self.private_key_file, "rb") as f:
                return f.read()
        except (IOError, OSError):
            return None

    def sign(self, data: str) -> str:
        """Sign data with private key.

        Args:
            data: String data to sign

        Returns:
            Base64-encoded signature

        Raises:
            RuntimeError: If cryptography not available or no keypair configured
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "cryptography package not installed. "
                "Install with: uv add cryptography"
            )

        private_bytes = self._load_private_key()
        if private_bytes is None:
            raise RuntimeError(
                "No private key configured. "
                "Generate a keypair first with generate_keypair()"
            )

        # Reconstruct private key from raw bytes
        private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)

        # Sign the data
        signature = private_key.sign(data.encode("utf-8"))

        return base64.b64encode(signature).decode("ascii")

    def verify(self, data: str, signature: str, key_id: str) -> VerifyResult:
        """Verify a signature against a trusted key.

        Args:
            data: The original data that was signed
            signature: Base64-encoded signature
            key_id: Key ID to verify against

        Returns:
            VerifyResult indicating verification status
        """
        if not CRYPTO_AVAILABLE:
            # Without cryptography, we cannot verify signatures
            return VerifyResult.UNSIGNED

        # Check if it's our own key
        our_key_id = self.get_key_id()
        if our_key_id and our_key_id == key_id:
            public_bytes = self.get_public_key()
            if public_bytes:
                return self._verify_with_key(data, signature, public_bytes)

        # Look up in trusted keys
        trusted_key = self.get_trusted_key(key_id)
        if trusted_key is None:
            return VerifyResult.UNKNOWN_KEY

        # Check trust level
        if trusted_key.trust_level == TrustLevel.NONE:
            return VerifyResult.UNTRUSTED

        return self._verify_with_key(data, signature, trusted_key.public_key)

    def _verify_with_key(
        self, data: str, signature: str, public_key_bytes: bytes
    ) -> VerifyResult:
        """Verify signature with a specific public key.

        Args:
            data: Original data
            signature: Base64-encoded signature
            public_key_bytes: Raw public key bytes

        Returns:
            VerifyResult.VALID or VerifyResult.INVALID_SIGNATURE
        """
        try:
            sig_bytes = base64.b64decode(signature)
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            public_key.verify(sig_bytes, data.encode("utf-8"))
            return VerifyResult.VALID
        except InvalidSignature:
            return VerifyResult.INVALID_SIGNATURE
        except (ValueError, TypeError):
            return VerifyResult.INVALID_SIGNATURE

    def _load_trusted_keys(self) -> dict:
        """Load trusted keys from file.

        Returns:
            Dictionary with trusted keys data
        """
        if not self.trusted_keys_file.exists():
            return {"keys": {}}

        try:
            with open(self.trusted_keys_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"keys": {}}

    def _save_trusted_keys(self, data: dict) -> None:
        """Save trusted keys to file.

        Args:
            data: Trusted keys data dictionary
        """
        self.path.mkdir(parents=True, exist_ok=True)
        with open(self.trusted_keys_file, "w") as f:
            json.dump(data, f, indent=2)

    def add_trusted_key(self, key: TrustedKey) -> None:
        """Add a key to trusted_keys.json.

        Args:
            key: TrustedKey to add
        """
        data = self._load_trusted_keys()
        data["keys"][key.key_id] = key.to_dict()
        self._save_trusted_keys(data)

    def remove_trusted_key(self, key_id: str) -> bool:
        """Remove a trusted key.

        Args:
            key_id: Key ID to remove

        Returns:
            True if key was found and removed, False otherwise
        """
        data = self._load_trusted_keys()
        if key_id in data.get("keys", {}):
            del data["keys"][key_id]
            self._save_trusted_keys(data)
            return True
        return False

    def get_trusted_key(self, key_id: str) -> Optional[TrustedKey]:
        """Get a trusted key by ID.

        Args:
            key_id: Key ID to look up

        Returns:
            TrustedKey if found, None otherwise
        """
        data = self._load_trusted_keys()
        key_data = data.get("keys", {}).get(key_id)
        if key_data:
            return TrustedKey.from_dict(key_data)
        return None

    def list_trusted_keys(self) -> list[TrustedKey]:
        """List all trusted keys.

        Returns:
            List of all TrustedKey objects
        """
        data = self._load_trusted_keys()
        return [
            TrustedKey.from_dict(key_data)
            for key_data in data.get("keys", {}).values()
        ]

    def set_trust_level(self, key_id: str, level: TrustLevel) -> bool:
        """Update trust level for a key.

        Args:
            key_id: Key ID to update
            level: New trust level

        Returns:
            True if key was found and updated, False otherwise
        """
        data = self._load_trusted_keys()
        if key_id in data.get("keys", {}):
            data["keys"][key_id]["trust_level"] = level.value
            self._save_trusted_keys(data)
            return True
        return False

    def export_public_key(self) -> str:
        """Export public key in PEM format for sharing.

        Returns:
            PEM-encoded public key string

        Raises:
            RuntimeError: If cryptography not available or no keypair configured
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "cryptography package not installed. "
                "Install with: uv add cryptography"
            )

        public_bytes = self.get_public_key()
        if public_bytes is None:
            raise RuntimeError(
                "No public key configured. "
                "Generate a keypair first with generate_keypair()"
            )

        # Reconstruct public key object and serialize to PEM
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem.decode("ascii")

    def import_public_key(
        self,
        pem_data: str,
        identity: Identity,
        trust_level: TrustLevel = TrustLevel.MARGINAL,
    ) -> TrustedKey:
        """Import a public key from PEM format.

        Args:
            pem_data: PEM-encoded public key
            identity: Identity information for the key owner
            trust_level: Initial trust level for the key

        Returns:
            The created TrustedKey

        Raises:
            RuntimeError: If cryptography not available
            ValueError: If PEM data is invalid
        """
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "cryptography package not installed. "
                "Install with: uv add cryptography"
            )

        try:
            # Load public key from PEM
            public_key = serialization.load_pem_public_key(pem_data.encode("ascii"))
            if not isinstance(public_key, Ed25519PublicKey):
                raise ValueError("Key must be Ed25519")

            # Get raw bytes
            public_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        except Exception as e:
            raise ValueError(f"Invalid PEM data: {e}") from e

        # Compute key ID
        key_id = _compute_key_id(public_bytes)

        # Create trusted key
        trusted_key = TrustedKey(
            key_id=key_id,
            public_key=public_bytes,
            identity=identity,
            trust_level=trust_level,
        )

        # Save to trusted keys
        self.add_trusted_key(trusted_key)

        return trusted_key

    def sign_block_hash(self, block_hash: str) -> Optional[tuple[str, str]]:
        """Sign a block hash with the private key.

        This method is used by the Ledger class for block signing.

        Args:
            block_hash: The hex-encoded block hash to sign

        Returns:
            Tuple of (key_id, base64_signature) if successful, None otherwise
        """
        if not CRYPTO_AVAILABLE:
            return None

        if not self.has_keypair():
            return None

        try:
            signature = self.sign(block_hash)
            key_id = self.get_key_id()
            if key_id is None:
                return None
            return (key_id, signature)
        except RuntimeError:
            return None

    def verify_signature(
        self,
        block_hash: str,
        key_id: str,
        signature: str,
    ) -> VerifyResult:
        """Verify a block signature.

        This method is used by the Ledger class for signature verification.

        Args:
            block_hash: The hex-encoded block hash that was signed
            key_id: The ID of the key that signed the block
            signature: Base64-encoded signature

        Returns:
            VerifyResult indicating the outcome
        """
        return self.verify(block_hash, signature, key_id)


def sign_block_hash(block_hash: str, key_manager: KeyManager) -> Optional[dict]:
    """
    Sign a block hash. Returns signature data to include in block.

    Args:
        block_hash: The block's hash to sign
        key_manager: KeyManager with the signing keypair

    Returns:
        Dictionary with signature data:
        {
            "author_key_id": "ABC123",
            "signature": "base64-signature..."
        }
        Returns None if signing is not available (no keypair or no crypto)
    """
    if not CRYPTO_AVAILABLE:
        return None

    if not key_manager.has_keypair():
        return None

    try:
        signature = key_manager.sign(block_hash)
        key_id = key_manager.get_key_id()

        return {
            "author_key_id": key_id,
            "signature": signature,
        }
    except RuntimeError:
        return None


def verify_block_signature(block: dict, key_manager: KeyManager) -> VerifyResult:
    """Verify a block's signature.

    Args:
        block: Block dictionary (must have "hash" field, optionally "signature" dict)
        key_manager: KeyManager with trusted keys

    Returns:
        VerifyResult indicating verification status
    """
    if not CRYPTO_AVAILABLE:
        return VerifyResult.UNSIGNED

    # Check if block has signature
    signature_data = block.get("signature")
    if not signature_data:
        return VerifyResult.UNSIGNED

    author_key_id = signature_data.get("author_key_id")
    signature = signature_data.get("signature")
    block_hash = block.get("hash")

    if not all([author_key_id, signature, block_hash]):
        return VerifyResult.UNSIGNED

    return key_manager.verify(block_hash, signature, author_key_id)


# Compatibility functions for CLI and other code
def get_identity_path(ledger_path: Path) -> Path:
    """Get the path to identity.json for a ledger.

    Args:
        ledger_path: Path to the ledger directory

    Returns:
        Path to the identity.json file
    """
    return ledger_path / "identity.json"


def get_keystore_path(ledger_path: Path) -> Path:
    """Get the path to trusted_keys.json for a ledger.

    Args:
        ledger_path: Path to the ledger directory

    Returns:
        Path to the trusted_keys.json file
    """
    return ledger_path / "trusted_keys.json"


def load_identity_for_ledger(ledger_path: Path) -> Optional[Identity]:
    """Load identity for a ledger from identity.json.

    Args:
        ledger_path: Path to the ledger directory

    Returns:
        Identity if configured, None otherwise
    """
    identity_file = get_identity_path(ledger_path)
    if not identity_file.exists():
        return None

    try:
        with open(identity_file) as f:
            data = json.load(f)
        identity_data = data.get("identity", {})
        return Identity.from_dict(identity_data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


class KeyStore:
    """Compatibility class wrapping KeyManager for trusted key operations."""

    def __init__(self, ledger_path: Path):
        """Initialize keystore for a ledger.

        Args:
            ledger_path: Path to the ledger directory
        """
        self._key_manager = KeyManager(ledger_path)
        self._path = ledger_path

    @property
    def trusted_keys(self) -> dict[str, TrustedKey]:
        """Get all trusted keys as a dictionary."""
        keys = self._key_manager.list_trusted_keys()
        return {k.key_id: k for k in keys}

    def add_key(
        self,
        name: str,
        public_key_pem: str,
        trust_level: TrustLevel = TrustLevel.MARGINAL,
        vouched_by: Optional[str] = None,
    ) -> TrustedKey:
        """Add a trusted public key.

        Args:
            name: Name of the key owner
            public_key_pem: PEM-encoded public key
            trust_level: Trust level for this key
            vouched_by: Key ID that vouched for this key

        Returns:
            The created TrustedKey
        """
        identity = Identity(name=name, machine="imported")
        trusted_key = self._key_manager.import_public_key(
            public_key_pem, identity, trust_level
        )
        if vouched_by:
            # Update vouched_by in the stored key
            data = self._key_manager._load_trusted_keys()
            if trusted_key.key_id in data.get("keys", {}):
                if "vouched_by" not in data["keys"][trusted_key.key_id]:
                    data["keys"][trusted_key.key_id]["vouched_by"] = []
                data["keys"][trusted_key.key_id]["vouched_by"].append(vouched_by)
                self._key_manager._save_trusted_keys(data)
        return trusted_key

    def get_key(self, key_id: str) -> Optional[TrustedKey]:
        """Get a trusted key by ID (supports prefix match).

        Args:
            key_id: Full key ID or prefix

        Returns:
            TrustedKey or None if not found
        """
        # Exact match first
        key = self._key_manager.get_trusted_key(key_id)
        if key:
            return key

        # Try prefix match
        all_keys = self._key_manager.list_trusted_keys()
        key_id_lower = key_id.lower()
        matches = [k for k in all_keys if k.key_id.lower().startswith(key_id_lower)]

        if len(matches) == 1:
            return matches[0]

        return None

    def remove_key(self, key_id: str) -> bool:
        """Remove a trusted key.

        Args:
            key_id: Key ID to remove

        Returns:
            True if key was removed, False if not found
        """
        key = self.get_key(key_id)
        if key:
            return self._key_manager.remove_trusted_key(key.key_id)
        return False

    def list_keys(self) -> list[TrustedKey]:
        """List all trusted keys.

        Returns:
            List of TrustedKey instances
        """
        return self._key_manager.list_trusted_keys()

    def save(self, path: Path) -> None:
        """Save keystore to disk.

        Args:
            path: Path to save the keystore file (ignored, uses internal path)
        """
        # The KeyManager already saves on each operation
        pass

    @classmethod
    def load(cls, path: Path) -> "KeyStore":
        """Load keystore from disk.

        Args:
            path: Path to the keystore file

        Returns:
            KeyStore instance
        """
        # Extract ledger path from keystore path
        ledger_path = path.parent
        return cls(ledger_path)


def load_keystore_for_ledger(ledger_path: Path) -> KeyStore:
    """Load the keystore for a ledger.

    Args:
        ledger_path: Path to the ledger directory

    Returns:
        KeyStore instance
    """
    return KeyStore(ledger_path)
