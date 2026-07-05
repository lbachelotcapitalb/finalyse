# LEARNINGS — finalyse

Enseignements curés au fil des itérations. Le classement chiffré vit dans
`INDEX.md` (auto) ; ici on garde le **pourquoi** — édité à la main / par l'IA.

## Modèle

- **Piloter par le CDaR, pas le MaxDD brut.** Le max drawdown est mono-trajectoire
  (une seule pire ligne réalisée) → sur-ajusté. Le CDaR (moyenne des pires
  drawdowns au-delà d'un quantile) est convexe et stable. Le MaxDD reste en
  reporting, jamais en objectif.
- **Overfitting du drawdown, confirmé sur données réelles.** La variante
  `cdar_budget` (rendement max sous budget DD, dépendant des μ) promet ~8 % de
  CDaR in-sample mais réalise jusqu'à **−40 % de MaxDD hors-échantillon** sur
  25 ans / 22 fenêtres. Le `min_cdar` (sans forecast de rendement) tient sa
  promesse (ratio réalisé/promis ≈ 1). Leçon : se méfier des portefeuilles qui
  s'appuient sur les rendements espérés ; privilégier le risk-based.
- **Les rendements espérés produisent des coins.** Le maximiseur de rendement
  tape les plafonds `wmax` sur 2-3 lignes. C'est la fragilité classique des μ →
  motive Black-Litterman / shrinkage en v2.
- **Biais de récence sur l'or.** 2000-2026 fut une période exceptionnelle pour
  l'or (faible corrélation + forte perf) → l'optimiseur le surpondère (15-35 %).
  Correct sur ces données mais à surveiller ; le walk-forward l'atténue.

## Données

- **EODHD « All World » (20 €/mois) suffit pour démarrer.** Coté par `TICKER.US`,
  or par `XAUUSD.FOREX`, fonds/UC par `ISIN.EUFUND`. `adjusted_close` = total
  return (règle le piège dividendes).
- **UC françaises classiques : couvertes avec VL profondes.** Carmignac
  Patrimoine (FR0010135103) remonte à **1995** (31 ans). Quantalys Pôle Data
  seulement pour d'éventuelles UC niche/assureur manquantes.
- **25 ans impossibles avec les ETF** (HYG né 2007 borne à ~19 ans). Résolu par
  des **proxys fonds indiciels longue histoire** (Vanguard VFINX/VWEHX… +
  or spot) → fenêtre commune **25,9 ans (2000-2026), dot-com incluse**.
- Yahoo/Stooq/FRED sont bloqués depuis cette machine (429 / anti-bot / timeout) ;
  EODHD passe. Ne pas dépendre du scraping live.

## Méthode

- Toujours **walk-forward + contrôle d'honnêteté** avant de croire un backtest.
- Comparer les runs via `INDEX.md` (Calmar de l'équilibré) : même rendement +
  drawdown plus faible = mieux.
