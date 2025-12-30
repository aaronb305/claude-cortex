"""Ledger module for blockchain-style knowledge storage."""

from .models import Block, Learning, Outcome, LearningCategory, ProjectContext, OutcomeResult, compute_content_hash
from .chain import Ledger, file_lock
from .merkle import MerkleTree, MerkleNode
from .objects import ObjectStore
from .crypto import (
    Identity,
    TrustedKey,
    KeyPair,
    KeyManager,
    KeyStore,
    TrustLevel,
    VerifyResult,
    is_crypto_available,
    sign_block_hash,
    verify_block_signature,
    get_identity_path,
    get_keystore_path,
    load_identity_for_ledger,
    load_keystore_for_ledger,
)

__all__ = [
    "Block",
    "Learning",
    "Outcome",
    "OutcomeResult",
    "LearningCategory",
    "Ledger",
    "ProjectContext",
    "compute_content_hash",
    "file_lock",
    "MerkleTree",
    "MerkleNode",
    "ObjectStore",
    # Crypto/signing
    "Identity",
    "TrustedKey",
    "KeyPair",
    "KeyManager",
    "KeyStore",
    "TrustLevel",
    "VerifyResult",
    "is_crypto_available",
    "sign_block_hash",
    "verify_block_signature",
    "get_identity_path",
    "get_keystore_path",
    "load_identity_for_ledger",
    "load_keystore_for_ledger",
]
