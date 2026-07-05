"""Univers d'actifs — socle multi-classes (v1).

12 lignes couvrant actions (zones + taille), obligataire (duration + crédit),
réel (or, matières premières, immobilier coté) et protection inflation.

Pour le prototype on utilise des ETF US à longue histoire (Stooq les couvre
proprement). En PRODUCTION, chaque ligne se mappe sur son équivalent UCITS
distribuable en Europe (même exposition) — le mapping est porté ici pour être
la seule source de vérité quand on branchera EODHD.

CAVEAT DONNÉES (proto) : les séries Stooq gratuites sont price-return, pas
total-return. Les lignes à fort rendement distribué (TLT, HYG, LQD, VNQ) sont
donc sous-estimées. On valide ici la PLOMBERIE du modèle, pas les chiffres
d'allocation définitifs — ceux-ci exigent adjusted_close (EODHD) en prod.
"""

# clé interne -> (ticker Stooq proto, classe, libellé FR, équivalent UCITS cible)
SOCLE = {
    "US_LARGE":   ("spy.us", "Actions",     "Actions US large cap",         "IWDA/CSPX (S&P 500 / World)"),
    "US_SMALL":   ("iwm.us", "Actions",     "Actions US small cap",         "IUSN (World Small Cap)"),
    "DEV_EXUS":   ("efa.us", "Actions",     "Actions dév. hors US (EAFE)",  "EXUS/IWDA ex-US"),
    "EMERGING":   ("eem.us", "Actions",     "Actions émergentes",           "EIMI (EM IMI)"),
    "TREAS_LONG": ("tlt.us", "Oblig. souv.", "Souverain US long (20+ ans)", "DTLA (US Treas 20+)"),
    "TREAS_MID":  ("ief.us", "Oblig. souv.", "Souverain US 7-10 ans",       "IDTM / gouv. EUR moyen terme"),
    "CORP_IG":    ("lqd.us", "Crédit",      "Crédit IG US",                 "LQDE (USD IG Corp)"),
    "HIGH_YIELD": ("hyg.us", "Crédit",      "High yield US",                "IHYU (USD HY Corp)"),
    "GOLD":       ("gld.us", "Réel",        "Or",                           "SGLN / PHAU (or physique)"),
    "COMMOD":     ("dbc.us", "Réel",        "Matières premières large",     "ICOM (Bloomberg Commodity)"),
    "REIT":       ("vnq.us", "Réel",        "Immobilier coté (SIIC/REIT)",  "IWDP (Developed Property)"),
    "TIPS":       ("tip.us", "Inflation",   "Obligations indexées inflation", "IBCI / TIPS EUR"),
}

# Benchmark par défaut : 60/40 actions monde / obligations souveraines.
# On l'exprime dans l'univers pour pouvoir comparer sur la MÊME fenêtre de données.
BENCHMARK_6040 = {"US_LARGE": 0.60, "TREAS_MID": 0.40}

# Univers « deep history » (≥25 ans) : mêmes expositions via des fonds indiciels
# à VL longue (Vanguard, années 80-90) + or spot. Sert les backtests longs
# incluant la bulle dot-com 2000-2002 — que les ETF (nés 2004-2007) ratent.
# Commodités large exclue faute de série propre >20 ans ; l'or représente le réel.
DEEP_HISTORY = {
    "US_LARGE":   "VFINX.US",
    "US_SMALL":   "NAESX.US",
    "DEV_EXUS":   "VGTSX.US",
    "EMERGING":   "VEIEX.US",
    "TREAS_LONG": "VUSTX.US",
    "TREAS_MID":  "VFITX.US",
    "CORP_IG":    "VWESX.US",
    "HIGH_YIELD": "VWEHX.US",
    "REIT":       "VGSIX.US",
    "TIPS":       "VIPSX.US",
    "GOLD":       "XAUUSD.FOREX",
}

# --- Univers UC assurance-vie (fonds réels par ISIN.EUFUND, testés couverts) ---
UC_SOCLE = {
    "CARMIGNAC_PAT": ("FR0010135103.EUFUND", "Carmignac Patrimoine (mixte flexible)"),
    "DNCA_EUROSE":   ("LU0284394235.EUFUND", "DNCA Invest Eurose (prudent mixte)"),
    "RCO_VALOR":     ("FR0011261197.EUFUND", "R-co Valor (flexible offensif)"),
    "COMGEST_MONDE": ("FR0000284689.EUFUND", "Comgest Monde (actions monde qualité)"),
    "MONETA_MC":     ("FR0010298596.EUFUND", "Moneta Multi Caps (actions France)"),
    "ECHIQUIER_AGR": ("FR0011435197.EUFUND", "Echiquier Agressor (actions Europe)"),
}
UC_SYMBOLS = {k: v[0] for k, v in UC_SOCLE.items()}
UC_LABELS = {k: v[1] for k, v in UC_SOCLE.items()}

# --- Univers UCITS/PEA coté (mêmes CLÉS que SOCLE → benchmark & labels réutilisés).
#     Symboles EODHD résolus par scripts/discover_ucits.py. UCITS = jeunes (post-2010,
#     tranches oblig. 2018-2019) → fenêtre commune ~7 ans ; la longue histoire passe par
#     DEEP_HISTORY. TIPS retiré (seule tranche UCITS trouvée = 0-5 née 2025, inutilisable). ---
UCITS_SYMBOLS = {
    "US_LARGE":   "CSP1.LSE",     # iShares Core S&P 500 UCITS (IE00B5BMR087)
    "US_SMALL":   "IUSN.XETRA",   # iShares MSCI World Small Cap UCITS (IE00BF4RFH31)
    "DEV_EXUS":   "SWDA.LSE",     # iShares Core MSCI World UCITS (IE00B4L5Y983)
    "EMERGING":   "EIMU.LSE",     # iShares Core MSCI EM IMI UCITS (IE00BD45KH83)
    "TREAS_LONG": "DTLA.LSE",     # iShares $ Treasury 20+yr UCITS (IE00BFM6TC58)
    "TREAS_MID":  "IGTM.LSE",     # iShares $ Treasury 7-10yr UCITS (IE00BGPP6580)
    "CORP_IG":    "LQDA.LSE",     # iShares $ Corp Bond UCITS (IE00BYXYYJ35)
    "HIGH_YIELD": "SDHA.LSE",     # iShares $ Short Dur. HY Corp UCITS (IE00BZ17CN18)
    "GOLD":       "SGLN.LSE",     # iShares Physical Gold ETC (IE00B4ND3602)
    "COMMOD":     "ICOM.LSE",     # iShares Diversified Commodity Swap UCITS (IE00BDFL4P12)
    "REIT":       "IDWP.LSE",     # iShares Dev. Markets Property Yield UCITS (IE00B1FZS350)
}

TICKERS = {k: v[0] for k, v in SOCLE.items()}
CLASSES = {k: v[1] for k, v in SOCLE.items()}
LABELS = {k: v[2] for k, v in SOCLE.items()}
UCITS_TARGET = {k: v[3] for k, v in SOCLE.items()}
KEYS = list(SOCLE.keys())
