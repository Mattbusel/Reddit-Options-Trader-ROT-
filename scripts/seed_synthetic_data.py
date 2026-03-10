#!/usr/bin/env python3
"""Seed the ROT SQLite database with 30 days of synthetic resolved outcome data.

Creates deterministic test data for:
- control_snapshots: 30 days of PID parameter snapshots
- attention_radar_events: 20 synthetic radar events with lead times
- pre_signal_events: 50 pre-signals with resolution data
- signals: 100 historical directional signals for radar resolver

Usage:
    python scripts/seed_synthetic_data.py [--db /path/to/rot.db]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import time
import sys

# Ensure src/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


TICKERS = ["TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOG", "AMD", "NFLX", "INTC"]
SOURCES = ["reddit", "sec_filing", "fda_release", "congressional", "rss"]
CATALYSTS = ["acquisition", "earnings_beat", "regulatory_approval", "product_news", "insider_buy"]


async def seed(db_path: str) -> None:
    import aiosqlite

    print(f"Seeding synthetic data into: {db_path}")
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

    async with aiosqlite.connect(db_path) as conn:
        now = time.time()
        day = 86400.0
        rng = random.Random(42)  # deterministic

        # ── 1. Create schema ────────────────────────────────────────────────
        await _create_schema(conn)

        # ── 2. Seed signals table ───────────────────────────────────────────
        print("  Seeding signals table (100 rows)...")
        for i in range(100):
            ts = now - rng.uniform(0, 30) * day
            ticker = rng.choice(TICKERS)
            stance = rng.choice(["bullish", "bearish"])
            confidence = rng.uniform(0.65, 0.97)
            event_type = rng.choice(["earnings_rumor", "product_news", "regulatory", "other"])
            await conn.execute(
                "INSERT OR IGNORE INTO signals (id, ticker, created_at, event_type, stance, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"sig_{i:04d}", ticker, ts, event_type, stance, round(confidence, 3)),
            )

        # ── 3. Seed control_snapshots ───────────────────────────────────────
        print("  Seeding control_snapshots (30 rows)...")
        for i in range(30):
            ts = now - (30 - i) * day
            values = {
                "sentiment_threshold": round(rng.uniform(-0.2, 0.2), 3),
                "confidence_floor": round(rng.uniform(0.0, 0.3), 3),
                "suppress_threshold": round(rng.uniform(0.15, 0.35), 3),
                "position_sizing_factor": round(rng.uniform(0.7, 1.5), 2),
                "iv_threshold": round(rng.uniform(0.1, 0.6), 2),
            }
            await conn.execute(
                "INSERT OR IGNORE INTO control_snapshots "
                "(snap_id, created_at, trigger, accuracy_at_snap, param_values) "
                "VALUES (?, ?, ?, ?, ?)",
                (i + 1, ts, "pid_adjustment",
                 round(rng.uniform(0.60, 0.88), 3), json.dumps(values)),
            )

        # ── 4. Seed attention_radar_events ──────────────────────────────────
        print("  Seeding attention_radar_events (20 rows)...")
        for i in range(20):
            fire_ts = now - rng.uniform(5, 30) * day
            ticker = rng.choice(TICKERS)
            confidence = round(rng.uniform(0.88, 0.98), 3)
            z_score = round(rng.uniform(2.1, 6.0), 2)
            resolved = i < 14  # 14 resolved, 6 pending
            catalyst = rng.choice(CATALYSTS) if resolved else None
            lead_days = round(rng.uniform(2.0, 18.0), 1) if resolved else None
            resolved_at = fire_ts + (lead_days * day) if resolved else None
            await conn.execute(
                "INSERT OR IGNORE INTO attention_radar_events "
                "(ticker, timestamp, confidence, signal_volume_zscore, event_type, stance, "
                " source_signal_id, eventual_catalyst, lead_time_days, resolved, resolved_at, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, fire_ts, confidence, z_score, "other",
                 rng.choice(["unknown", "mixed"]), f"sig_{rng.randint(0,99):04d}",
                 catalyst, lead_days, 1 if resolved else 0, resolved_at, "{}"),
            )

        # ── 5. Seed pre_signal_events ───────────────────────────────────────
        print("  Seeding pre_signal_events (50 rows)...")
        for i in range(50):
            ts = now - rng.uniform(0, 30) * day
            ticker = rng.choice(TICKERS)
            source = rng.choice(SOURCES)
            pre_conf = round(rng.uniform(0.72, 0.95), 3)
            pre_dir = rng.choice(["bullish", "bearish"])
            resolved = i < 40
            final_conf = round(pre_conf + rng.uniform(-0.1, 0.1), 3) if resolved else None
            final_dir = rng.choice(["bullish", "bearish"]) if resolved else None
            agreement = (pre_dir == final_dir) if resolved else None
            lead_ms = round(rng.uniform(50, 5000), 1) if resolved else None
            await conn.execute(
                "INSERT OR IGNORE INTO pre_signal_events "
                "(ticker, timestamp, source, doc_id, pre_signal_confidence, final_signal_confidence, "
                " pre_signal_direction, final_signal_direction, agreement, lead_time_ms, "
                " iir_value, variance, chunks_at_fire, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, ts, source, f"doc_{i:04d}", pre_conf, final_conf,
                 pre_dir, final_dir, (1 if agreement else 0) if agreement is not None else None,
                 lead_ms, round(rng.uniform(-0.5, 0.5), 3), round(rng.uniform(0, 0.1), 4),
                 rng.randint(5, 50), "{}"),
            )

        await conn.commit()

    print("Seeding complete.")
    print(f"  signals: 100 rows")
    print(f"  control_snapshots: 30 rows (30 days of PID history)")
    print(f"  attention_radar_events: 20 rows (14 resolved, 6 pending)")
    print(f"  pre_signal_events: 50 rows (40 resolved, 10 pending)")


async def _create_schema(conn) -> None:
    """Ensure all required tables exist."""
    from rot.storage.control_db import CONTROL_SCHEMA
    from rot.storage.radar_db import RADAR_SCHEMA
    from rot.storage.probability_db import PROBABILITY_SCHEMA

    # signals table (minimal version for seeding)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            created_at REAL NOT NULL,
            event_type TEXT,
            stance TEXT,
            confidence REAL
        )
    """)

    for schema in [CONTROL_SCHEMA, RADAR_SCHEMA, PROBABILITY_SCHEMA]:
        for stmt in schema.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)

    await conn.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed ROT synthetic data")
    parser.add_argument("--db", default=os.environ.get("ROT_DB_PATH", "storage/rot.db"))
    args = parser.parse_args()
    asyncio.run(seed(args.db))
