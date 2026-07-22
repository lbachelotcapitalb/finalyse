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
import scipy.optimize as _sciopt

WK = 52.0

# Jeu de facteurs EUR DÉCOLLINÉARISÉ (natif EUR quand possible → sans bruit FX ;
# US converti via to_eur sinon). Symbole EODHD + faut-il convertir en EUR.
# Valider/étendre ce jeu est la clé pour un entraînement (train_prior) fiable.
EUR_FACTOR_SYMBOLS = {
    "WORLD":  ("VFINX.US", True),      # actions US/monde (FX réel pour un EUR)
    "EUROPE": ("MSE.PA", False),       # MSCI Europe — NATIF EUR
    "EM":     ("VEIEX.US", True),      # émergents
    "BONDS":  ("IBCX.LSE", False),     # € Corporate — NATIF EUR
    "RE":     ("IPRP.LSE", False),     # foncières EU — NATIF EUR
    "INFRA":  ("XLU.US", True),        # infra (proxy utilities)
    "GOLD":   ("XAUUSD.FOREX", True),
    # "CASH" : synthétique (~monétaire), ajouté à 0 dans le tableau de facteurs
}

# Priors d'exposition économique par catégorie. Portent le VRAI risque quand la
# donnée du fonds est trop pauvre. (v) = validé/affiné par entraînement sur fonds
# réel (confiance élevée) ; les autres sont posés par bon sens économique.
CATEGORY_PRIORS = {
    "OPCI":             {"RE": 0.62, "BONDS": 0.28, "CASH": 0.10},   # immo + poche liquide
    "SCPI":             {"RE": 0.92, "CASH": 0.08},
    "INFRA_NON_COTE":   {"INFRA": 0.65, "WORLD": 0.15, "BONDS": 0.20},
    "MIXTE_PRUDENT":    {"EUROPE": 0.32, "BONDS": 0.33, "CASH": 0.25, "RE": 0.05, "WORLD": 0.05},  # (v) DNCA Eurose
    "MIXTE_EQUILIBRE":  {"WORLD": 0.30, "EUROPE": 0.30, "BONDS": 0.30, "CASH": 0.10},
    "FLEXIBLE_OFFENSIF": {"WORLD": 0.35, "EUROPE": 0.35, "GOLD": 0.12, "CASH": 0.13, "RE": 0.05},  # (v) R-co Valor
    "ACTIONS_MONDE":    {"WORLD": 0.70, "EUROPE": 0.30},
    "ACTIONS_EUROPE":   {"EUROPE": 0.90, "WORLD": 0.10},              # (v) Moneta Multi Caps
    "OBLIGATIONS":      {"BONDS": 0.90, "CASH": 0.10},
    "MONETAIRE":        {"CASH": 1.00},
}


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


# ---------------------------------------------------------------------------
# Panier multi-facteurs pour UC pauvres en données (mieux qu'un proxy unique)
# ---------------------------------------------------------------------------
def fit_basket(fund_returns, factors_df, prior_weights, strength=6.0, blend=True):
    """Ajuste un panier de facteurs aux rendements du fonds, RIDGE vers un prior
    de catégorie. Peu de points → reste près du prior (exposition économique
    connue = vrai risque) ; beaucoup de points → suit l'ajustement. Poids ≥ 0 (NNLS).

    Renvoie (weights: dict, r2, n_obs). Fréquence libre (annuelle si c'est tout
    ce qu'on a) — les poids s'appliqueront ensuite à la granularité fine.
    """
    facs = list(factors_df.columns)
    prior = np.array([prior_weights.get(f, 0.0) for f in facs])
    df = pd.concat([pd.Series(fund_returns).rename("y"), factors_df], axis=1).dropna()
    if len(df) < 2:
        return dict(prior_weights), 0.0, len(df)
    y, F, n = df["y"].values, df[facs].values, len(df)
    lam = strength / n                                   # + de data → - de shrinkage
    A = np.vstack([F, np.sqrt(lam) * np.eye(len(facs))])
    b = np.concatenate([y, np.sqrt(lam) * prior])
    w, _ = _sciopt.nnls(A, b)
    pred = F @ w
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
    r2 = 1.0 - float(np.sum((y - pred) ** 2)) / ss_tot
    # fond l'ajustement vers le prior au prorata de la confiance-données :
    # peu/mauvaise data (r2 bas, n petit) → on garde le prior (vrai risque connu).
    if not blend:                                        # entraînement : on laisse parler la donnée
        return {f: float(wi) for f, wi in zip(facs, w) if wi > 1e-4}, r2, n
    c = max(0.0, min(1.0, r2)) * (n / (n + 6.0))
    bl = {f: c * wi + (1 - c) * prior_weights.get(f, 0.0) for f, wi in zip(facs, w)}
    return {f: v for f, v in bl.items() if v > 1e-4}, r2, n


def couple_spliced(proxy_returns, fund_real_returns, fee_annual=0.0, seed=7,
                   ppy=WK, unsmooth=False):
    """BACKFILL CALIBRÉ (« la data alimente le proxy ») — le bon compromis entre
    remplacement strict (perd les crises longues) et mix pondéré (ad hoc).

    Là où la VRAIE série du fonds existe (récent, ex. 5 ans Quantalys) → on l'utilise
    telle quelle (comportement réel, régime récent). Avant → reconstruction du proxy
    CALIBRÉE sur le recouvrement : on estime (α, β, vol résiduelle) du fonds contre
    le proxy sur l'overlap, puis on les extrapole sur le passé profond (crises réelles
    conservées). Séries CHAÎNÉES (rendements → pas de saut de niveau).

    unsmooth=True : dé-lisse d'abord la série réelle (Geltner) — À METTRE pour une VL
    d'expert lissée (OPCI/SCPI/infra non coté), sinon on ré-injecte le lissage qu'on
    combat. Pour un fonds LIQUIDE (VL de marché), laisser False.

    Renvoie (série_hebdo, meta) où meta = {beta, alpha, resid, r2, n_overlap,
    confiance, debut_reel}. Repli sur `couple` (calibration de niveau) si < 8 points réels.
    """
    proxy = pd.Series(proxy_returns).dropna()
    real = pd.Series(fund_real_returns).dropna()
    if len(real) < 8:
        return couple(proxy, fee_annual, seed=seed, ppy=ppy), {"confiance": 0, "note": "réel insuffisant → calibration de niveau"}
    if unsmooth:
        vals, _phi = unsmooth_geltner(real.values)
        real = pd.Series(vals, index=real.index)
    a_net, beta, resid = estimate_factor(real, proxy)
    ov = pd.concat([real.rename("f"), proxy.rename("p")], axis=1).dropna()
    r2 = 0.0
    if len(ov) >= 8 and ov["p"].var() > 0:
        pred = a_net + beta * ov["p"].values
        ss = float(((ov["f"].values - ov["f"].mean()) ** 2).sum()) or 1.0
        r2 = 1.0 - float(((ov["f"].values - pred) ** 2).sum()) / ss
    fee_p = _fee_per_period(fee_annual, ppy)
    cutoff = real.index.min()
    deep = proxy[proxy.index < cutoff]
    recon_deep = reconstruct(deep, beta, a_net + fee_p, fee_annual, resid, seed, ppy)
    recent = real[real.index >= cutoff]
    out = pd.concat([recon_deep, recent])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    conf, lvl = confidence(r2, len(ov), smoothed=unsmooth)
    meta = {"beta": round(beta, 3), "alpha": round(a_net, 6), "resid": round(resid, 5),
            "r2": round(r2, 3), "n_overlap": len(ov), "confiance": conf, "niveau": lvl,
            "debut_reel": str(cutoff.date()) if hasattr(cutoff, "date") else str(cutoff)}
    return out, meta


def couple_basket(factors_fine, weights, fee_annual=0.0, realized_annual=None,
                  ppy=WK):
    """Reconstruit la série longue à partir d'un panier ajusté (weights) appliqué
    aux facteurs à granularité fine. Niveau calé sur le réalisé NET si fourni,
    frais réels déduits. → deux UC de même thème diffèrent par panier + niveau + frais.
    """
    r = sum(factors_fine[f] * w for f, w in weights.items() if f in factors_fine)
    fee_p = _fee_per_period(fee_annual, ppy)
    if realized_annual is not None:
        tgt = (1 + realized_annual) ** (1 / ppy) - 1
        r = r - r.mean() + tgt + fee_p                   # cale le NET après déduction des frais
    return r - fee_p


# Correspondance « classe d'actif publiée » (composition scrapée) → facteur moteur.
# LISTE ORDONNÉE : le plus spécifique d'abord (émergent/europe avant « action » générique).
ASSET_CLASS_TO_FACTOR = [
    ("emergent", "EM"), ("émergent", "EM"),
    ("europe", "EUROPE"),
    ("immobil", "RE"), ("foncier", "RE"), ("real estate", "RE"), ("reit", "RE"), ("scpi", "RE"),
    ("infrastructure", "INFRA"), ("infra", "INFRA"),
    ("obligation", "BONDS"), ("oblig", "BONDS"), ("taux", "BONDS"), ("bond", "BONDS"),
    ("liquidit", "CASH"), ("monetaire", "CASH"), ("monétaire", "CASH"), ("tresorerie", "CASH"),
    ("trésorerie", "CASH"), ("cash", "CASH"),
    ("gold", "GOLD"), ("métaux précieux", "GOLD"), ("matieres", "COMMOD"), ("matières", "COMMOD"),
    ("action", "WORLD"), ("equity", "WORLD"),   # générique en DERNIER
]


def composition_to_basket(composition, mapping=None):
    """Convertit une COMPOSITION publiée du fonds (scrapée) en panier de facteurs.

    composition : {libellé_classe: poids} — ex. {'Immobilier':0.58,'Obligations':0.32,'Liquidités':0.10}.
    → {facteur: poids} agrégé et normalisé. C'est le meilleur prior possible :
    la vraie allocation du fonds, pas une catégorie générique. Classes non
    reconnues ignorées (le reste renormalisé). Match spécifique avant générique.
    """
    mp = mapping or ASSET_CLASS_TO_FACTOR
    basket = {}
    for label, w in composition.items():
        lab = str(label).strip().lower()
        fac = next((f for k, f in mp if k in lab), None)
        if fac:
            basket[fac] = basket.get(fac, 0.0) + float(w)
    s = sum(basket.values())
    return {f: w / s for f, w in basket.items()} if s > 0 else {}


def train_prior(category_returns, factors_df, base_prior=None, strength=1.0):
    """Calibre EMPIRIQUEMENT un prior de catégorie à partir de rendements RÉELS
    représentatifs (indice de catégorie ou moyenne de fonds). Renvoie {facteur: poids}.

    ⚠️ FIABLE UNIQUEMENT avec un jeu de facteurs propre : facteurs actions
    MULTI-RÉGIONS distincts (Europe/US/Monde/Émergents), NON collinéaires (éviter
    de tous les convertir via le même FX), sinon le NNLS distribue les poids à tort
    (un fonds 100% actions peut ressortir avec des obligations). En pratique, la
    COMPOSITION RÉELLE scrapée (composition_to_basket) est un prior bien plus sûr
    que l'entraînement statistique. `train_prior` = repli quand aucune compo dispo.
    """
    base = base_prior or {f: 1.0 / len(factors_df.columns) for f in factors_df.columns}
    w, _r2, _n = fit_basket(category_returns, factors_df, base, strength, blend=False)
    s = sum(w.values())
    return {f: v / s for f, v in w.items()} if s > 0 else base


def confidence(r2, n_obs, smoothed=False):
    """Score 0-100 : part 'pilotée par la donnée' vs 'pilotée par le prior'.
    Pénalise le peu d'observations et la valorisation lissée (VL d'expert).
    """
    data = max(0.0, min(1.0, r2)) * (n_obs / (n_obs + 6.0))
    if smoothed:
        data *= 0.6
    lvl = "donnée" if data > 0.5 else ("mixte" if data > 0.2 else "prior")
    return round(100 * data), lvl
