"""examples/demo.py runs the real pipeline offline on the bundled sample posts."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("rot_demo", DEMO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if the demo tries to reach Yahoo Finance instead of the bundled snapshot."""
    import rot.market.enricher as enricher
    import rot.market.symbol_validator as validator

    def boom(*a, **k):
        raise AssertionError("demo tried to fetch live market data")

    monkeypatch.setattr(enricher.yf, "Ticker", boom)
    monkeypatch.setattr(validator.yf, "Ticker", boom)
    monkeypatch.delenv("ROT_LLM_API_KEY", raising=False)


def test_sample_files_are_well_formed():
    posts = json.loads((ROOT / "examples" / "sample" / "posts.json").read_text(encoding="utf-8"))
    assert posts["poll_gap_s"] > 0
    assert len(posts["posts"]) >= 3
    for p in posts["posts"]:
        assert len(p["polls"]) == 2
    snap = json.loads((ROOT / "examples" / "sample" / "market_snapshot.json").read_text(encoding="utf-8"))
    assert snap["fetched"] and snap["symbols_valid"] and snap["market"]


def test_demo_runs_offline(no_network, capsys):
    demo = _load_demo()
    assert demo.main([]) == 0
    out = capsys.readouterr().out
    assert "pass 1: snapshots 5, candidates 0" in out
    assert "pass 2: snapshots 5" in out
    assert "bundled Yahoo Finance snapshot" in out
    assert "stub mode" in out
    assert "NVDA" in out and "TSLA" in out
    assert "Not financial advice." in out


def test_sample_ingestor_replays_two_polls():
    demo = _load_demo()
    demo._import_rot()
    ing = demo.SampleIngestor(demo.POSTS, now=1_800_000_000)
    first, second = ing.poll(), ing.poll()
    assert len(first) == len(second) == 5
    assert second[0].snapshot_ts - first[0].snapshot_ts == 600
    assert second[0].post.score >= first[0].post.score
