"""Integration tests for database backup system.

Tests the complete backup workflow:
- Creating compressed backups
- Automatic rotation (keeping last 7)
- Listing backups with metadata
- Restoring from backup
- Backup size validation
"""
from __future__ import annotations

import asyncio
import gzip
import sqlite3
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from rot.storage.backup import BackupManager
from rot.storage.database import Database


@pytest.mark.asyncio
async def test_create_backup_with_compression():
    """Test creating a compressed database backup."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create a test database with some data
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER, data TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'test data')")
        conn.commit()
        conn.close()

        # Create backup
        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))
        backup_file = await manager.create_backup()

        assert backup_file is not None
        assert backup_file.exists()
        assert backup_file.suffix == ".gz"
        assert backup_file.name.startswith("rot_backup_")

        # Verify it's actually gzip compressed
        with gzip.open(backup_file, "rb") as f:
            content = f.read()
            assert b"SQLite format" in content
            assert b"test data" in content


@pytest.mark.asyncio
async def test_backup_rotation_keeps_last_7():
    """Test that old backups are automatically cleaned up."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create minimal database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))

        # Create 10 backups
        for i in range(10):
            await manager.create_backup()
            await asyncio.sleep(0.01)  # Ensure different timestamps

        # Should only keep last 7
        backups = list(backup_dir.glob("*.gz"))
        assert len(backups) == 7


@pytest.mark.asyncio
async def test_list_backups_with_metadata():
    """Test listing backups returns correct metadata."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))

        # Create backups
        await manager.create_backup()
        await asyncio.sleep(0.1)
        await manager.create_backup()

        # List backups
        backups = await manager.list_backups()

        assert len(backups) == 2
        assert all("filename" in b for b in backups)
        assert all("size_mb" in b for b in backups)
        assert all("age_hours" in b for b in backups)
        assert all("created_at" in b for b in backups)

        # Should be sorted newest first
        assert backups[0]["age_hours"] < backups[1]["age_hours"]

        # Sizes should be reasonable (compressed SQLite DB)
        for backup in backups:
            assert backup["size_mb"] > 0
            assert backup["size_mb"] < 100  # Shouldn't be huge for empty DB


@pytest.mark.asyncio
async def test_restore_backup():
    """Test restoring database from backup."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        restore_path = Path(tmpdir) / "restored.db"
        backup_dir.mkdir()

        # Create database with data
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        conn.commit()
        conn.close()

        # Create backup
        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))
        backup_file = await manager.create_backup()

        # Restore to new location
        await manager.restore_backup(backup_file, str(restore_path))

        # Verify restored data
        conn = sqlite3.connect(str(restore_path))
        cursor = conn.execute("SELECT * FROM users ORDER BY id")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0] == (1, "Alice")
        assert rows[1] == (2, "Bob")


@pytest.mark.asyncio
async def test_backup_compression_reduces_size():
    """Test that GZip compression actually reduces file size."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create database with compressible data
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE data (id INTEGER, text TEXT)")
        # Insert repetitive data (compresses well)
        for i in range(1000):
            conn.execute("INSERT INTO data VALUES (?, ?)", (i, "test data" * 10))
        conn.commit()
        conn.close()

        original_size = db_path.stat().st_size

        # Create compressed backup
        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))
        backup_file = await manager.create_backup()
        compressed_size = backup_file.stat().st_size

        # Compression should reduce size significantly
        compression_ratio = compressed_size / original_size
        assert compression_ratio < 0.5  # At least 50% reduction


@pytest.mark.asyncio
async def test_backup_empty_database():
    """Test backing up an empty database."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "empty.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create empty database
        conn = sqlite3.connect(str(db_path))
        conn.close()

        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))
        backup_file = await manager.create_backup()

        assert backup_file is not None
        assert backup_file.exists()

        # Should still be valid gzip
        with gzip.open(backup_file, "rb") as f:
            content = f.read()
            assert len(content) > 0


@pytest.mark.asyncio
async def test_backup_with_real_schema():
    """Test backup of database with ROT schema."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rot.db"
        backup_dir = Path(tmpdir) / "backups"

        # Create database with ROT schema
        db = Database(str(tmpdir))
        await db.connect()

        # Insert some test signals
        await db.store_signal(
            ticker="AAPL",
            stance="bullish",
            confidence=0.8,
            event_type="earnings_beat",
            post_id="test123",
            subreddit="wallstreetbets",
            post_title="AAPL to the moon",
            reasoning="Strong earnings",
        )

        await db.close()

        # Create backup
        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))
        backup_file = await manager.create_backup()

        assert backup_file is not None

        # Restore and verify
        restored_path = Path(tmpdir) / "restored.db"
        await manager.restore_backup(backup_file, str(restored_path))

        # Reconnect to restored DB
        restored_db = Database(str(tmpdir))
        restored_db.db_path = str(restored_path)
        await restored_db.connect()

        # Verify signal was restored
        signal_count = await restored_db.get_signal_count()
        assert signal_count >= 1

        await restored_db.close()


@pytest.mark.asyncio
async def test_cleanup_old_backups_by_age():
    """Test that cleanup removes backups older than keep_last."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir), keep_last=3)

        # Create 5 backups
        for _ in range(5):
            await manager.create_backup()
            await asyncio.sleep(0.01)

        # Should only keep 3
        backups = list(backup_dir.glob("*.gz"))
        assert len(backups) == 3

        # Verify newest ones were kept
        listed_backups = await manager.list_backups()
        assert len(listed_backups) == 3
        # All should be recent (< 1 hour old)
        assert all(b["age_hours"] < 1 for b in listed_backups)


@pytest.mark.asyncio
async def test_concurrent_backup_creation():
    """Test that concurrent backup creation works correctly."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))

        # Create multiple backups concurrently
        tasks = [manager.create_backup() for _ in range(3)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r is not None for r in results)
        assert all(r.exists() for r in results)

        # All should have unique filenames (due to timestamps)
        filenames = [r.name for r in results]
        assert len(set(filenames)) == len(filenames)


@pytest.mark.asyncio
async def test_backup_filename_format():
    """Test that backup filenames follow expected format."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        backup_dir = Path(tmpdir) / "backups"
        backup_dir.mkdir()

        # Create database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        manager = BackupManager(db_path=str(db_path), backup_dir=str(backup_dir))
        backup_file = await manager.create_backup()

        # Filename should be: rot_backup_YYYYMMDD_HHMMSS.db.gz
        assert backup_file.name.startswith("rot_backup_")
        assert backup_file.name.endswith(".db.gz")

        # Extract timestamp portion
        timestamp_part = backup_file.name.replace("rot_backup_", "").replace(".db.gz", "")
        # Should be YYYYMMDD_HHMMSS format (15 characters)
        assert len(timestamp_part) == 15
        assert timestamp_part[8] == "_"  # Separator between date and time
