"""Black-Scholes-Merton pricing and greeks. Clean-room, stdlib only.

European options on a dividend-paying underlying. Used by the backtester to price
structures when no historical option chain exists (SPEC: no vendor chain data is
available on this machine, so contracts are model-priced).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _cdf(x: float) -> float:
    """Standard normal CDF via erf — exact to double precision, no table."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float          # per 1.00 (100 vol points), divide by 100 for per-point
    theta: float         # per year
    rho: float


def _d1_d2(S, K, T, r, sigma, q=0.0):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vt
    return d1, d1 - vt


def price(S: float, K: float, T: float, r: float, sigma: float,
          kind: str, q: float = 0.0) -> float:
    """Option value. `kind` is 'call' or 'put'. T in years."""
    if T <= 0:
        return max(0.0, (S - K) if kind == "call" else (K - S))
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    if d1 is None:
        return max(0.0, (S - K) if kind == "call" else (K - S))
    df_r, df_q = math.exp(-r * T), math.exp(-q * T)
    if kind == "call":
        return S * df_q * _cdf(d1) - K * df_r * _cdf(d2)
    return K * df_r * _cdf(-d2) - S * df_q * _cdf(-d1)


def greeks(S: float, K: float, T: float, r: float, sigma: float,
           kind: str, q: float = 0.0) -> Greeks:
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (S - K) if kind == "call" else (K - S))
        d = (1.0 if S > K else 0.0) if kind == "call" else (-1.0 if S < K else 0.0)
        return Greeks(intrinsic, d, 0.0, 0.0, 0.0, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    df_r, df_q = math.exp(-r * T), math.exp(-q * T)
    sqrtT = math.sqrt(T)
    gamma = df_q * _pdf(d1) / (S * sigma * sqrtT)
    vega = S * df_q * _pdf(d1) * sqrtT
    if kind == "call":
        delta = df_q * _cdf(d1)
        theta = (-S * df_q * _pdf(d1) * sigma / (2 * sqrtT)
                 - r * K * df_r * _cdf(d2) + q * S * df_q * _cdf(d1))
        rho = K * T * df_r * _cdf(d2)
    else:
        delta = -df_q * _cdf(-d1)
        theta = (-S * df_q * _pdf(d1) * sigma / (2 * sqrtT)
                 + r * K * df_r * _cdf(-d2) - q * S * df_q * _cdf(-d1))
        rho = -K * T * df_r * _cdf(-d2)
    return Greeks(price(S, K, T, r, sigma, kind, q), delta, gamma, vega, theta, rho)


def strike_for_delta(S: float, T: float, r: float, sigma: float, target_delta: float,
                     kind: str, q: float = 0.0) -> float:
    """Invert delta -> strike by bisection.

    `target_delta` is given as a positive magnitude (0.16 means 16-delta, whether
    the leg is a put or a call).
    """
    if T <= 0 or sigma <= 0:
        return S
    lo, hi = S * 0.20, S * 3.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        d = abs(greeks(S, mid, T, r, sigma, kind, q).delta)
        if kind == "put":
            # put |delta| DEcreases as strike falls
            if d > target_delta:
                hi = mid
            else:
                lo = mid
        else:
            # call delta DEcreases as strike rises
            if d > target_delta:
                lo = mid
            else:
                hi = mid
        if abs(hi - lo) < 1e-6:
            break
    return 0.5 * (lo + hi)
