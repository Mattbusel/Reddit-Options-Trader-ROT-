"""Implied volatility surface fitting with SABR model."""
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict


def bsm_iv_newton(market_price: float, S: float, K: float, T: float, r: float,
                   is_call: bool = True, tol: float = 1e-6, max_iter: int = 100) -> Optional[float]:
    """Newton-Raphson IV solver."""
    if T <= 0 or market_price <= 0:
        return None

    def bsm(sigma):
        if sigma <= 0:
            return 0.0
        d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
        d2 = d1 - sigma*math.sqrt(T)
        nd1 = 0.5*(1+math.erf(d1/math.sqrt(2)))
        nd2 = 0.5*(1+math.erf(d2/math.sqrt(2)))
        if is_call:
            return S*nd1 - K*math.exp(-r*T)*nd2
        return K*math.exp(-r*T)*(1-nd2) - S*(1-nd1)

    def vega(sigma):
        if sigma <= 0:
            return 1e-10
        d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
        return S * math.sqrt(T) * math.exp(-0.5*d1**2) / math.sqrt(2*math.pi)

    sigma = 0.3
    for _ in range(max_iter):
        price = bsm(sigma)
        v = vega(sigma)
        diff = market_price - price
        if abs(diff) < tol:
            return sigma
        sigma += diff / max(v, 1e-10)
        sigma = max(0.001, min(sigma, 5.0))
    return sigma


@dataclass
class VolSurface:
    """Discrete implied volatility surface by strike and expiry."""
    strikes: List[float]
    expiries: List[float]  # in years
    iv_matrix: List[List[float]]  # iv_matrix[expiry_idx][strike_idx]

    def iv(self, K: float, T: float) -> float:
        """Bilinear interpolation."""
        # Find enclosing expiry bracket
        if T <= self.expiries[0]:
            t_idx, t_w = 0, 1.0
        elif T >= self.expiries[-1]:
            t_idx, t_w = len(self.expiries)-2, 0.0
        else:
            t_idx = next(i for i in range(len(self.expiries)-1) if self.expiries[i+1] >= T)
            t_w = (self.expiries[t_idx+1] - T) / (self.expiries[t_idx+1] - self.expiries[t_idx])

        # Find enclosing strike bracket
        if K <= self.strikes[0]:
            k_idx, k_w = 0, 1.0
        elif K >= self.strikes[-1]:
            k_idx, k_w = len(self.strikes)-2, 0.0
        else:
            k_idx = next(i for i in range(len(self.strikes)-1) if self.strikes[i+1] >= K)
            k_w = (self.strikes[k_idx+1] - K) / (self.strikes[k_idx+1] - self.strikes[k_idx])

        # Bilinear interpolation
        iv00 = self.iv_matrix[t_idx][k_idx]
        iv01 = self.iv_matrix[t_idx][min(k_idx+1, len(self.strikes)-1)]
        iv10 = self.iv_matrix[min(t_idx+1, len(self.expiries)-1)][k_idx]
        iv11 = self.iv_matrix[min(t_idx+1, len(self.expiries)-1)][min(k_idx+1, len(self.strikes)-1)]

        iv_t1 = k_w * iv00 + (1-k_w) * iv01
        iv_t2 = k_w * iv10 + (1-k_w) * iv11
        return t_w * iv_t1 + (1-t_w) * iv_t2


@dataclass
class SABRModel:
    """SABR stochastic volatility model: Hagan et al. approximation."""
    alpha: float  # initial vol
    beta: float   # CEV exponent (0 to 1)
    rho: float    # correlation (-1 to 1)
    nu: float     # vol of vol

    def implied_vol(self, F: float, K: float, T: float) -> float:
        """Hagan SABR approximation for implied vol."""
        if abs(F - K) < 1e-10:
            # ATM formula
            fk_beta = F ** (1 - self.beta)
            term1 = self.alpha / fk_beta
            term2 = 1 + ((1-self.beta)**2/24 * self.alpha**2 / fk_beta**2
                         + self.rho*self.beta*self.nu*self.alpha/(4*fk_beta)
                         + (2-3*self.rho**2)*self.nu**2/24) * T
            return term1 * term2

        FK = F * K
        log_FK = math.log(F / K)
        fk_beta = FK ** ((1-self.beta)/2)

        z = self.nu / self.alpha * fk_beta * log_FK
        chi_z = math.log((math.sqrt(1 - 2*self.rho*z + z**2) + z - self.rho) / (1 - self.rho))

        num = self.alpha
        denom = fk_beta * (1 + (1-self.beta)**2/24 * log_FK**2 + (1-self.beta)**4/1920 * log_FK**4)

        correction = 1 + ((1-self.beta)**2/24 * self.alpha**2/FK**((1-self.beta))
                          + self.rho*self.beta*self.nu*self.alpha/(4*FK**((1-self.beta)/2))
                          + (2-3*self.rho**2)*self.nu**2/24) * T

        return (num / denom) * (z / chi_z) * correction

    def calibrate(self, F: float, strikes: List[float], T: float, market_ivs: List[float],
                  n_iters: int = 100, lr: float = 0.001) -> 'SABRModel':
        """Gradient descent calibration."""
        alpha, rho, nu = self.alpha, self.rho, self.nu

        for _ in range(n_iters):
            total_err = 0.0
            d_alpha = d_rho = d_nu = 0.0
            eps = 1e-5
            for K, iv_mkt in zip(strikes, market_ivs):
                iv_model = SABRModel(alpha, self.beta, rho, nu).implied_vol(F, K, T)
                err = iv_model - iv_mkt
                total_err += err ** 2
                # finite difference gradients
                da = (SABRModel(alpha+eps, self.beta, rho, nu).implied_vol(F, K, T) - iv_model) / eps
                dr = (SABRModel(alpha, self.beta, rho+eps, nu).implied_vol(F, K, T) - iv_model) / eps
                dn = (SABRModel(alpha, self.beta, rho, nu+eps).implied_vol(F, K, T) - iv_model) / eps
                d_alpha += err * da
                d_rho += err * dr
                d_nu += err * dn

            alpha -= lr * d_alpha
            rho -= lr * d_rho
            nu -= lr * d_nu
            alpha = max(0.001, alpha)
            rho = max(-0.999, min(0.999, rho))
            nu = max(0.001, nu)

        return SABRModel(alpha, self.beta, rho, nu)
