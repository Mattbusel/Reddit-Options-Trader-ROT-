#!/usr/bin/env python3
"""
Manual migration script to add auth_attempts table.

Run this on the deployment if the table doesn't exist:
    python scripts/migrate_auth_attempts.py
"""
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rot.storage.database import Database


async def main():
    print("Checking for auth_attempts table...")

    db = Database("storage/rot.db")
    await db.connect()

    try:
        # Check if table exists
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auth_attempts'"
        )
        result = await cursor.fetchone()

        if result:
            print("✓ auth_attempts table already exists")
            cursor = await db._db.execute("SELECT COUNT(*) as count FROM auth_attempts")
            row = await cursor.fetchone()
            print(f"  Current entries: {row['count']}")
        else:
            print("✗ auth_attempts table NOT FOUND - creating now...")

            # Create table
            await db._db.execute("""
                CREATE TABLE IF NOT EXISTS auth_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    attempted_at REAL NOT NULL
                )
            """)

            # Create index
            await db._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup
                ON auth_attempts(ip_address, endpoint, attempted_at)
            """)

            await db._db.commit()
            print("✓ auth_attempts table created successfully")

        print("\nMigration complete!")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
