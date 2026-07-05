"""Métriques de performance/risque sur une série de rendements hebdo simples."""
import numpy as np

WEEKS = 52.0


def equity_curve(returns: np.ndarray) -> np.ndarray:
    """Équité composée à partir de rendements simples (base 1.0)."""
    return np.cumprod(1.0 + np.asarray(returns, float))


def max_drawdown(returns: np.ndarray) -> float:
    """Max drawdown (fraction positive, ex. 0.32 = -32%) sur l'équité composée."""
    eq = equity_curve(returns)
    peak = np.maximum.accumulate(eq)
    dd = 1.0 - eq / peak
    return float(np.max(dd))


def cagr(returns: np.ndarray) -> float:
    eq = equity_curve(returns)
    n = len(returns)
    if n == 0 or eq[-1] <= 0:
        return float("nan")
    return float(eq[-1] ** (WEEKS / n) - 1.0)


def vol_annual(returns: np.ndarray) -> float:
    return float(np.std(returns, ddof=1) * np.sqrt(WEEKS))


def sharpe(returns: np.ndarray, rf: float = 0.0) -> float:
    v = vol_annual(returns)
    if v == 0:
        return float("nan")
    return float((cagr(returns) - rf) / v)


def calmar(returns: np.ndarray) -> float:
    """Rendement annualisé / max drawdown — le ratio 'juge de paix' du pilotage DD."""
    mdd = max_drawdown(returns)
    if mdd <= 1e-9:
        return float("nan")
    return float(cagr(returns) / mdd)


def cdar(returns: np.ndarray, alpha: float = 0.95) -> float:
    """CDaR ex-post (Conditional Drawdown at Risk) sur l'équité composée.

    Moyenne des drawdowns au-delà du quantile alpha. Sert au reporting ;
    l'optimiseur, lui, minimise le CDaR sur les cumuls non-composés (LP).
    """
    eq = equity_curve(returns)
    peak = np.maximum.accumulate(eq)
    dd = 1.0 - eq / peak
    thr = np.quantile(dd, alpha)
    tail = dd[dd >= thr]
    return float(tail.mean()) if len(tail) else 0.0


def summary(returns: np.ndarray, alpha: float = 0.95) -> dict:
    r = np.asarray(returns, float)
    return {
        "cagr": round(cagr(r), 4),
        "vol": round(vol_annual(r), 4),
        "sharpe": round(sharpe(r), 3),
        "max_drawdown": round(max_drawdown(r), 4),
        "cdar95": round(cdar(r, alpha), 4),
        "calmar": round(calmar(r), 3),
    }
