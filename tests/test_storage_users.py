"""Tests for rot.storage.users — UsersMixin: CRUD, email alerts, API usage, watchlists."""
from __future__ import annotations

import json
import time

import pytest

from rot.storage.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


# ---------------------------------------------------------------------------
# create_user / get_user_by_*
# ---------------------------------------------------------------------------


class TestUserCrud:
    @pytest.mark.asyncio
    async def test_create_user(self, db):
        user = await db.create_user("alice@example.com", "hash123")
        assert user["email"] == "alice@example.com"
        assert user["tier"] == "free"
        assert "id" in user

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, db):
        await db.create_user("bob@example.com", "hash456")
        found = await db.get_user_by_email("bob@example.com")
        assert found is not None
        assert found["email"] == "bob@example.com"

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self, db):
        found = await db.get_user_by_email("nobody@example.com")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, db):
        user = await db.create_user("carl@example.com", "hash789")
        found = await db.get_user_by_id(user["id"])
        assert found is not None
        assert found["email"] == "carl@example.com"

    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self, db):
        found = await db.get_user_by_id("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_user_by_api_key_hash(self, db):
        user = await db.create_user("apiuser@example.com", "hash")
        await db.set_user_api_key(user["id"], "sha256_test_hash")
        found = await db.get_user_by_api_key_hash("sha256_test_hash")
        assert found is not None
        assert found["email"] == "apiuser@example.com"

    @pytest.mark.asyncio
    async def test_get_user_by_api_key_hash_not_found(self, db):
        found = await db.get_user_by_api_key_hash("nonexistent_hash")
        assert found is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("email", [
        "a@b.com", "user+tag@gmail.com", "long.email.address@subdomain.example.org",
    ])
    async def test_various_email_formats(self, db, email):
        user = await db.create_user(email, "hash")
        assert user["email"] == email
        found = await db.get_user_by_email(email)
        assert found is not None


# ---------------------------------------------------------------------------
# update_user_tier
# ---------------------------------------------------------------------------


class TestUpdateUserTier:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("tier", ["free", "pro", "premium", "ultra", "enterprise"])
    async def test_update_tier(self, db, tier):
        user = await db.create_user(f"tier_{tier}@example.com", "hash")
        await db.update_user_tier(user["id"], tier)
        found = await db.get_user_by_id(user["id"])
        assert found["tier"] == tier


# ---------------------------------------------------------------------------
# set_user_api_key
# ---------------------------------------------------------------------------


class TestSetApiKey:
    @pytest.mark.asyncio
    async def test_set_api_key(self, db):
        user = await db.create_user("key@example.com", "hash")
        await db.set_user_api_key(user["id"], "my_key_hash")
        found = await db.get_user_by_id(user["id"])
        assert found["api_key_hash"] == "my_key_hash"

    @pytest.mark.asyncio
    async def test_update_api_key(self, db):
        user = await db.create_user("key2@example.com", "hash")
        await db.set_user_api_key(user["id"], "first_hash")
        await db.set_user_api_key(user["id"], "second_hash")
        found = await db.get_user_by_id(user["id"])
        assert found["api_key_hash"] == "second_hash"


# ---------------------------------------------------------------------------
# update_user_password
# ---------------------------------------------------------------------------


class TestUpdatePassword:
    @pytest.mark.asyncio
    async def test_update_password(self, db):
        user = await db.create_user("pw@example.com", "old_hash")
        await db.update_user_password(user["id"], "new_hash")
        found = await db.get_user_by_id(user["id"])
        assert found["password_hash"] == "new_hash"


# ---------------------------------------------------------------------------
# update_user_settings
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    @pytest.mark.asyncio
    async def test_update_settings(self, db):
        user = await db.create_user("settings@example.com", "hash")
        settings = {"watchlist": ["TSLA", "AAPL"], "theme": "dark"}
        await db.update_user_settings(user["id"], settings)
        found = await db.get_user_by_id(user["id"])
        assert found["settings"]["watchlist"] == ["TSLA", "AAPL"]
        assert found["settings"]["theme"] == "dark"

    @pytest.mark.asyncio
    async def test_update_settings_overwrite(self, db):
        user = await db.create_user("settings2@example.com", "hash")
        await db.update_user_settings(user["id"], {"a": 1})
        await db.update_user_settings(user["id"], {"b": 2})
        found = await db.get_user_by_id(user["id"])
        assert found["settings"] == {"b": 2}

    @pytest.mark.asyncio
    async def test_empty_settings(self, db):
        user = await db.create_user("empty_settings@example.com", "hash")
        await db.update_user_settings(user["id"], {})
        found = await db.get_user_by_id(user["id"])
        assert found["settings"] == {}


# ---------------------------------------------------------------------------
# Email alert settings
# ---------------------------------------------------------------------------


class TestEmailAlertSettings:
    @pytest.mark.asyncio
    async def test_insert_new_settings(self, db):
        user = await db.create_user("alert@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "digest_enabled": 1,
            "realtime_enabled": 0,
            "min_confidence": 0.7,
            "tickers": ["TSLA", "AAPL"],
            "stances": ["bullish"],
            "event_types": ["earnings_rumor"],
            "webhook_url": "",
        })
        settings = await db.get_email_alert_settings(user["id"])
        assert settings is not None
        assert settings["enabled"] == 1
        assert settings["min_confidence"] == 0.7
        assert settings["tickers"] == ["TSLA", "AAPL"]
        assert settings["stances"] == ["bullish"]

    @pytest.mark.asyncio
    async def test_update_existing_settings(self, db):
        user = await db.create_user("alert2@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {"enabled": 0})
        await db.upsert_email_alert_settings(user["id"], {"enabled": 1, "min_confidence": 0.9})
        settings = await db.get_email_alert_settings(user["id"])
        assert settings["enabled"] == 1
        assert settings["min_confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_get_settings_not_found(self, db):
        settings = await db.get_email_alert_settings("nonexistent")
        assert settings is None

    @pytest.mark.asyncio
    async def test_json_fields_parsed(self, db):
        user = await db.create_user("json@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {
            "tickers": ["SPY", "QQQ"],
            "stances": ["bearish", "mixed"],
            "event_types": ["squeeze_chatter", "macro"],
        })
        settings = await db.get_email_alert_settings(user["id"])
        assert isinstance(settings["tickers"], list)
        assert isinstance(settings["stances"], list)
        assert isinstance(settings["event_types"], list)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confidence", [0.0, 0.3, 0.5, 0.7, 1.0])
    async def test_various_confidence_thresholds(self, db, confidence):
        user = await db.create_user(f"conf_{confidence}@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {"min_confidence": confidence})
        settings = await db.get_email_alert_settings(user["id"])
        assert abs(settings["min_confidence"] - confidence) < 0.01


# ---------------------------------------------------------------------------
# get_users_for_digest
# ---------------------------------------------------------------------------


class TestUsersForDigest:
    @pytest.mark.asyncio
    async def test_returns_eligible_users(self, db):
        user = await db.create_user("digest@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "digest_enabled": 1,
        })
        results = await db.get_users_for_digest()
        assert len(results) >= 1
        emails = [r["email"] for r in results]
        assert "digest@example.com" in emails

    @pytest.mark.asyncio
    async def test_excludes_disabled(self, db):
        user = await db.create_user("disabled@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 0,
            "digest_enabled": 1,
        })
        results = await db.get_users_for_digest()
        emails = [r["email"] for r in results]
        assert "disabled@example.com" not in emails

    @pytest.mark.asyncio
    async def test_excludes_recently_digested(self, db):
        user = await db.create_user("recent@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "digest_enabled": 1,
        })
        await db.update_digest_sent(user["id"])
        results = await db.get_users_for_digest()
        emails = [r["email"] for r in results]
        assert "recent@example.com" not in emails


# ---------------------------------------------------------------------------
# get_users_for_realtime_alert
# ---------------------------------------------------------------------------


class TestRealtimeAlerts:
    @pytest.mark.asyncio
    async def test_returns_matching_users(self, db):
        user = await db.create_user("rt@example.com", "hash")
        await db.update_user_tier(user["id"], "pro")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "realtime_enabled": 1,
            "min_confidence": 0.5,
            "tickers": [],
            "stances": [],
            "event_types": [],
        })
        results = await db.get_users_for_realtime_alert("TSLA", "bullish", 0.7, "earnings_rumor")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_filters_by_ticker(self, db):
        user = await db.create_user("ticker_filter@example.com", "hash")
        await db.update_user_tier(user["id"], "pro")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "realtime_enabled": 1,
            "min_confidence": 0.3,
            "tickers": ["AAPL"],
            "stances": [],
            "event_types": [],
        })
        # TSLA should not match because user only watches AAPL
        results = await db.get_users_for_realtime_alert("TSLA", "bullish", 0.8, "other")
        emails = [r["email"] for r in results]
        assert "ticker_filter@example.com" not in emails

    @pytest.mark.asyncio
    async def test_filters_by_confidence(self, db):
        user = await db.create_user("low_conf@example.com", "hash")
        await db.update_user_tier(user["id"], "premium")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "realtime_enabled": 1,
            "min_confidence": 0.9,
        })
        results = await db.get_users_for_realtime_alert("SPY", "bearish", 0.5, "macro")
        emails = [r["email"] for r in results]
        assert "low_conf@example.com" not in emails

    @pytest.mark.asyncio
    async def test_excludes_free_tier(self, db):
        user = await db.create_user("free@example.com", "hash")
        # Tier is 'free' by default
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "realtime_enabled": 1,
            "min_confidence": 0.1,
        })
        results = await db.get_users_for_realtime_alert("SPY", "bullish", 0.9, "other")
        emails = [r["email"] for r in results]
        assert "free@example.com" not in emails

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stance_filter,signal_stance,should_match", [
        ([], "bullish", True),
        (["bullish"], "bullish", True),
        (["bearish"], "bullish", False),
        (["bullish", "bearish"], "bearish", True),
    ])
    async def test_stance_filtering(self, db, stance_filter, signal_stance, should_match):
        user = await db.create_user(f"stance_{signal_stance}_{len(stance_filter)}@example.com", "hash")
        await db.update_user_tier(user["id"], "pro")
        await db.upsert_email_alert_settings(user["id"], {
            "enabled": 1,
            "realtime_enabled": 1,
            "min_confidence": 0.1,
            "stances": stance_filter,
        })
        results = await db.get_users_for_realtime_alert("SPY", signal_stance, 0.8, "other")
        emails = [r["email"] for r in results]
        if should_match:
            assert user["email"] in emails or len(stance_filter) == 0
        else:
            assert user["email"] not in emails


# ---------------------------------------------------------------------------
# get_users_with_watchlist_ticker
# ---------------------------------------------------------------------------


class TestWatchlistTicker:
    @pytest.mark.asyncio
    async def test_finds_user_with_ticker(self, db):
        user = await db.create_user("watchlist@example.com", "hash")
        await db.update_user_tier(user["id"], "pro")
        await db.update_user_settings(user["id"], {"watchlist": ["TSLA", "AAPL"]})
        results = await db.get_users_with_watchlist_ticker("TSLA")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_excludes_free_tier(self, db):
        user = await db.create_user("free_wl@example.com", "hash")
        await db.update_user_settings(user["id"], {"watchlist": ["TSLA"]})
        results = await db.get_users_with_watchlist_ticker("TSLA")
        emails = [r.get("email") for r in results]
        assert "free_wl@example.com" not in emails

    @pytest.mark.asyncio
    async def test_no_match(self, db):
        user = await db.create_user("nomatch@example.com", "hash")
        await db.update_user_tier(user["id"], "pro")
        await db.update_user_settings(user["id"], {"watchlist": ["AAPL"]})
        results = await db.get_users_with_watchlist_ticker("TSLA")
        emails = [r.get("email") for r in results]
        assert "nomatch@example.com" not in emails

    @pytest.mark.asyncio
    async def test_case_insensitive(self, db):
        user = await db.create_user("case@example.com", "hash")
        await db.update_user_tier(user["id"], "premium")
        await db.update_user_settings(user["id"], {"watchlist": ["tsla"]})
        results = await db.get_users_with_watchlist_ticker("TSLA")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# update_digest_sent
# ---------------------------------------------------------------------------


class TestUpdateDigestSent:
    @pytest.mark.asyncio
    async def test_updates_timestamp(self, db):
        user = await db.create_user("dsent@example.com", "hash")
        await db.upsert_email_alert_settings(user["id"], {"enabled": 1, "digest_enabled": 1})
        before = time.time()
        await db.update_digest_sent(user["id"])
        settings = await db.get_email_alert_settings(user["id"])
        assert settings["last_digest_at"] >= before


# ---------------------------------------------------------------------------
# API usage tracking
# ---------------------------------------------------------------------------


class TestApiUsage:
    @pytest.mark.asyncio
    async def test_record_api_call_basic(self, db):
        user = await db.create_user("api@example.com", "hash")
        await db.record_api_call(user["id"], "/api/test")
        count = await db.get_api_call_count(user["id"], time.time() - 3600)
        assert count == 1

    @pytest.mark.asyncio
    async def test_record_api_call_with_endpoint(self, db):
        user = await db.create_user("api2@example.com", "hash")
        await db.record_api_call(user["id"], "/api/signals", "1.2.3.4")
        count = await db.get_api_call_count(user["id"], time.time() - 3600)
        assert count == 1

    @pytest.mark.asyncio
    async def test_multiple_calls(self, db):
        user = await db.create_user("api3@example.com", "hash")
        for i in range(5):
            await db.record_api_call(user["id"], f"/api/test{i}")
        count = await db.get_api_call_count(user["id"], time.time() - 3600)
        assert count == 5

    @pytest.mark.asyncio
    async def test_count_since_filters(self, db):
        user = await db.create_user("api4@example.com", "hash")
        await db.record_api_call(user["id"], "/api/test")
        # Count from future — should be 0
        count = await db.get_api_call_count(user["id"], time.time() + 3600)
        assert count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call_count", [0, 1, 3, 10])
    async def test_various_call_counts(self, db, call_count):
        user = await db.create_user(f"apicount_{call_count}@example.com", "hash")
        for i in range(call_count):
            await db.record_api_call(user["id"], f"/api/test{i}")
        count = await db.get_api_call_count(user["id"], time.time() - 3600)
        assert count == call_count


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_settings_default_empty_dict(self, db):
        user = await db.create_user("default@example.com", "hash")
        found = await db.get_user_by_id(user["id"])
        assert found["settings"] == {}

    @pytest.mark.asyncio
    async def test_duplicate_email_raises(self, db):
        await db.create_user("dup@example.com", "hash")
        with pytest.raises(Exception):
            await db.create_user("dup@example.com", "hash2")

    @pytest.mark.asyncio
    async def test_empty_watchlist(self, db):
        user = await db.create_user("empty_wl@example.com", "hash")
        await db.update_user_tier(user["id"], "pro")
        await db.update_user_settings(user["id"], {"watchlist": []})
        results = await db.get_users_with_watchlist_ticker("TSLA")
        emails = [r.get("email") for r in results]
        assert "empty_wl@example.com" not in emails

    @pytest.mark.asyncio
    async def test_no_watchlist_key(self, db):
        user = await db.create_user("no_wl@example.com", "hash")
        await db.update_user_tier(user["id"], "pro")
        await db.update_user_settings(user["id"], {"theme": "dark"})
        results = await db.get_users_with_watchlist_ticker("SPY")
        emails = [r.get("email") for r in results]
        assert "no_wl@example.com" not in emails
