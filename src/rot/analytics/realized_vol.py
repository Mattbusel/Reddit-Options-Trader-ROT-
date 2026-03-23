"""Realized volatility estimators."""
import math
from typing import List, Optional


def annualize(daily_vol: float, trading_days: int = 252) -> float:
    return daily_vol * math.sqrt(trading_days)


def close_to_close(closes: List[float], annualize_flag: bool = True) -> float:
    """Classic close-to-close volatility."""
    if len(closes) < 2:
        return 0.0
    returns = [math.log(closes[i]/closes[i-1]) for i in range(1, len(closes))]
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean)**2 for r in returns) / (n - 1)
    vol = math.sqrt(var)
    return annualize(vol) if annualize_flag else vol


def parkinson(highs: List[float], lows: List[float], annualize_flag: bool = True) -> float:
    """Parkinson estimator using high-low range."""
    n = len(highs)
    if n == 0:
        return 0.0
    factor = 1.0 / (4 * n * math.log(2))
    s = sum(math.log(highs[i]/lows[i])**2 for i in range(n))
    vol = math.sqrt(factor * s)
    return annualize(vol) if annualize_flag else vol


def garman_klass(opens: List[float], highs: List[float], lows: List[float], closes: List[float], annualize_flag: bool = True) -> float:
    """Garman-Klass estimator."""
    n = len(closes)
    if n == 0:
        return 0.0
    s = 0.0
    for i in range(n):
        hl = math.log(highs[i]/lows[i])**2
        co = math.log(closes[i]/opens[i])**2
        s += 0.5 * hl - (2*math.log(2) - 1) * co
    vol = math.sqrt(s / n)
    return annualize(vol) if annualize_flag else vol


def rogers_satchell(opens: List[float], highs: List[float], lows: List[float], closes: List[float], annualize_flag: bool = True) -> float:
    """Rogers-Satchell estimator (drift-independent)."""
    n = len(closes)
    if n == 0:
        return 0.0
    s = 0.0
    for i in range(n):
        s += (math.log(highs[i]/closes[i]) * math.log(highs[i]/opens[i]) +
              math.log(lows[i]/closes[i]) * math.log(lows[i]/opens[i]))
    vol = math.sqrt(s / n)
    return annualize(vol) if annualize_flag else vol


def yang_zhang(opens: List[float], highs: List[float], lows: List[float], closes: List[float], k: float = 0.34, annualize_flag: bool = True) -> float:
    """Yang-Zhang estimator (drift-robust, overnight-gap robust)."""
    n = len(closes)
    if n < 2:
        return 0.0
    # Overnight returns
    overnight = [math.log(opens[i]/closes[i-1]) for i in range(1, n)]
    o_mean = sum(overnight) / len(overnight)
    var_o = sum((r - o_mean)**2 for r in overnight) / (len(overnight) - 1) if len(overnight) > 1 else 0
    # Open-to-close returns
    oc = [math.log(closes[i]/opens[i]) for i in range(n)]
    oc_mean = sum(oc) / n
    var_oc = sum((r - oc_mean)**2 for r in oc) / (n - 1) if n > 1 else 0
    # Rogers-Satchell portion (use same-day data)
    var_rs = sum(math.log(highs[i]/closes[i]) * math.log(highs[i]/opens[i]) +
                 math.log(lows[i]/closes[i]) * math.log(lows[i]/opens[i]) for i in range(n)) / n
    vol = math.sqrt(var_o + k * var_oc + (1 - k) * var_rs)
    return annualize(vol) if annualize_flag else vol


class RealizedVolSurface:
    def __init__(self):
        self.term_structure: dict = {}

    def add_tenor(self, days: int, opens: List[float], highs: List[float], lows: List[float], closes: List[float]):
        self.term_structure[days] = {
            "close_close": close_to_close(closes),
            "parkinson": parkinson(highs, lows),
            "garman_klass": garman_klass(opens, highs, lows, closes),
            "rogers_satchell": rogers_satchell(opens, highs, lows, closes),
            "yang_zhang": yang_zhang(opens, highs, lows, closes),
        }

    def vol_term_structure(self, estimator: str = "close_close") -> List[tuple]:
        return sorted([(d, self.term_structure[d][estimator]) for d in self.term_structure])

    def vol_of_vol(self, estimator: str = "close_close") -> float:
        vols = [self.term_structure[d][estimator] for d in self.term_structure]
        if len(vols) < 2:
            return 0.0
        mean = sum(vols) / len(vols)
        return math.sqrt(sum((v - mean)**2 for v in vols) / (len(vols) - 1))
