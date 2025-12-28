"""Pytest fixtures for continuous-claude-custom tests."""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests.

    Yields the path and cleans up after the test.
    """
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def ledger_path(temp_dir):
    """Create a ledger directory path within the temp directory."""
    path = temp_dir / "ledger"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def project_dir(temp_dir):
    """Create a project directory path within the temp directory."""
    path = temp_dir / "project"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def search_db_path(temp_dir):
    """Create a path for the search database."""
    cache_dir = temp_dir / "cache"
    cache_dir.mkdir(parents=True)
    return cache_dir / "search.db"
