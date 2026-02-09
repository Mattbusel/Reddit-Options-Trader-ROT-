from __future__ import annotations

from rot.reasoner.parser import parse_reasoning_response, _extract_json


class TestExtractJson:
    def test_direct_json(self):
        result = _extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fenced(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_text_with_json_block(self):
        text = 'Here is my analysis:\n\n{"key": "value"}\n\nHope this helps!'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_invalid_json_raises(self):
        import pytest
        with pytest.raises(ValueError):
            _extract_json("this is not json at all")


class TestParseReasoningResponse:
    def test_valid_response(self):
        response = """{
            "event_type": "earnings_rumor",
            "stance": "bullish",
            "time_horizon": "earnings",
            "confidence": 0.7,
            "thesis": "Strong earnings expected",
            "catalyst_window": "Next Tuesday",
            "market_expectation": "Priced in partially",
            "invalidations": ["Earnings miss"],
            "recommended_structures": ["bull call spread"],
            "risk_notes": ["High IV"]
        }"""

        packet = parse_reasoning_response(response, ["TSLA"])
        assert packet.thesis == "Strong earnings expected"
        assert packet.raw["event_type"] == "earnings_rumor"
        assert packet.raw["confidence"] == 0.7

    def test_invalid_event_type_defaults(self):
        response = '{"event_type": "invalid_type", "stance": "bullish"}'
        packet = parse_reasoning_response(response, ["TSLA"])
        assert packet.raw["event_type"] == "other"

    def test_confidence_clamped(self):
        response = '{"confidence": 5.0}'
        packet = parse_reasoning_response(response, ["TSLA"])
        assert packet.raw["confidence"] == 1.0

    def test_fallback_on_bad_json(self):
        packet = parse_reasoning_response("not json", ["TSLA"])
        assert "LLM parse failed" in packet.thesis
        assert "error" in packet.raw

    def test_missing_fields_have_defaults(self):
        response = '{"thesis": "Just a thesis"}'
        packet = parse_reasoning_response(response, ["TSLA"])
        assert packet.thesis == "Just a thesis"
        assert packet.catalyst_window == "unknown"
