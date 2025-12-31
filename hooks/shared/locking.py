#!/usr/bin/env python3
"""
File locking utilities using fcntl.
"""

import fcntl
import sys
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path, exclusive: bool = True):
    """Context manager for file locking using fcntl.

    Args:
        path: Path to the file to lock.
        exclusive: If True, acquire exclusive lock. Otherwise, shared lock.

    Yields:
        The file handle with the lock held.
    """
    # Use hidden lock file pattern (matches chain.py implementation)
    lock_path = path.parent / f".{path.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_file = open(lock_path, "w")
    try:
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        start = time.time()
        fcntl.flock(lock_file.fileno(), lock_type)
        elapsed = time.time() - start
        if elapsed > 1.0:
            print(f"[claude-cortex] Lock on {path} took {elapsed:.2f}s", file=sys.stderr)
        yield lock_file
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass  # Ignore unlock errors
        try:
            lock_file.close()
        except Exception:
            pass  # Ignore close errors


__all__ = ["file_lock"]
