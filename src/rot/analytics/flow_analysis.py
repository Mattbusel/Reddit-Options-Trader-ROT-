"""Order flow analysis and VPIN calculation."""
import math
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class TradeBar:
    timestamp: float
    price: float
    volume: float
    buy_volume: float  # estimated
    sell_volume: float


def classify_trade(price: float, prev_price: float) -> str:
    """Tick rule: classify trade as buy/sell."""
    if price > prev_price:
        return 'buy'
    elif price < prev_price:
        return 'sell'
    return 'buy'  # tie-break


def bulk_volume_classification(prices: List[float], volumes: List[float]) -> List[TradeBar]:
    """Classify volume as buy/sell using tick rule."""
    bars = []
    for i, (p, v) in enumerate(zip(prices, volumes)):
        prev_p = prices[i-1] if i > 0 else p
        side = classify_trade(p, prev_p)
        buy_v = v if side == 'buy' else 0.0
        sell_v = v if side == 'sell' else 0.0
        bars.append(TradeBar(float(i), p, v, buy_v, sell_v))
    return bars


class VpinCalculator:
    """Volume-Synchronized Probability of Informed Trading (VPIN)."""

    def __init__(self, bucket_size: float = 50.0, num_buckets: int = 50):
        self.bucket_size = bucket_size
        self.num_buckets = num_buckets

    def compute_buckets(self, bars: List[TradeBar]) -> List[Tuple[float, float]]:
        """Returns list of (buy_volume, sell_volume) per bucket."""
        buckets = []
        current_buy = 0.0
        current_sell = 0.0
        current_size = 0.0

        for bar in bars:
            remaining = bar.volume
            while remaining > 0:
                space = self.bucket_size - current_size
                fill = min(remaining, space)
                frac = fill / bar.volume if bar.volume > 0 else 0
                current_buy += bar.buy_volume * frac
                current_sell += bar.sell_volume * frac
                current_size += fill
                remaining -= fill
                if current_size >= self.bucket_size - 1e-9:
                    buckets.append((current_buy, current_sell))
                    current_buy = current_sell = current_size = 0.0

        return buckets

    def vpin(self, buckets: List[Tuple[float, float]]) -> List[float]:
        """Compute rolling VPIN over num_buckets window."""
        vpins = []
        for i in range(self.num_buckets, len(buckets) + 1):
            window = buckets[i - self.num_buckets:i]
            total_vol = sum(b + s for b, s in window)
            if total_vol < 1e-9:
                vpins.append(0.0)
            else:
                imbalance = sum(abs(b - s) for b, s in window)
                vpins.append(imbalance / total_vol)
        return vpins

    def flow_toxicity(self, bars: List[TradeBar]) -> dict:
        """Compute flow toxicity metrics."""
        buckets = self.compute_buckets(bars)
        vpins = self.vpin(buckets)
        total_vol = sum(b.volume for b in bars)
        total_buy = sum(b.buy_volume for b in bars)
        total_sell = sum(b.sell_volume for b in bars)
        return {
            "vpin_current": vpins[-1] if vpins else 0.0,
            "vpin_mean": sum(vpins) / len(vpins) if vpins else 0.0,
            "vpin_max": max(vpins) if vpins else 0.0,
            "order_imbalance": (total_buy - total_sell) / total_vol if total_vol > 0 else 0.0,
            "bucket_count": len(buckets),
        }


class KyleLambda:
    """Kyle's lambda (price impact) estimation."""

    def estimate(self, price_changes: List[float], order_imbalances: List[float]) -> float:
        """OLS regression: delta_p = lambda * OI + epsilon."""
        n = len(price_changes)
        if n < 2:
            return 0.0
        x = order_imbalances
        y = price_changes
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        den = sum((x[i] - x_mean) ** 2 for i in range(n))
        return num / den if den > 1e-12 else 0.0

    def estimate_impact(self, lambda_val: float, trade_size: float, avg_daily_volume: float) -> float:
        """Estimated price impact in bps for given trade."""
        return lambda_val * trade_size / avg_daily_volume * 10000
