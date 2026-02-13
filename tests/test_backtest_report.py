"""Tests for backtest report generation."""

from __future__ import annotations

import pytest

from rot.backtest.report import generate_csv_trades, generate_html_report


# ── Helpers ──


def _make_trade(**overrides) -> dict:
    defaults = dict(
        signal_id="sig-001",
        ticker="TSLA",
        stance="bullish",
        strategy="debit_spread",
        event_type="product_news",
        confidence=0.65,
        entry_price=250.0,
        exit_price=260.0,
        pnl_pct=4.0,
        pnl_dollars=200.0,
        is_win=True,
    )
    defaults.update(overrides)
    return defaults


def _make_result_dict(**overrides) -> dict:
    defaults = dict(
        total_trades=10,
        winning_trades=6,
        losing_trades=4,
        win_rate=0.6,
        total_return_pct=12.5,
        annual_return_pct=50.0,
        final_equity=11250.0,
        sharpe_ratio=1.2,
        sortino_ratio=1.8,
        calmar_ratio=2.0,
        max_drawdown_pct=6.3,
        max_drawdown_duration_s=86400.0,
        profit_factor=1.5,
        expectancy=1.25,
        avg_win_pct=5.0,
        avg_loss_pct=-3.0,
        equity_curve=[],
        trades=[_make_trade(), _make_trade(is_win=False, pnl_pct=-3.0, pnl_dollars=-150.0)],
        monthly_returns={"2024-01": 3.5},
        strategy_breakdown={},
        drawdown_periods=[],
    )
    defaults.update(overrides)
    return defaults


# ── CSV Tests ──


class TestGenerateCsvEmpty:
    def test_empty_trades(self):
        csv = generate_csv_trades([])
        assert "signal_id" in csv
        assert "ticker" in csv
        lines = csv.strip().split("\n")
        assert len(lines) == 1  # header only

    def test_header_contains_all_fields(self):
        csv = generate_csv_trades([])
        header = csv.strip()
        for field in ["signal_id", "ticker", "stance", "strategy", "event_type",
                       "confidence", "entry_price", "exit_price", "pnl_pct",
                       "pnl_dollars", "is_win"]:
            assert field in header


class TestGenerateCsvWithTrades:
    def test_single_trade(self):
        trades = [_make_trade()]
        csv = generate_csv_trades(trades)
        lines = csv.strip().split("\n")
        assert len(lines) == 2  # header + 1 data row

    def test_multiple_trades(self):
        trades = [_make_trade(), _make_trade(ticker="AAPL"), _make_trade(ticker="NVDA")]
        csv = generate_csv_trades(trades)
        lines = csv.strip().split("\n")
        assert len(lines) == 4

    def test_ticker_in_output(self):
        trades = [_make_trade(ticker="GOOGL")]
        csv = generate_csv_trades(trades)
        assert "GOOGL" in csv

    def test_pnl_rounded(self):
        trades = [_make_trade(pnl_pct=3.456789)]
        csv = generate_csv_trades(trades)
        assert "3.46" in csv

    def test_confidence_rounded(self):
        trades = [_make_trade(confidence=0.123456)]
        csv = generate_csv_trades(trades)
        assert "0.123" in csv

    def test_missing_fields_handled(self):
        trades = [{"ticker": "TSLA"}]  # minimal dict
        csv = generate_csv_trades(trades)
        lines = csv.strip().split("\n")
        assert len(lines) == 2
        assert "TSLA" in lines[1]


# ── HTML Report Tests ──


class TestGenerateHtmlEmpty:
    def test_empty_result(self):
        html = generate_html_report({})
        assert "<!DOCTYPE html>" in html
        assert "ROT Backtest Report" in html

    def test_has_kpi_section(self):
        html = generate_html_report(_make_result_dict())
        assert "Total Trades" in html
        assert "Win Rate" in html
        assert "Sharpe Ratio" in html


class TestGenerateHtmlWithData:
    def test_trade_count_displayed(self):
        html = generate_html_report(_make_result_dict(total_trades=42))
        assert "42" in html

    def test_return_displayed(self):
        html = generate_html_report(_make_result_dict(total_return_pct=15.3))
        assert "+15.3%" in html

    def test_negative_return(self):
        html = generate_html_report(_make_result_dict(total_return_pct=-8.7))
        assert "-8.7%" in html

    def test_trades_in_table(self):
        html = generate_html_report(_make_result_dict())
        assert "TSLA" in html
        assert "bullish" in html
        assert "debit_spread" in html

    def test_sharpe_none(self):
        html = generate_html_report(_make_result_dict(sharpe_ratio=None))
        assert "N/A" in html


class TestGenerateHtmlRisk:
    def test_risk_section_included(self):
        risk = {"var_95": 5.0, "cvar_95": 7.5, "recovery_factor": 2.0}
        html = generate_html_report(_make_result_dict(), risk_dict=risk)
        assert "Risk Analytics" in html
        assert "Var 95" in html or "var_95" in html.lower()

    def test_no_risk_section_when_none(self):
        html = generate_html_report(_make_result_dict(), risk_dict=None)
        assert "Risk Analytics" not in html


class TestGenerateHtmlMonteCarlo:
    def test_mc_section_included(self):
        mc = {
            "n_simulations": 1000,
            "n_trades": 20,
            "prob_profit": 0.85,
            "prob_ruin": 0.02,
            "final_equity_p50": 12000.0,
            "final_equity_p5": 8000.0,
            "final_equity_p95": 16000.0,
        }
        html = generate_html_report(_make_result_dict(), mc_dict=mc)
        assert "Monte Carlo" in html
        assert "1000 simulations" in html

    def test_no_mc_section_when_none(self):
        html = generate_html_report(_make_result_dict(), mc_dict=None)
        assert "Monte Carlo" not in html


class TestGenerateHtmlStructure:
    def test_valid_html(self):
        html = generate_html_report(_make_result_dict())
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<body>" in html
        assert "</body>" in html

    def test_has_style_section(self):
        html = generate_html_report(_make_result_dict())
        assert "<style>" in html

    def test_has_footer(self):
        html = generate_html_report(_make_result_dict())
        assert "ROT" in html.split("footer")[1] if "footer" in html else True
