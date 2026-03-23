"""
Interest rate term structure modeling.
Implements bootstrapping, Nelson-Siegel, and TermStructureModel class.
All computation in pure Python.
"""
import math


def bootstrap_zero_curve(maturities: list, par_rates: list) -> list:
    """
    Bootstrap zero rates from par (coupon) rates.
    Returns list of (maturity, zero_rate) pairs.
    Uses annual coupon payments and act/act day count convention (simplified).
    """
    if not maturities or len(maturities) != len(par_rates):
        return []

    zero_rates = []
    discount_factors = {}

    for i, (T, c) in enumerate(zip(maturities, par_rates)):
        # For par bond: price = 100, coupon = c * 100 (annual)
        # P = c * sum(DF(t)) + DF(T) * 100 = 100
        # => DF(T) = (1 - c * sum_prev_dfs) / (1 + c)

        # Sum of discount factors for coupon payment dates before T
        sum_prev = 0.0
        # Integer coupon periods before final maturity
        n_coupons = int(round(T))
        for t_idx in range(1, n_coupons):
            t = float(t_idx)
            if t in discount_factors:
                sum_prev += discount_factors[t]
            else:
                # Interpolate if needed
                if zero_rates:
                    # Simple linear interpolation of zero rates
                    zr = _interp_zero(zero_rates, t)
                    df = math.exp(-zr * t)
                    sum_prev += df

        df_T = (1.0 - c * sum_prev) / (1.0 + c)
        df_T = max(df_T, 1e-10)

        discount_factors[T] = df_T
        zero_rate = -math.log(df_T) / T if T > 0 else 0.0
        zero_rates.append((T, zero_rate))

    return zero_rates


def _interp_zero(zero_rates: list, t: float) -> float:
    """Linear interpolation of zero rates."""
    if not zero_rates:
        return 0.0
    if t <= zero_rates[0][0]:
        return zero_rates[0][1]
    if t >= zero_rates[-1][0]:
        return zero_rates[-1][1]
    for i in range(len(zero_rates) - 1):
        t0, r0 = zero_rates[i]
        t1, r1 = zero_rates[i + 1]
        if t0 <= t <= t1:
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return r0 + frac * (r1 - r0)
    return zero_rates[-1][1]


def forward_rate(zero_rates: list, t1: float, t2: float) -> float:
    """
    Compute continuously compounded forward rate f(t1, t2) from zero curve.
    f(t1,t2) = (r(t2)*t2 - r(t1)*t1) / (t2 - t1)
    """
    if t2 <= t1 or t1 < 0:
        return 0.0
    r1 = _interp_zero(zero_rates, t1)
    r2 = _interp_zero(zero_rates, t2)
    return (r2 * t2 - r1 * t1) / (t2 - t1)


def nelson_siegel(beta0: float, beta1: float, beta2: float,
                  lambda_: float, maturities: list) -> list:
    """
    Nelson-Siegel yield curve model.
    y(T) = beta0 + beta1 * (1 - exp(-T/lambda)) / (T/lambda)
           + beta2 * ((1 - exp(-T/lambda)) / (T/lambda) - exp(-T/lambda))
    Returns list of yields corresponding to maturities.
    """
    yields = []
    for T in maturities:
        if T <= 0:
            yields.append(beta0 + beta1)
            continue
        x = T / lambda_
        factor1 = (1.0 - math.exp(-x)) / x
        factor2 = factor1 - math.exp(-x)
        y = beta0 + beta1 * factor1 + beta2 * factor2
        yields.append(y)
    return yields


class TermStructureModel:
    """
    Interest rate term structure model.
    Supports 'nelson_siegel' and 'linear' fitting methods.
    """

    def __init__(self, model: str = "nelson_siegel"):
        self.model = model
        self.params = {}
        self.zero_curve = []  # List of (maturity, zero_rate)

    def fit(self, maturities: list, yields: list) -> dict:
        """
        Fit model parameters to observed yield data.
        Returns dict of fitted parameters.
        """
        if self.model == "nelson_siegel":
            self.params = self._fit_nelson_siegel(maturities, yields)
        elif self.model == "linear":
            self.params = self._fit_linear(maturities, yields)
        else:
            self.params = self._fit_linear(maturities, yields)

        # Store zero curve from fitted yields
        self.zero_curve = list(zip(maturities, yields))
        return self.params

    def _fit_nelson_siegel(self, maturities: list, yields: list) -> dict:
        """Grid search over Nelson-Siegel parameters to minimize RSS."""
        best_params = {"beta0": 0.05, "beta1": -0.02, "beta2": 0.01, "lambda": 1.5}
        best_rss = 1e18

        # Grid search
        for b0 in [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]:
            for b1 in [-0.04, -0.02, 0.0, 0.02, 0.04]:
                for b2 in [-0.02, 0.0, 0.02, 0.04]:
                    for lam in [0.5, 1.0, 1.5, 2.0, 3.0]:
                        pred = nelson_siegel(b0, b1, b2, lam, maturities)
                        rss = sum((p - a) ** 2 for p, a in zip(pred, yields))
                        if rss < best_rss:
                            best_rss = rss
                            best_params = {
                                "beta0": b0, "beta1": b1,
                                "beta2": b2, "lambda": lam
                            }

        # Gradient refinement around best grid point
        params = best_params
        lr = 0.001
        for _ in range(200):
            pred = nelson_siegel(
                params["beta0"], params["beta1"],
                params["beta2"], params["lambda"], maturities
            )
            residuals = [p - a for p, a in zip(pred, yields)]

            # Numerical gradients
            eps = 1e-5
            grads = {}
            for key in ["beta0", "beta1", "beta2", "lambda"]:
                p_plus = dict(params)
                p_plus[key] += eps
                pred_plus = nelson_siegel(
                    p_plus["beta0"], p_plus["beta1"],
                    p_plus["beta2"], p_plus["lambda"], maturities
                )
                rss_plus = sum((p - a) ** 2 for p, a in zip(pred_plus, yields))
                p_minus = dict(params)
                p_minus[key] -= eps
                pred_minus = nelson_siegel(
                    p_minus["beta0"], p_minus["beta1"],
                    p_minus["beta2"], p_minus["lambda"], maturities
                )
                rss_minus = sum((p - a) ** 2 for p, a in zip(pred_minus, yields))
                grads[key] = (rss_plus - rss_minus) / (2 * eps)

            for key in ["beta0", "beta1", "beta2"]:
                params[key] -= lr * grads[key]
            params["lambda"] = max(0.1, params["lambda"] - lr * grads["lambda"])

        return params

    def _fit_linear(self, maturities: list, yields: list) -> dict:
        """Simple linear fit: y = alpha + beta * T."""
        if len(maturities) < 2:
            return {"alpha": yields[0] if yields else 0.0, "beta": 0.0}

        n = len(maturities)
        mean_T = sum(maturities) / n
        mean_y = sum(yields) / n
        num = sum((T - mean_T) * (y - mean_y) for T, y in zip(maturities, yields))
        den = sum((T - mean_T) ** 2 for T in maturities)
        beta = num / den if abs(den) > 1e-12 else 0.0
        alpha = mean_y - beta * mean_T
        return {"alpha": alpha, "beta": beta}

    def yield_at(self, maturity: float) -> float:
        """Compute model yield at given maturity."""
        if self.model == "nelson_siegel" and self.params:
            p = self.params
            return nelson_siegel(
                p["beta0"], p["beta1"], p["beta2"], p["lambda"], [maturity]
            )[0]
        elif self.params:
            alpha = self.params.get("alpha", 0.0)
            beta = self.params.get("beta", 0.0)
            return alpha + beta * maturity
        elif self.zero_curve:
            return _interp_zero(self.zero_curve, maturity)
        return 0.0

    def forward_curve(self, max_maturity: float, n_points: int = 50) -> list:
        """
        Compute instantaneous forward rate curve f(T) = y(T) + T * dy/dT.
        Returns list of (maturity, forward_rate) pairs.
        """
        result = []
        dt = max_maturity / max(n_points - 1, 1)
        for i in range(n_points):
            T = dt * i + 1e-6
            y_T = self.yield_at(T)
            y_T2 = self.yield_at(T + dt)
            # f(T) approximated as d(T*y)/dT = y + T * dy/dT
            dy_dT = (y_T2 - y_T) / dt if dt > 0 else 0.0
            f = y_T + T * dy_dT
            result.append((T, f))
        return result

    def par_curve(self, max_maturity: float, n_points: int = 50) -> list:
        """
        Compute par yield curve (coupon rate that prices bond at par).
        Returns list of (maturity, par_rate) pairs.
        """
        result = []
        step = max_maturity / max(n_points - 1, 1)
        for i in range(n_points):
            T = step * i + step  # Start from step, not 0
            # Sum of discount factors for annual coupon periods
            sum_df = 0.0
            n_periods = max(1, int(round(T)))
            for t_idx in range(1, n_periods + 1):
                t = float(t_idx)
                zr = self.yield_at(t)
                df = math.exp(-zr * t)
                sum_df += df
            # Par rate: c = (1 - DF(T)) / sum_DF
            zr_T = self.yield_at(T)
            df_T = math.exp(-zr_T * T)
            par_rate = (1.0 - df_T) / sum_df if sum_df > 1e-10 else 0.0
            result.append((T, par_rate))
        return result

    def duration(self, coupon: float, maturity: float, face: float = 100.0) -> float:
        """
        Compute Macaulay duration.
        duration = sum(t * CF_t * DF_t) / price
        """
        n = max(1, int(round(maturity)))
        price = 0.0
        weighted_time = 0.0

        for t_idx in range(1, n + 1):
            t = float(t_idx)
            zr = self.yield_at(t)
            df = math.exp(-zr * t)
            cf = coupon * face if t_idx < n else (coupon + 1.0) * face
            pv = cf * df
            price += pv
            weighted_time += t * pv

        return weighted_time / price if price > 1e-10 else 0.0

    def convexity(self, coupon: float, maturity: float, face: float = 100.0) -> float:
        """
        Compute bond convexity.
        convexity = sum(t*(t+1) * CF_t * DF_t) / (price * (1+y)^2)
        Approximated using model yield to maturity.
        """
        n = max(1, int(round(maturity)))
        y = self.yield_at(maturity)
        price = 0.0
        conv_num = 0.0

        for t_idx in range(1, n + 1):
            t = float(t_idx)
            df = 1.0 / (1.0 + y) ** t
            cf = coupon * face if t_idx < n else (coupon + 1.0) * face
            pv = cf * df
            price += pv
            conv_num += t * (t + 1) * pv

        if price < 1e-10:
            return 0.0
        return conv_num / (price * (1.0 + y) ** 2)

    def dv01(self, coupon: float, maturity: float, face: float = 100.0) -> float:
        """
        Dollar value of a basis point (DV01).
        DV01 = -dP/dy * 0.0001 ≈ duration * price * 0.0001
        """
        n = max(1, int(round(maturity)))
        y = self.yield_at(maturity)

        price = 0.0
        for t_idx in range(1, n + 1):
            t = float(t_idx)
            cf = coupon * face if t_idx < n else (coupon + 1.0) * face
            price += cf / (1.0 + y) ** t

        dur = self.duration(coupon, maturity, face)
        mod_dur = dur / (1.0 + y)
        return mod_dur * price * 0.0001
