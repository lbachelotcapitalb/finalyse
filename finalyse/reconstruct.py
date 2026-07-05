"""Reconstruction longue-histoire de fonds mal/non sourcés (VL de marché absente
ou trop courte), par couplage proxy ↔ réalité du fonds.

PROBLÈME : deux UC de même thème mappées sur le même proxy liquide auraient des
statistiques identiques, alors qu'en réalité elles diffèrent (frais, skill, style,
structure). Les coller au même proxy serait faux.

SOLUTION — modèle factoriel calibré, frais réels appliqués :

    r_fonds(t) = alpha + beta · r_proxy(t) + residu(t) − frais_annuels

- beta   : intensité d'exposition au facteur (estimée sur l'overlap fonds↔proxy)
- alpha  : style/skill propre (estimé sur l'overlap ; gross de frais)
- residu : idiosyncratique (vol résiduelle, pour le MC / les queues)
- frais  : DÉTERMINISTE et CONNU par UC — le différenciateur le plus propre

→ deux fonds de même thème partagent le risque systématique du proxy (crises,
  volatilité, drawdown longue histoire) mais divergent par (alpha, beta, residu)
  et par leurs FRAIS réels. Là où la vraie VL fine du fonds existe, on l'utilise
  directement ; le proxy ne sert qu'au backfill / aux fonds sans VL.

Les fonds à valorisation d'expert (OPCI, SCPI, infra non coté) sont d'abord
DÉ-LISSÉS (Geltner) quand on dispose de leur VL, pour retrouver la vraie vol.
"""
import numpy as np
import pandas as pd

WK = 52.0


def to_eur(prices_usd, eurusd_prices):
    """Convertit une série de PRIX en USD vers EUR via EURUSD (= USD par EUR).
    Permet de rapatrier des proxys profonds US (25+ ans) en base EUR, plutôt que
    d'être borné par l'inception tardive des ETF UCITS libellés EUR.
    """
    fx = eurusd_prices.reindex(prices_usd.index).ffill()
    return (prices_usd / fx).dropna()


def unsmooth_geltner(returns, phi=None):
    """Dé-lissage de Geltner : r_vrai = (r_obs − φ·r_obs,t−1) / (1−φ).

    Les VL d'expert (immo, infra non coté) sont autocorrélées (lissées) → vol
    sous-estimée. φ = autocorrélation lag-1 si non fourni. Renvoie (série, φ).
    """
    r = np.asarray(returns, float)
    if phi is None:
        if len(r) < 4 or np.std(r[:-1]) == 0:
            phi = 0.0
        else:
            phi = float(np.clip(np.corrcoef(r[1:], r[:-1])[0, 1], 0.0, 0.9))
    out = r.astype(float).copy()
    if phi > 0:
        out[1:] = (r[1:] - phi * r[:-1]) / (1 - phi)
    return out, phi


def estimate_factor(fund_returns, proxy_returns):
    """OLS fonds ~ alpha + beta·proxy sur l'index commun.
    Renvoie (alpha_net_par_periode, beta, vol_residuelle). alpha est NET (tel quel).
    """
    df = pd.concat([pd.Series(fund_returns).rename("f"),
                    pd.Series(proxy_returns).rename("p")], axis=1).dropna()
    if len(df) < 8 or df["p"].var() == 0:
        return 0.0, 1.0, float(np.std(df["f"])) if len(df) else 0.0
    f, p = df["f"].values, df["p"].values
    beta = float(np.cov(f, p)[0, 1] / np.var(p))
    alpha = float(f.mean() - beta * p.mean())
    resid = f - (alpha + beta * p)
    return alpha, beta, float(resid.std())


def _fee_per_period(fee_annual, freq=WK):
    return (1 + fee_annual) ** (1 / freq) - 1


def reconstruct(proxy_returns, beta=1.0, alpha=0.0, fee_annual=0.0,
                resid_vol=0.0, seed=7, ppy=WK):
    """Série longue reconstruite à la granularité du proxy :
    alpha + beta·proxy + residu − frais. (alpha ici = gross, frais déduits à part.)
    ppy = périodes/an (52 hebdo, 252 quotidien) pour le calcul des frais.
    """
    idx = proxy_returns.index if hasattr(proxy_returns, "index") else None
    p = np.asarray(getattr(proxy_returns, "values", proxy_returns), float)
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, resid_vol, len(p)) if resid_vol > 0 else 0.0
    r = alpha + beta * p + eps - _fee_per_period(fee_annual, ppy)
    return pd.Series(r, index=idx)


def couple(proxy_returns, fee_annual, fund_real_returns=None,
           fund_realized_annual=None, seed=7, ppy=WK):
    """Couple le proxy (risque systématique long) avec la réalité du fonds.

    Priorité des sources de vérité du fonds :
      1. fund_real_returns (VL fine réelle) → régression → (alpha, beta, residu).
      2. fund_realized_annual (rendement net annualisé connu, ex. relevé) → cale
         le NIVEAU (beta=1), pas de residu.
      3. rien → suppose qu'il suit le proxy brut ; SEULS ses frais le distinguent.

    Dans tous les cas les FRAIS RÉELS du fonds sont appliqués → deux UC de même
    thème mais de frais/skill différents obtiennent des séries différentes.
    """
    fee_p = _fee_per_period(fee_annual, ppy)
    if fund_real_returns is not None and pd.Series(fund_real_returns).dropna().shape[0] >= 8:
        a_net, beta, resid = estimate_factor(fund_real_returns, proxy_returns)
        alpha_gross = a_net + fee_p                      # sépare les frais proprement
        return reconstruct(proxy_returns, beta, alpha_gross, fee_annual, resid, seed, ppy)
    beta = 1.0
    if fund_realized_annual is not None:
        tgt_p = (1 + fund_realized_annual) ** (1 / ppy) - 1
        alpha_gross = tgt_p - beta * float(np.mean(getattr(proxy_returns, "values", proxy_returns))) + fee_p
    else:
        alpha_gross = 0.0                                # suit le proxy brut ; frais seuls diffèrent
    return reconstruct(proxy_returns, beta, alpha_gross, fee_annual, 0.0, seed, ppy)
