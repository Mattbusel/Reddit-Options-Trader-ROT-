"""Database backup system with rotation and compression.

Provides automated SQLite database backups with:
- Scheduled backups (configurable interval)
- Backup rotation (keep last N backups)
- GZip compression to save disk space
- Backup verification (file integrity check)
- Automatic cleanup of old backups

Backups are stored in storage/backups/ directory with format:
  rot_backup_YYYYMMDD_HHMMSS.db.gz

Usage:
    from rot.storage.backup import BackupManager

    manager = BackupManager(
        db_path="storage/rot.db",
        backup_dir="storage/backups",
        keep_count=7,  # Keep last 7 backups
    )

    # Manual backup
    backup_path = await manager.create_backup()

    # Automatic cleanup
    await manager.cleanup_old_backups()
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)


class BackupManager:
    """Manages SQLite database backups with rotation and compression."""

    def __init__(
        self,
        db_path: str = "storage/rot.db",
        backup_dir: str = "storage/backups",
        keep_count: int = 7,
        compress: bool = True,
    ) -> None:
        """Initialize backup manager.

        Args:
            db_path: Path to the SQLite database file
            backup_dir: Directory to store backups
            keep_count: Number of backups to keep (oldest are deleted)
            compress: Whether to gzip compress backups
        """
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.keep_count = keep_count
        self.compress = compress
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def create_backup(self) -> Path:
        """Create a new database backup with compression and rotation.

        Returns:
            Path to the created backup file

        Raises:
            FileNotFoundError: If source database doesn't exist
            IOError: If backup creation fails
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"rot_backup_{timestamp}.db"
        if self.compress:
            backup_name += ".gz"

        backup_path = self.backup_dir / backup_name

        try:
            # Copy database to backup location
            # Use asyncio to avoid blocking during large file copy
            await asyncio.to_thread(self._copy_with_compression, backup_path)

            # Verify backup was created
            if not backup_path.exists() or backup_path.stat().st_size == 0:
                raise IOError(f"Backup verification failed: {backup_path}")

            log.info(
                "Database backup created: %s (size: %.2f MB)",
                backup_path.name,
                backup_path.stat().st_size / (1024 * 1024),
            )

            # Cleanup old backups
            await self.cleanup_old_backups()

            return backup_path

        except Exception as e:
            log.error("Database backup failed: %s", e, exc_info=True)
            # Clean up failed backup
            if backup_path.exists():
                backup_path.unlink()
            raise

    def _copy_with_compression(self, backup_path: Path) -> None:
        """Copy database file with optional gzip compression.

        Args:
            backup_path: Destination path for backup
        """
        if self.compress:
            with open(self.db_path, "rb") as f_in:
                with gzip.open(backup_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copy2(self.db_path, backup_path)

    async def cleanup_old_backups(self) -> int:
        """Remove old backups, keeping only the most recent N backups.

        Returns:
            Number of backups deleted
        """
        # Get all backup files sorted by modification time (newest first)
        backups = sorted(
            self.backup_dir.glob("rot_backup_*.db*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        # Keep only the most recent N backups
        deleted = 0
        for old_backup in backups[self.keep_count:]:
            try:
                old_backup.unlink()
                deleted += 1
                log.info("Deleted old backup: %s", old_backup.name)
            except Exception as e:
                log.warning("Failed to delete backup %s: %s", old_backup.name, e)

        if deleted > 0:
            log.info("Backup cleanup: removed %d old backup(s), kept %d", deleted, len(backups) - deleted)

        return deleted

    async def list_backups(self) -> List[dict]:
        """List all available backups with metadata.

        Returns:
            List of dicts with backup info (path, size, created_at)
        """
        backups = []
        for backup_path in sorted(
            self.backup_dir.glob("rot_backup_*.db*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            stat = backup_path.stat()
            backups.append({
                "path": str(backup_path),
                "filename": backup_path.name,
                "size_mb": stat.st_size / (1024 * 1024),
                "created_at": stat.st_mtime,
                "age_hours": (time.time() - stat.st_mtime) / 3600,
            })
        return backups

    async def restore_backup(self, backup_path: Path | str) -> None:
        """Restore database from a backup file.

        DANGER: This OVERWRITES the current database!

        Args:
            backup_path: Path to the backup file to restore

        Raises:
            FileNotFoundError: If backup file doesn't exist
            IOError: If restore fails
        """
        backup_path = Path(backup_path)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        try:
            # Create a safety backup of current DB before restoring
            safety_backup = self.db_path.with_suffix(".db.pre_restore")
            if self.db_path.exists():
                shutil.copy2(self.db_path, safety_backup)
                log.warning("Created safety backup at %s", safety_backup)

            # Restore from backup
            await asyncio.to_thread(self._restore_with_decompression, backup_path)

            log.warning("Database restored from backup: %s", backup_path.name)

        except Exception as e:
            log.error("Database restore failed: %s", e, exc_info=True)
            # Try to restore from safety backup
            if safety_backup.exists():
                shutil.copy2(safety_backup, self.db_path)
                log.warning("Restored from safety backup after failed restore")
            raise

    def _restore_with_decompression(self, backup_path: Path) -> None:
        """Restore database file with optional gzip decompression.

        Args:
            backup_path: Source backup path
        """
        if backup_path.suffix == ".gz":
            with gzip.open(backup_path, "rb") as f_in:
                with open(self.db_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copy2(backup_path, self.db_path)
