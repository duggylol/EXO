"""
Performance + selection-bias metrics (Bailey & López de Prado).

The headline tool is the Deflated Sharpe Ratio (DSR): it discounts an observed
Sharpe for (a) how many strategy/parameter variants you tried, and (b) the
non-Normality of the returns, then returns the PROBABILITY the edge is real.

The point: a backtest Sharpe means nothing without the number of trials behind
it. If DSR < 0.95, treat the "edge" as a likely fluke.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import kurtosis, norm, skew

EULER = 0.5772156649015329


def sharpe(returns) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    s = r.std(ddof=1)
    return float(r.mean() / s) if s > 0 else 0.0


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected MAXIMUM Sharpe across N independent trials when the true SR is 0
    (the False Strategy Theorem). This is the bar a real edge must clear."""
    n = max(2, int(n_trials))
    z = (1 - EULER) * norm.ppf(1 - 1.0 / n) + EULER * norm.ppf(1 - 1.0 / (n * np.e))
    return float(np.sqrt(max(sr_variance, 0.0)) * z)


def probabilistic_sharpe(returns, sr_benchmark: float = 0.0) -> float:
    """P(true SR > benchmark), correcting for skew/kurtosis and sample length.
    `sharpe` here is per-observation (non-annualized), matching the inputs."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    T = r.size
    if T < 3:
        return float("nan")
    sr = sharpe(r)
    sk = float(skew(r))
    ku = float(kurtosis(r, fisher=False))   # 3.0 == Normal
    denom = 1.0 - sk * sr + ((ku - 1.0) / 4.0) * sr ** 2
    if denom <= 0:
        return float("nan")
    z = (sr - sr_benchmark) * np.sqrt(T - 1) / np.sqrt(denom)
    return float(norm.cdf(z))


def deflated_sharpe(returns, n_trials: int, sr_variance: float) -> tuple[float, float]:
    """Returns (DSR probability, SR0 benchmark). DSR > 0.95 => edge survives
    multiple-testing + non-Normality at 95% confidence."""
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    return probabilistic_sharpe(returns, sr_benchmark=sr0), sr0


def annualized_sharpe(per_trade_returns, trades_per_year: float) -> float:
    return sharpe(per_trade_returns) * np.sqrt(max(trades_per_year, 1.0))
